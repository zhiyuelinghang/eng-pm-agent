# -*- coding: utf-8 -*-
"""Credential-scoped chat model catalogue and discovery helpers."""
from __future__ import annotations

import copy
import json
from typing import Literal

import httpx
from pydantic import BaseModel, SecretStr

from ...credential import (
    CredentialBase,
    CredentialModelDefinition,
)
from ...model import ModelCard

_DISCOVERABLE_CREDENTIAL_TYPES = {
    "custom_openai_credential",
    "openai_credential",
    "dashscope_credential",
    "deepseek_credential",
    "moonshot_credential",
    "xai_credential",
}
_MAX_DISCOVERY_RESPONSE_BYTES = 2 * 1024 * 1024


class CredentialModelEntry(ModelCard):
    """A model card plus its credential-scoped catalogue state."""

    source: Literal["builtin", "discovered", "manual"]
    enabled: bool


class ModelDiscoveryError(Exception):
    """Safe, user-facing failure raised while querying ``GET /models``."""


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

    for card in credential.list_models():
        merged[card.name] = (card, "builtin")

    for definition in credential.model_catalog.discovered_models:
        if definition.name not in merged:
            merged[definition.name] = (
                _definition_to_card(credential, definition),
                "discovered",
            )

    for definition in credential.model_catalog.manual_models:
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
