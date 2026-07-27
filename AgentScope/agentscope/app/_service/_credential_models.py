# -*- coding: utf-8 -*-
"""Credential-scoped model catalogue, discovery, and test helpers."""
from __future__ import annotations

import asyncio
import copy
import json
import re
from time import perf_counter
from typing import Literal

import httpx
from pydantic import BaseModel, SecretStr

from ...credential import (
    CredentialBase,
    CredentialModelDefinition,
)
from ...embedding import EmbeddingModelCard
from ...message import UserMsg
from ...model import ChatResponse, FinishedReason, ModelCard
from ...types import ErrorType
from ._errors import _classify_error

_DISCOVERABLE_CREDENTIAL_TYPES = {
    "custom_openai_credential",
    "openai_credential",
    "dashscope_credential",
    "deepseek_credential",
    "moonshot_credential",
    "xai_credential",
}
_OPENAI_SDK_CREDENTIAL_TYPES = {
    "custom_openai_credential",
    "openai_credential",
    "dashscope_credential",
    "deepseek_credential",
    "moonshot_credential",
}
_MAX_DISCOVERY_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_MODEL_TEST_RAW_RESPONSE_CHARS = 4_000
_MODEL_TEST_TIMEOUT_SECONDS = 30.0
_OPENAI_COMPATIBLE_EMBEDDING_TYPES = {
    "custom_openai_credential",
    "openai_credential",
    "dashscope_credential",
}


class CredentialModelEntry(ModelCard):
    """A model card plus its credential-scoped catalogue state."""

    source: Literal["builtin", "discovered", "manual"]
    enabled: bool


class CredentialEmbeddingModelEntry(EmbeddingModelCard):
    """An embedding model card plus credential-scoped catalogue state."""

    source: Literal["builtin", "discovered", "manual"]
    enabled: bool


class CredentialModelTestResult(BaseModel):
    """Sanitised result of one real, minimal model request."""

    success: bool
    model: str
    model_type: Literal["chat", "embedding"] = "chat"
    latency_ms: int
    dimensions: int | None = None
    error_type: ErrorType | None = None
    message: str
    status_code: int | None = None
    raw_response: str | None = None


class ModelDiscoveryError(Exception):
    """Safe, user-facing failure raised while querying ``GET /models``."""


class EmbeddingProbeError(Exception):
    """Embedding response failure with an optional HTTP status code."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        raw_response: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.raw_response = raw_response


def supports_model_discovery(credential: CredentialBase) -> bool:
    """Whether the credential exposes an OpenAI-compatible models API."""
    return getattr(credential, "type", None) in _DISCOVERABLE_CREDENTIAL_TYPES


def _discovery_base_url(credential: CredentialBase) -> str:
    credential_type = getattr(credential, "type", None)
    if credential_type == "openai_credential":
        return getattr(credential, "base_url", None) or (
            "https://api.openai.com/v1"
        )
    if credential_type == "xai_credential":
        host = str(getattr(credential, "api_host", "api.x.ai")).strip()
        if host.startswith(("http://", "https://")):
            return f"{host.rstrip('/')}/v1"
        return f"https://{host.rstrip('/')}/v1"
    base_url = getattr(credential, "base_url", None)
    if not isinstance(base_url, str) or not base_url.strip():
        raise ModelDiscoveryError("当前凭证没有可用于模型发现的 API 地址。")
    return base_url.strip().rstrip("/")


def _api_key(credential: CredentialBase) -> str:
    value = getattr(credential, "api_key", None)
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, str):
        return value
    raise ModelDiscoveryError("当前凭证没有可用于模型发现的 API Key。")


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """Return an exception and its causes without following cycles."""
    result: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        result.append(current)
        current = current.__cause__ or current.__context__
    return result


def _raw_value_to_text(value: object) -> str | None:
    """Convert an upstream response body into readable text."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return str(value)


