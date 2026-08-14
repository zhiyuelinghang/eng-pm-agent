# -*- coding: utf-8 -*-
"""Platform model binding for Dobby's memory-only LLM work."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, TYPE_CHECKING

from pydantic import SecretStr

from ..storage import ChatModelConfig
from ...credential import CredentialBase, CredentialFactory

if TYPE_CHECKING:
    from .._service import ResourceAccessService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryModelRuntimeConfig:
    """Provider-neutral runtime data derived from one platform credential."""

    mem0_llm: dict[str, Any]
    graph_llm: dict[str, Any]
    signature: str
    context_size: int | None


def _secret_value(value: Any) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value or "")


def _with_v1(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    return normalized if normalized.endswith("/v1") else f"{normalized}/v1"


def _sampling_parameters(config: ChatModelConfig) -> tuple[float, int]:
    parameters = config.parameters or {}
    try:
        temperature = float(parameters.get("temperature", 0.1))
    except (TypeError, ValueError):
        temperature = 0.1
    raw_max_tokens = parameters.get(
        "max_tokens",
        parameters.get("max_completion_tokens", 2000),
    )
    try:
        max_tokens = max(256, int(raw_max_tokens))
    except (TypeError, ValueError):
        max_tokens = 2000
    return temperature, max_tokens


def build_memory_model_runtime_config(
    config: ChatModelConfig,
    credential: CredentialBase,
    *,
    context_size: int | None = None,
) -> MemoryModelRuntimeConfig:
    """Translate a platform model selection for Mem0 and graph components."""

    credential_type = str(getattr(credential, "type", ""))
    temperature, max_tokens = _sampling_parameters(config)
    common = {
        "model": config.model,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    api_key = _secret_value(getattr(credential, "api_key", ""))
    graph_provider = "openai"
    graph_base_url: str | None = None

    if credential_type == "deepseek_credential":
        graph_base_url = str(getattr(credential, "base_url", "")).rstrip("/")
        mem0_llm = {
            "provider": "deepseek",
            "config": {
                **common,
                "api_key": api_key,
                "deepseek_base_url": graph_base_url,
            },
        }
    elif credential_type in {
        "custom_openai_credential",
        "openai_credential",
        "dashscope_credential",
        "moonshot_credential",
    }:
        graph_base_url = (
            str(getattr(credential, "base_url", "") or "").rstrip("/")
            or None
        )
        mem0_llm = {
            "provider": "openai",
            "config": {
                **common,
                "api_key": api_key,
                "openai_base_url": graph_base_url,
            },
        }
    elif credential_type == "xai_credential":
        host = str(getattr(credential, "api_host", "api.x.ai")).strip().rstrip("/")
        graph_base_url = _with_v1(
            host if host.startswith(("http://", "https://")) else f"https://{host}",
        )
        mem0_llm = {
            "provider": "xai",
            "config": {
                **common,
                "api_key": api_key,
                "xai_base_url": graph_base_url,
            },
        }
    elif credential_type == "anthropic_credential":
        graph_provider = "anthropic"
        graph_base_url = (
            str(getattr(credential, "base_url", "") or "").rstrip("/")
            or None
        )
        mem0_llm = {
            "provider": "anthropic",
            "config": {
                **common,
                "api_key": api_key,
                "anthropic_base_url": graph_base_url,
            },
        }
    elif credential_type == "gemini_credential":
        graph_provider = "gemini"
        mem0_llm = {
            "provider": "gemini",
            "config": {**common, "api_key": api_key},
        }
    elif credential_type == "ollama_credential":
        host = str(
            getattr(credential, "host", None) or "http://127.0.0.1:11434",
        )
        graph_base_url = _with_v1(host)
        api_key = "ollama"
        mem0_llm = {
            "provider": "openai",
            "config": {
                **common,
                "api_key": api_key,
                "openai_base_url": graph_base_url,
            },
        }
    else:
        raise ValueError(f"不支持的记忆处理模型凭证类型：{credential_type or 'unknown'}")

    graph_llm = {
        "provider": graph_provider,
        "model": config.model,
        "api_key": api_key,
        "base_url": graph_base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    signature_payload = {
        "credential_id": config.credential_id,
        "credential_type": credential_type,
        "model": config.model,
        "parameters": config.parameters,
        "base_url": graph_base_url,
        "secret_hash": sha256(api_key.encode("utf-8")).hexdigest(),
    }
    signature = sha256(
        json.dumps(
            signature_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8"),
    ).hexdigest()
    return MemoryModelRuntimeConfig(
        mem0_llm=mem0_llm,
        graph_llm=graph_llm,
        signature=signature,
        context_size=context_size,
    )


async def configure_platform_memory_model(
    user_id: str,
    settings: Any,
    access: "ResourceAccessService",
) -> bool:
    """Apply the saved memory model to every copied Dobby model path."""

    from .._service import (
        build_credential_model_catalog,
        get_model,
    )
    from utils.langgraph_utils import configure_runtime_memory_model

    raw_config = (
        settings.memory_model_config
        if hasattr(settings, "memory_model_config")
        else (settings or {}).get("memory_model_config")
    )
    if raw_config is None:
        changed = configure_runtime_memory_model(signature="environment")
    else:
        config = ChatModelConfig.model_validate(raw_config)
        record = await access.resolve_credential(user_id, config.credential_id)
        credential = CredentialFactory.from_dict(record.data)
        if config.type != getattr(credential, "type", None):
            raise ValueError("配置的记忆处理模型与凭证类型不匹配。")
        candidate = next(
            (
                model
                for model in build_credential_model_catalog(credential)
                if model.name == config.model and model.enabled
            ),
            None,
        )
        if candidate is None:
            raise ValueError("配置的记忆处理模型不存在或已被停用。")

        runtime = build_memory_model_runtime_config(
            config,
            credential,
            context_size=candidate.context_size,
        )

        async def model_factory():
            return await get_model(user_id, config, access)

        changed = configure_runtime_memory_model(
            model_factory=model_factory,
            mem0_llm_config=runtime.mem0_llm,
            graph_llm_config=runtime.graph_llm,
            context_size=runtime.context_size,
            signature=runtime.signature,
        )

    if changed:
        try:
            from utils.graph_rag_engine import reset_graph_rag_engines

            await reset_graph_rag_engines()
        except Exception as exc:
            logger.warning(
                "Unable to reset GraphRAG engines after memory model change: %s",
                exc,
            )
    return changed
