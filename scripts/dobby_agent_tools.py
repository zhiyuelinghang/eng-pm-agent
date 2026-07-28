"""AgentScope tools backed by Dobby's session-bound internal gateway."""

import json
import logging
import os
from typing import Any

import httpx

from agentscope.message import TextBlock, ToolResultState
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from agentscope.tool import ToolBase, ToolChunk


logger = logging.getLogger(__name__)

_DEFAULT_GATEWAY_URL = (
    "http://127.0.0.1:38430/api/internal/agent-tools"
)


READ_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_get_project_overview",
        "operation": "get_project_overview",
        "description": (
            "读取当前平台会话所绑定项目的概览、当前账号身份、进度摘要和"
            "任务/风险/资料数量。项目和账号由平台会话自动确定，不能跨项目。"
            "在回答项目现状、准备执行写操作或不确定当前权限时应优先调用。"
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_list_project_items",
        "operation": "list_project_items",
        "description": (
            "读取当前项目的结构化业务数据。可查询任务、WBS 工序、风险源、"
            "质量指标、项目成员、最新信息、项目变更、通知、工程资料和日报。"
            "仅返回当前会话账号有权访问的项目数据。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "enum": [
                        "tasks",
                        "wbs",
                        "risks",
                        "quality",
                        "members",
                        "information",
                        "changes",
                        "notifications",
                        "documents",
                        "daily_reports",
                    ],
                    "description": "要读取的业务资源类型。",
                },
                "keyword": {
                    "type": ["string", "null"],
                    "description": "可选关键词，用于名称或内容筛选。",
                    "maxLength": 200,
                },
                "status": {
                    "type": ["string", "null"],
                    "description": (
                        "可选状态筛选；查询 documents 时代表资料分类，"
                        "查询 notifications 时可用 read/unread。"
                    ),
                    "maxLength": 64,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                },
            },
            "required": ["resource"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_search_documents",
        "operation": "search_documents",
        "description": (
            "按关键词检索当前项目已经归档的资料名称和已提取正文，返回命中"
            "文件及短摘要。此工具检索 Dobby 平台工程资料；AgentScope 知识库"
            "内容应使用 search_knowledge。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "资料检索关键词。",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                },
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    },
)


WRITE_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_create_task",
        "operation": "create_task",
        "description": (
            "在当前项目创建一条真实任务，并写入审计记录。调用前应先查询成员、"
            "WBS 和风险源，引用的 ID 必须属于当前项目。不要把“建议创建”当作"
            "已经创建；只有工具成功返回后才能向用户确认完成。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 300},
                "task_type": {
                    "type": "string",
                    "enum": [
                        "risk_alert",
                        "material_missing",
                        "daily_confirm",
                        "draft_review",
                        "fill_platform",
                    ],
                    "default": "risk_alert",
                },
                "risk_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "default": "low",
                },
                "assignee_user_id": {"type": ["integer", "null"]},
                "confirmer_user_id": {"type": ["integer", "null"]},
                "due_at": {
                    "type": ["string", "null"],
                    "description": "截止日期或时间，推荐 ISO 格式。",
                },
                "wbs_item_id": {"type": ["integer", "null"]},
                "risk_source_id": {"type": ["integer", "null"]},
                "trigger_reason": {
                    "type": ["string", "null"],
                    "maxLength": 2000,
                },
                "required_materials": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 30,
                    "default": [],
                },
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_update_task",
        "operation": "update_task",
        "description": (
            "更新当前项目的真实任务：状态流转、转交、添加处置说明或更新流程"
            "步骤。必须先读取任务当前状态；工具会执行合法流转和项目成员校验。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "action": {
                    "type": "string",
                    "enum": [
                        "transition",
                        "reassign",
                        "add_note",
                        "update_step",
                    ],
                },
                "status": {
                    "type": ["string", "null"],
                    "description": "状态流转或步骤更新时的新状态。",
                },
                "assignee_user_id": {"type": ["integer", "null"]},
                "step_index": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                    "description": "更新流程步骤时使用，从 0 开始。",
                },
                "note": {"type": ["string", "null"], "maxLength": 2000},
            },
            "required": ["task_id", "action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_dispose_information",
        "operation": "dispose_information",
        "description": (
            "确认、否认或修订当前项目的一条最新信息记录，并写入审计日志。"
            "修订时必须提供 content。执行前先读取原记录和可用依据。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer"},
                "action": {
                    "type": "string",
                    "enum": ["confirm", "deny", "revise"],
                },
                "content": {"type": ["string", "null"], "maxLength": 10000},
            },
            "required": ["record_id", "action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_create_project_change",
        "operation": "create_project_change",
        "description": (
            "在当前项目登记一条待审核的项目变更，并保留来源引用和审计记录。"
            "仅用于已有事实或用户明确要求登记的变更，不得自行编造变更事实。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "default": "工程内容变更",
                },
                "title": {"type": "string", "minLength": 1, "maxLength": 300},
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 10000,
                },
                "source_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 30,
                    "default": [],
                },
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_update_document_category",
        "operation": "update_document_category",
        "description": (
            "修改当前项目一份已归档资料的分类，并写入审计记录。先查询资料 ID，"
            "仅在用户要求或分类依据充分时执行。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "attachment_id": {"type": "integer"},
                "category": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                },
            },
            "required": ["attachment_id", "category"],
            "additionalProperties": False,
        },
    },
)