def _redact_and_truncate_provider_response(
    value: str,
    credential: CredentialBase,
) -> str:
    """Hide credential secrets and bound an upstream error body."""
    redacted = value
    secrets = {
        item.get_secret_value()
        for item in credential.__dict__.values()
        if isinstance(item, SecretStr) and item.get_secret_value()
    }
    for secret in sorted(secrets, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")

    redacted = re.sub(
        r"(?i)(bearer\s+)[a-z0-9._~+/=-]+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        (
            r"(?i)([\"']?(?:api[_-]?key|authorization|access[_-]?token)"
            r"[\"']?\s*[:=]\s*[\"'])([^\"']+)"
        ),
        r"\1[REDACTED]",
        redacted,
    )

    if len(redacted) <= _MAX_MODEL_TEST_RAW_RESPONSE_CHARS:
        return redacted
    return (
        redacted[:_MAX_MODEL_TEST_RAW_RESPONSE_CHARS]
        + "\n… [response truncated]"
    )


def _provider_error_details(
    exc: Exception,
    credential: CredentialBase,
) -> tuple[int | None, str | None]:
    """Extract HTTP status and original upstream body from SDK exceptions."""
    status_code: int | None = None
    candidates: list[object] = []

    for current in _exception_chain(exc):
        if status_code is None:
            direct_status = getattr(current, "status_code", None)
            if isinstance(direct_status, int):
                status_code = direct_status

        raw_response = getattr(current, "raw_response", None)
        if raw_response:
            candidates.append(raw_response)

        response = getattr(current, "response", None)
        if response is not None:
            response_status = getattr(response, "status_code", None)
            if status_code is None and isinstance(response_status, int):
                status_code = response_status
            content = getattr(response, "content", None)
            if content:
                candidates.append(content)
            else:
                try:
                    response_text = getattr(response, "text", None)
                except Exception:
                    response_text = None
                if response_text:
                    candidates.append(response_text)

        body = getattr(current, "body", None)
        if body:
            candidates.append(body)

    if not candidates:
        candidates.append(str(exc))

    for candidate in candidates:
        text = _raw_value_to_text(candidate)
        if text and text.strip():
            return (
                status_code,
                _redact_and_truncate_provider_response(
                    text.strip(),
                    credential,
                ),
            )
    return status_code, None


def _model_parameter_schema(
    credential: CredentialBase,
    definition: CredentialModelDefinition,
) -> dict:
    """Build the same parameter form shape used by static model cards."""
    base_schema = (
        credential.get_chat_model_class().Parameters.model_json_schema()
    )
    properties = copy.deepcopy(base_schema.get("properties", {}))

    if not any(
        item.startswith("audio/")
        for item in definition.output_types
        if isinstance(item, str)
    ):
        properties.pop("voice", None)

    if "max_tokens" in properties:
        properties["max_tokens"]["maximum"] = definition.output_size

    return {
        "type": "object",
        "properties": properties,
        "required": base_schema.get("required", []),
    }


def _definition_to_card(
    credential: CredentialBase,
    definition: CredentialModelDefinition,
) -> ModelCard:
    return ModelCard(
        name=definition.name,
        label=definition.label or definition.name,
        status="active",
        input_types=definition.input_types,
        output_types=definition.output_types,
        context_size=definition.context_size,
        output_size=definition.output_size,
        parameter_schema=_model_parameter_schema(credential, definition),
        parameters_overrides={},
    )


def build_credential_model_catalog(
    credential: CredentialBase,
) -> list[CredentialModelEntry]:
    """Merge built-in, discovered, and manual models for one credential.

    Built-in model metadata wins over a duplicate discovery result. A manual
    definition intentionally wins over either source, allowing a user to tune
    the context/output limits for the service they actually use.
    """
    merged: dict[str, tuple[ModelCard, str]] = {}
    manual_embedding_ids = {
        definition.name
        for definition in credential.model_catalog.manual_models
        if definition.model_type == "embedding"
    }

    for card in credential.list_models():
        if card.name not in manual_embedding_ids:
            merged[card.name] = (card, "builtin")

    for definition in credential.model_catalog.discovered_models:
        if definition.model_type != "chat":
            continue
        if definition.name in manual_embedding_ids:
            continue
        if definition.name not in merged:
            merged[definition.name] = (
                _definition_to_card(credential, definition),
                "discovered",
            )

    for definition in credential.model_catalog.manual_models:
        if definition.model_type != "chat":
            continue
        merged[definition.name] = (
            _definition_to_card(credential, definition),
            "manual",
        )

    hidden = set(credential.model_catalog.hidden_model_ids)
    return [
        CredentialModelEntry.model_validate(
            {
                **card.model_dump(),
                "source": source,
                "enabled": name not in hidden,
            },
        )
        for name, (card, source) in merged.items()
    ]


