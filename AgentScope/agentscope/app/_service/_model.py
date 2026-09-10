# -*- coding: utf-8 -*-
"""Model service: builds a ChatModelBase from stored credential + config."""
from fastapi import HTTPException, status

from ._access import ResourceAccessService
from ._credential_models import (
    require_enabled_chat_model,
    resolve_model_output_limit,
)
from ..storage import AgentData, ChatModelConfig, SessionConfig
from ...credential import CredentialBase, CredentialFactory
from ...model import CUSTOM_REQUEST_BODY_KEY, ChatModelBase, ModelCard


def _merge_request_bodies(
    base: dict,
    override: dict,
) -> dict:
    """Recursively merge provider request bodies with override precedence."""
    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _merge_request_bodies(current, value)
        else:
            result[key] = value
    return result


def resolve_effective_chat_model_config(
    agent: AgentData,
    session: SessionConfig,
) -> ChatModelConfig | None:
    """Resolve the primary model with agent policy taking precedence."""
    policy = agent.model_policy
    if policy.mode == "fixed":
        config = policy.chat_model_config
    else:
        config = session.chat_model_config
    return managed_chat_model_config(config)


def managed_chat_model_config(config: ChatModelConfig | None) -> ChatModelConfig | None:
    """Model selection is per agent; provider parameters belong to the catalogue.

    Do not rewrite stored agent/session records or silently copy one agent's
    legacy overrides into the shared model settings.
    """
    return config.model_copy(update={"parameters": {}}) if config else None


async def resolve_chat_model_binding(
    user_id: str,
    config: ChatModelConfig,
    access: ResourceAccessService,
) -> tuple[CredentialBase, ModelCard]:
    """Use the same current catalogue rules for configuration and execution."""
    record = await access.resolve_credential(user_id, config.credential_id)
    credential = CredentialFactory.from_dict(record.data)
    if config.type != credential.type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="聊天模型类型与所选凭证不匹配，请重新选择模型。",
        )
    try:
        definition = require_enabled_chat_model(credential, config.model)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return credential, definition


async def get_model(
    user_id: str,
    config: ChatModelConfig,
    access: ResourceAccessService,
) -> ChatModelBase:
    """Build a chat model instance from a stored credential and config.

    Credentials are resolved through :class:`ResourceAccessService` so
    both the viewer's own credentials and any shared to them via the
    resource access policy work. Runtime paths use
    :meth:`ResourceAccessService.resolve_credential` which returns the
    raw record (not the masked view) — required for making real
    provider calls.

    Args:
        user_id (`str`):
            The viewer's user id. May differ from the credential owner
            when the credential is shared.
        config (`ChatModelConfig`):
            The chat model configuration.
        access (`ResourceAccessService`):
            Injected resource access service.

    Returns:
        `ChatModelBase`:
            The model instance.

    Raises:
        `HTTPException`:
            404 when the credential is neither owned by ``user_id`` nor
            shared to them; 422 when its type differs or the selected model
            is absent from the current catalogue or disabled.
    """
    credential, model_definition = await resolve_chat_model_binding(
        user_id,
        config,
        access,
    )

    model_cls = credential.get_chat_model_class()
    default_parameters = dict(
        credential.model_catalog.model_default_parameters.get(
            config.model,
            {},
        ),
    )
    config_parameters = dict(config.parameters)
    default_request_body = default_parameters.pop(
        CUSTOM_REQUEST_BODY_KEY,
        {},
    )
    config_request_body = config_parameters.pop(
        CUSTOM_REQUEST_BODY_KEY,
        {},
    )
    effective_parameters = {
        **default_parameters,
        **config_parameters,
    }
    request_body_overrides = _merge_request_bodies(
        default_request_body,
        config_request_body,
    )
    parameters = (
        model_cls.Parameters(**effective_parameters)
        if effective_parameters
        else None
    )
    model = model_cls(
        credential=credential,
        model=config.model,
        parameters=parameters,
        context_size=model_definition.context_size,
    )
    model.input_types = list(model_definition.input_types)
    if hasattr(model, "formatter") and hasattr(model.formatter, "input_types"):
        model.formatter.input_types = list(model_definition.input_types)
    model.set_request_body_overrides(request_body_overrides)
    output_limit = resolve_model_output_limit(
        model_definition,
        getattr(model.parameters, "max_tokens", None),
    )
    if output_limit is not None:
        model._managed_output_limit = output_limit
        model._managed_thinking_budget = getattr(model.parameters, "thinking_budget", None)
        # Supplies mandatory fields (e.g. Anthropic) even before middleware.
        if hasattr(model.parameters, "max_tokens"):
            model.parameters.max_tokens = output_limit
    return model
