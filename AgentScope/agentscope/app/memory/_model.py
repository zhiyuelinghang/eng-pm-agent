"""Resolve the explicit conversation compression model for this invocation."""
from ..storage._model._session import ChatModelConfig
from ...credential import CredentialFactory


async def get_compression_model(user_id, settings, access):
    """None means use the current conversation model; no environment fallback."""
    from .._service import build_credential_model_catalog, get_model

    selected = settings.compression_model_config
    if selected is None:
        return None
    config = ChatModelConfig.model_validate(selected)
    record = await access.resolve_credential(user_id, config.credential_id)
    credential = CredentialFactory.from_dict(record.data)
    if config.type != credential.type:
        raise ValueError('对话摘要模型与凭证类型不匹配。')
    if not any(item.name == config.model and item.enabled
               for item in build_credential_model_catalog(credential)):
        raise ValueError('对话摘要模型不存在或已被停用。')
    return await get_model(user_id, config, access)