def _embedding_parameter_schema(credential: CredentialBase) -> dict:
    """Build the parameter schema used by dynamic embedding cards."""
    embedding_cls = credential.get_embedding_model_class()
    if embedding_cls is None:
        return {"type": "object", "properties": {}, "required": []}
    base_schema = embedding_cls.Parameters.model_json_schema()
    return {
        "type": "object",
        "properties": copy.deepcopy(base_schema.get("properties", {})),
        "required": base_schema.get("required", []),
    }


def _definition_to_embedding_card(
    credential: CredentialBase,
    definition: CredentialModelDefinition,
) -> EmbeddingModelCard:
    """Convert a persisted embedding definition into a runtime model card."""
    if definition.dimensions is None:
        raise ValueError(
            f"Embedding model {definition.name!r} has no dimensions.",
        )
    return EmbeddingModelCard(
        name=definition.name,
        label=definition.label or definition.name,
        status="active",
        input_types=definition.input_types,
        output_types=["application/x-embedding"],
        dimensions=definition.dimensions,
        supported_dimensions=None,
        context_size=definition.context_size,
        parameter_schema=_embedding_parameter_schema(credential),
        parameter_overrides={},
    )


def build_credential_embedding_model_catalog(
    credential: CredentialBase,
) -> list[CredentialEmbeddingModelEntry]:
    """Merge built-in and credential-managed embedding model cards."""
    if credential.get_embedding_model_class() is None:
        return []

    manual_chat_ids = {
        definition.name
        for definition in credential.model_catalog.manual_models
        if definition.model_type == "chat"
    }
    merged: dict[str, tuple[EmbeddingModelCard, str]] = {
        card.name: (card, "builtin")
        for card in credential.list_embedding_models()
        if card.name not in manual_chat_ids
    }

    for definition in credential.model_catalog.discovered_models:
        if definition.model_type != "embedding":
            continue
        if definition.name in manual_chat_ids:
            continue
        if definition.name not in merged:
            merged[definition.name] = (
                _definition_to_embedding_card(credential, definition),
                "discovered",
            )

    for definition in credential.model_catalog.manual_models:
        if definition.model_type != "embedding":
            continue
        merged[definition.name] = (
            _definition_to_embedding_card(credential, definition),
            "manual",
        )

    hidden = set(credential.model_catalog.hidden_embedding_model_ids)
    return [
        CredentialEmbeddingModelEntry.model_validate(
            {
                **card.model_dump(),
                "source": source,
                "enabled": name not in hidden,
            },
        )
        for name, (card, source) in merged.items()
    ]


def _extract_model_ids(payload: object) -> list[str]:
    """Accept the OpenAI response and a few common compatible variants."""
    items: object
    if isinstance(payload, dict):
        items = payload.get("data", payload.get("models", []))
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    if not isinstance(items, list):
        return []

    identifiers: list[str] = []
    seen: set[str] = set()
    for item in items:
        identifier: object = item
        if isinstance(item, dict):
            identifier = item.get("id") or item.get("name") or item.get(
                "model",
            )
        if not isinstance(identifier, str):
            continue
        identifier = identifier.strip()
        if identifier and identifier not in seen:
            identifiers.append(identifier)
            seen.add(identifier)
    return sorted(identifiers, key=str.casefold)