ADMIN_WRITE_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_create_risk",
        "operation": "create_risk",
        "description": (
            "以当前平台管理员身份在当前项目新增真实风险源，并写入审计记录。"
            "这是管理员级写操作；先核验风险依据、成员 ID 和是否已存在重复风险。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 300},
                "level": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "default": "medium",
                },
                "risk_type": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "default": "综合风险",
                },
                "planned_start": {"type": ["string", "null"]},
                "planned_finish": {"type": ["string", "null"]},
                "responsible_user_id": {"type": ["integer", "null"]},
                "confirmer_user_id": {"type": ["integer", "null"]},
                "material_requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 30,
                    "default": [],
                },
                "control_requirements": {
                    "type": ["string", "null"],
                    "maxLength": 4000,
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_update_wbs_progress",
        "operation": "update_wbs_progress",
        "description": (
            "以当前平台管理员身份更新当前项目 WBS 工序的真实进度和状态，"
            "并写入审计记录。必须先读取工序现状和进度依据。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "wbs_item_id": {"type": "integer"},
                "progress": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
                "status": {
                    "type": ["string", "null"],
                    "enum": [
                        "not_started",
                        "in_progress",
                        "delayed",
                        "completed",
                        "blocked",
                        None,
                    ],
                },
                "note": {"type": ["string", "null"], "maxLength": 1000},
            },
            "required": ["wbs_item_id", "progress"],
            "additionalProperties": False,
        },
    },
)


class DobbyGatewayTool(ToolBase):
    """One semantic Dobby operation bound to a platform chat session."""

    is_concurrency_safe = False
    is_external_tool = False
    is_state_injected = False
    is_mcp = False

    def __init__(
        self,
        definition: dict[str, Any],
        session_id: str,
        base_url: str,
        token: str,
        is_read_only: bool,
    ) -> None:
        super().__init__()
        self.name = str(definition["name"])
        self.description = str(definition["description"])
        self.input_schema = dict(definition["schema"])
        self.is_read_only = is_read_only
        self._operation = str(definition["operation"])
        self._session_id = session_id
        self._base_url = base_url.rstrip("/")
        self._token = token

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        del tool_input, context
        if self.is_read_only:
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message="该 Dobby 工具只读取当前授权项目的数据。",
            )
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message=(
                "该操作将修改当前平台账号有权访问的项目数据，"
                "需要权限模式或权限审核员批准。"
            ),
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._base_url}/execute",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "agentscope_session_id": self._session_id,
                        "operation": self._operation,
                        "arguments": kwargs,
                    },
                )
            if response.is_error:
                try:
                    payload = response.json()
                    detail = payload.get("detail", payload)
                except ValueError:
                    detail = response.text or response.reason_phrase
                return ToolChunk(
                    content=[
                        TextBlock(
                            text=(
                                f"Dobby 操作失败（{response.status_code}）："
                                f"{json.dumps(detail, ensure_ascii=False)}"
                            ),
                        ),
                    ],
                    state=ToolResultState.ERROR,
                    is_last=True,
                    metadata={"operation": self._operation},
                )
            payload = response.json()
            return ToolChunk(
                content=[
                    TextBlock(
                        text=json.dumps(payload, ensure_ascii=False, default=str),
                    ),
                ],
                state=ToolResultState.SUCCESS,
                is_last=True,
                metadata={
                    "operation": self._operation,
                    "platform_data_changed": not self.is_read_only,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("Dobby agent tool gateway request failed: %s", exc)
            return ToolChunk(
                content=[
                    TextBlock(
                        text=f"Dobby 平台工具网关当前不可用：{exc}",
                    ),
                ],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata={"operation": self._operation},
            )


def _gateway_settings() -> tuple[str, str]:
    base_url = os.getenv("DOBBY_AGENT_TOOL_BASE_URL", _DEFAULT_GATEWAY_URL).strip()
    token = (
        os.getenv("DOBBY_AGENT_TOOL_TOKEN", "").strip()
        or os.getenv("AGENTSCOPE_SERVICE_TOKEN", "").strip()
    )
    return base_url, token


async def create_dobby_agent_tools(
    user_id: str,
    agent_id: str,
    session_id: str,
) -> list[ToolBase]:
    """Build tools only for sessions created through the Dobby platform."""
    del user_id
    base_url, token = _gateway_settings()
    if not token:
        logger.warning(
            "Dobby agent tools disabled: no internal service token configured.",
        )
        return []

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{base_url}/context",
                headers={"Authorization": f"Bearer {token}"},
                params={"agentscope_session_id": session_id},
            )
        if response.status_code in {403, 404}:
            return []
        response.raise_for_status()
        context = response.json().get("data") or {}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Unable to resolve Dobby tool context: %s", exc)
        return []

    # Prevent a mapped session from being used to assemble tools for a
    # different AgentScope agent.
    if str(context.get("agent_id") or "") != agent_id:
        return []

    capabilities = context.get("capabilities") or {}
    definitions: list[tuple[dict[str, Any], bool]] = [
        *((definition, True) for definition in READ_TOOL_DEFINITIONS),
    ]
    if capabilities.get("write"):
        definitions.extend(
            (definition, False) for definition in WRITE_TOOL_DEFINITIONS
        )
    if capabilities.get("admin_write"):
        definitions.extend(
            (definition, False) for definition in ADMIN_WRITE_TOOL_DEFINITIONS
        )

    return [
        DobbyGatewayTool(
            definition=definition,
            session_id=session_id,
            base_url=base_url,
            token=token,
            is_read_only=is_read_only,
        )
        for definition, is_read_only in definitions
    ]
