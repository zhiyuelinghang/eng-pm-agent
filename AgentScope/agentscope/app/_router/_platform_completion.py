"""One-shot platform text generation through the saved main-agent model."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .._auth import AgentScopePrincipal
from .._service._access import ResourceAccessService
from .._service._model import get_model, managed_chat_model_config
from ..deps import (
    get_current_principal,
    get_current_user_id,
    get_resource_access_service,
    get_storage,
)
from ..storage import StorageBase
from ...message import SystemMsg, UserMsg
from ...model import ChatResponse


platform_completion_router = APIRouter(prefix="/platform", tags=["platform"])


class PlatformTextCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    system_prompt: str = Field(min_length=1, max_length=20_000)
    prompt: str = Field(min_length=1, max_length=120_000)


class PlatformTextCompletionResponse(BaseModel):
    content: str


async def require_platform_service(
    principal: AgentScopePrincipal = Depends(get_current_principal),
) -> None:
    if principal.kind != "service":
        raise HTTPException(status_code=403, detail="此接口仅供工程平台服务调用。")


@platform_completion_router.post("/model-completion", response_model=PlatformTextCompletionResponse)
async def complete_platform_text(
    body: PlatformTextCompletionRequest,
    _: None = Depends(require_platform_service),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> PlatformTextCompletionResponse:
    """Generate text without creating a session, running tools or retaining memory."""
    settings = await storage.get_platform_settings(user_id)
    main_id = settings.data.global_main_agent_id if settings else None
    agent = await storage.get_agent(user_id, main_id) if main_id else None
    policy = agent.data.model_policy if agent else None
    if policy is None or policy.mode != "fixed" or policy.chat_model_config is None:
        raise HTTPException(status_code=409, detail="请先为平台总控配置可用的固定模型。")

    config = managed_chat_model_config(policy.chat_model_config)
    model = await get_model(user_id, config, access)
    model.stream = False
    try:
        response = await model([
            SystemMsg(name="platform-instruction", content=body.system_prompt),
            UserMsg(name="platform-request", content=body.prompt),
        ], tools=None)
        if not isinstance(response, ChatResponse):
            last = None
            async for chunk in response:
                last = chunk
            response = last
        content = "".join(
            block.text for block in (response.content if response else [])
            if getattr(block, "type", None) == "text"
        ).strip()
    except Exception as error:
        raise HTTPException(status_code=502, detail="平台共享模型暂时无法生成回复，请稍后重试。") from error
    if not content:
        raise HTTPException(status_code=502, detail="平台共享模型未返回文本回复。")
    return PlatformTextCompletionResponse(content=content)