async def discover_credential_models(
    credential: CredentialBase,
) -> list[CredentialModelDefinition]:
    """Query the provider's OpenAI-compatible ``GET /models`` endpoint."""
    if not supports_model_discovery(credential):
        raise ModelDiscoveryError(
            "当前厂商不支持 OpenAI 兼容的模型自动获取，请手动添加模型。",
        )

    url = f"{_discovery_base_url(credential)}/models"
    headers = {
        "Authorization": f"Bearer {_api_key(credential)}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise ModelDiscoveryError(
            "获取模型列表超时，请检查 API 地址或改为手动添加。",
        ) from exc
    except httpx.RequestError as exc:
        raise ModelDiscoveryError(
            "无法连接模型服务，请检查 API 地址和网络。",
        ) from exc

    if response.status_code in {401, 403}:
        raise ModelDiscoveryError(
            "模型服务拒绝了凭证，请检查 API Key。",
        )
    if response.status_code == 404:
        raise ModelDiscoveryError(
            "该服务未提供 OpenAI 兼容的 /models 接口，请手动添加模型。",
        )
    if response.status_code == 429:
        raise ModelDiscoveryError(
            "模型服务请求过于频繁，请稍后重试或手动添加模型。",
        )
    if not 200 <= response.status_code < 300:
        raise ModelDiscoveryError(
            f"模型服务返回 HTTP {response.status_code}，请检查配置。",
        )

    if len(response.content) > _MAX_DISCOVERY_RESPONSE_BYTES:
        raise ModelDiscoveryError("模型列表响应过大，已拒绝处理。")

    try:
        payload = json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelDiscoveryError(
            "模型服务返回的模型列表不是有效 JSON。",
        ) from exc

    model_ids = _extract_model_ids(payload)
    if not model_ids:
        raise ModelDiscoveryError(
            "模型服务没有返回可识别的模型，请手动添加模型。",
        )

    return [
        CredentialModelDefinition(name=model_id)
        for model_id in model_ids
    ]


