# -*- coding: utf-8 -*-
"""Model service: builds a ChatModelBase from stored credential + config."""
from ._access import ResourceAccessService
from ..storage import AgentData, ChatModelConfig, SessionConfig
from ...credential import CredentialFactory
from ...model import CUSTOM_REQUEST_BODY_KEY, ChatModelBase


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
        return policy.chat_model_config
    return session.chat_model_config


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
            shared to them.
    """
    credential_record = await access.resolve_credential(
        user_id,
        config.credential_id,
    )

    credential = CredentialFactory.from_dict(credential_record.data)
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
    )
    model.set_request_body_overrides(request_body_overrides)
    return model