async def test_credential_model(
    credential: CredentialBase,
    model_name: str,
) -> CredentialModelTestResult:
    """Send one minimal, non-streaming request through the real adapter.

    The request asks for a one-word reply, disables retries, and has a hard
    timeout so clicking the UI button cannot silently trigger repeated calls
    or leave the request hanging indefinitely. No explicit token parameter is
    sent because older OpenAI-compatible services may reject the newer
    ``max_completion_tokens`` field. Provider exception details are classified
    and sanitised before returning to the browser.
    """
    started_at = perf_counter()

    async def _invoke() -> None:
        model_cls = credential.get_chat_model_class()
        parameters = model_cls.Parameters()
        client_kwargs: dict[str, int | float] = {}
        credential_type = getattr(credential, "type", None)
        if credential_type in _OPENAI_SDK_CREDENTIAL_TYPES:
            # The OpenAI SDK otherwise performs its own retries underneath
            # AgentScope, turning one button click into multiple requests.
            client_kwargs = {
                "max_retries": 0,
                "timeout": 20.0,
            }
        elif credential_type == "anthropic_credential":
            client_kwargs = {
                "max_retries": 0,
                "timeout": 20.0,
            }
        elif credential_type == "ollama_credential":
            client_kwargs = {"timeout": 20.0}

        model = model_cls(
            credential=credential,
            model=model_name,
            parameters=parameters,
            stream=False,
            max_retries=0,
            client_kwargs=client_kwargs,
        )
        response = await model(
            [
                UserMsg(
                    name="model-test",
                    content="Reply with only OK.",
                ),
            ],
        )

        if isinstance(response, ChatResponse):
            if response.finished_reason == FinishedReason.INTERRUPTED:
                raise TimeoutError("The model test timed out.")
            return

        async for chunk in response:
            if chunk.finished_reason == FinishedReason.INTERRUPTED:
                raise TimeoutError("The model test timed out.")

    try:
        await asyncio.wait_for(
            _invoke(),
            timeout=_MODEL_TEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # Provider SDKs expose many exception classes.
        error = _classify_error(exc)
        status_code, raw_response = _provider_error_details(
            exc,
            credential,
        )
        return CredentialModelTestResult(
            success=False,
            model=model_name,
            latency_ms=max(1, round((perf_counter() - started_at) * 1000)),
            error_type=error.type,
            message=error.message,
            status_code=status_code,
            raw_response=raw_response,
        )

    return CredentialModelTestResult(
        success=True,
        model=model_name,
        latency_ms=max(1, round((perf_counter() - started_at) * 1000)),
        message="Model request completed successfully.",
    )


def _embedding_dimensions_from_payload(payload: object) -> int:
    """Return the first vector length from an OpenAI-compatible response."""
    if not isinstance(payload, dict):
        raise EmbeddingProbeError(
            "Embedding response is not a JSON object.",
            422,
        )
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise EmbeddingProbeError(
            "Embedding response does not contain any vectors.",
            422,
        )
    first = data[0]
    if not isinstance(first, dict):
        raise EmbeddingProbeError(
            "Embedding response contains an invalid vector entry.",
            422,
        )
    vector = first.get("embedding", first.get("dense_embedding"))
    if not isinstance(vector, list) or not vector:
        raise EmbeddingProbeError(
            "Embedding response does not contain a usable vector.",
            422,
        )
    if not all(isinstance(value, (int, float)) for value in vector):
        raise EmbeddingProbeError(
            "Embedding response vector is not numeric.",
            422,
        )
    return len(vector)


async def _probe_openai_compatible_embedding(
    credential: CredentialBase,
    model_name: str,
) -> int:
    """Call ``POST /embeddings`` once without forcing a dimension."""
    url = f"{_discovery_base_url(credential)}/embeddings"
    headers = {
        "Authorization": f"Bearer {_api_key(credential)}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0),
        follow_redirects=False,
    ) as client:
        response = await client.post(
            url,
            headers=headers,
            json={
                "model": model_name,
                "input": "AgentScope embedding model test.",
            },
        )

    if not 200 <= response.status_code < 300:
        raise EmbeddingProbeError(
            "Embedding endpoint rejected the test request.",
            response.status_code,
            _raw_value_to_text(response.content),
        )
    if len(response.content) > _MAX_DISCOVERY_RESPONSE_BYTES:
        raise EmbeddingProbeError(
            "Embedding response is too large.",
            422,
            _raw_value_to_text(response.content),
        )
    try:
        payload = json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EmbeddingProbeError(
            "Embedding response is not valid JSON.",
            422,
            _raw_value_to_text(response.content),
        ) from exc
    try:
        return _embedding_dimensions_from_payload(payload)
    except EmbeddingProbeError as exc:
        if exc.raw_response is None:
            exc.raw_response = _raw_value_to_text(payload)
        raise


async def _probe_native_embedding(
    credential: CredentialBase,
    model_name: str,
    dimensions: int | None,
) -> int:
    """Test a native embedding adapter when its dimensions are known."""
    if dimensions is None:
        raise EmbeddingProbeError(
            "This provider requires a known embedding dimension.",
            422,
        )
    embedding_cls = credential.get_embedding_model_class()
    if embedding_cls is None:
        raise EmbeddingProbeError(
            "This credential does not support embedding models.",
            422,
        )
    model = embedding_cls(
        credential=credential,
        model=model_name,
        dimensions=dimensions,
        parameters=embedding_cls.Parameters(),
        max_retries=0,
    )
    response = await model(["AgentScope embedding model test."])
    if not response.embeddings or not response.embeddings[0]:
        raise EmbeddingProbeError(
            "Embedding response does not contain a usable vector.",
            422,
        )
    return len(response.embeddings[0])


async def test_credential_embedding_model(
    credential: CredentialBase,
    model_name: str,
    dimensions: int | None = None,
) -> CredentialModelTestResult:
    """Send one real embedding request and report the vector dimensions."""
    started_at = perf_counter()

    async def _invoke() -> int:
        credential_type = getattr(credential, "type", None)
        if credential_type in _OPENAI_COMPATIBLE_EMBEDDING_TYPES:
            return await _probe_openai_compatible_embedding(
                credential,
                model_name,
            )
        return await _probe_native_embedding(
            credential,
            model_name,
            dimensions,
        )

    try:
        detected_dimensions = await asyncio.wait_for(
            _invoke(),
            timeout=_MODEL_TEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        error = _classify_error(exc)
        status_code, raw_response = _provider_error_details(
            exc,
            credential,
        )
        return CredentialModelTestResult(
            success=False,
            model=model_name,
            model_type="embedding",
            latency_ms=max(1, round((perf_counter() - started_at) * 1000)),
            error_type=error.type,
            message=error.message,
            status_code=status_code,
            raw_response=raw_response,
        )

    return CredentialModelTestResult(
        success=True,
        model=model_name,
        model_type="embedding",
        dimensions=detected_dimensions,
        latency_ms=max(1, round((perf_counter() - started_at) * 1000)),
        message=(
            "Embedding request completed successfully "
            f"({detected_dimensions} dimensions)."
        ),
    )
