"""Assemble platform tools from external, editable capability catalogues.

Database tools are created exclusively from the platform's declarative
database-interaction catalogue.  This module intentionally contains no fixed
business-tool definitions and no operation dispatch table.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from agentscope.app._types import AgentToolDescriptor
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

class DobbyDatabaseInteractionTool(ToolBase):
    """One structured operation loaded from the editable database catalogue."""

    is_concurrency_safe = False
    is_external_tool = False
    is_state_injected = False
    is_mcp = False
    assignment_source = "database"

    def __init__(
        self,
        definition: dict[str, Any],
        session_id: str,
        actor_agent_id: str,
        base_url: str,
        token: str,
        requires_confirmation: bool,
        changes_business_data: bool,
        team_report_on_success: bool = False,
        team_report_message: str | None = None,
        bounded_initialization_section_reads: bool = False,
    ) -> None:
        super().__init__()
        self.name = str(definition["key"])
        self.description = str(definition.get("description") or "")
        self.input_schema = dict(definition.get("input_schema") or {})
        self.is_read_only = not changes_business_data
        self._session_id = session_id
        self._actor_agent_id = actor_agent_id
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._requires_confirmation = requires_confirmation
        self._changes_business_data = changes_business_data
        self._team_report_on_success = team_report_on_success
        self._team_report_message = team_report_message
        self._bounded_initialization_section_reads = (
            bounded_initialization_section_reads
        )
        self._display_name = str(
            definition.get("display_name") or self.name,
        )

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        del tool_input, context
        if not self._requires_confirmation:
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message="该数据库交互只读取当前项目白名单内的数据。",
            )
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message=(
                "该数据库交互将修改当前项目白名单内的数据，"
                "需要权限模式或权限审核员批准。"
            ),
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        if (
            self._bounded_initialization_section_reads
            and self.name == "dobby_list_project_initialization_sections"
        ):
            read_error = _initialization_section_read_error(kwargs)
            if read_error is not None:
                return ToolChunk(
                    content=[TextBlock(text=read_error)],
                    state=ToolResultState.ERROR,
                    is_last=True,
                    metadata={"operation": self.name},
                )
        if (
            self._bounded_initialization_section_reads
            and self.name
            == "dobby_list_project_initialization_attachment_chunks"
        ):
            read_error = _initialization_attachment_chunk_read_error(kwargs)
            if read_error is not None:
                return ToolChunk(
                    content=[TextBlock(text=read_error)],
                    state=ToolResultState.ERROR,
                    is_last=True,
                    metadata={"operation": self.name},
                )
        endpoint = (
            f"{self._base_url.rsplit('/agent-tools', 1)[0]}"
            "/database-interactions/execute"
        )
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "agentscope_session_id": self._session_id,
                        "actor_agent_id": self._actor_agent_id,
                        "interaction_key": self.name,
                        "access_mode": "agent",
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
                                f"数据库交互失败（{response.status_code}）："
                                f"{json.dumps(detail, ensure_ascii=False)}"
                            ),
                        ),
                    ],
                    state=ToolResultState.ERROR,
                    is_last=True,
                    metadata={"operation": self.name},
                )
            payload = response.json()
            team_report_message = self._team_report_message or (
                f"已完成「{self._display_name}」，数据已写入初始化草稿。"
            )
            return ToolChunk(
                content=[
                    TextBlock(
                        text=json.dumps(payload, ensure_ascii=False, default=str),
                    ),
                ],
                state=ToolResultState.SUCCESS,
                is_last=True,
                metadata={
                    "operation": self.name,
                    "platform_data_changed": self._changes_business_data,
                    "team_report_on_success": self._team_report_on_success,
                    "team_report_message": team_report_message,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("Database interaction request failed: %s", exc)
            return ToolChunk(
                content=[TextBlock(text=f"数据库交互服务当前不可用：{exc}")],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata={"operation": self.name},
            )


def _gateway_settings() -> tuple[str, str]:
    base_url = os.getenv(
        "DOBBY_AGENT_TOOL_BASE_URL",
        _DEFAULT_GATEWAY_URL,
    ).strip()
    token = (
        os.getenv("DOBBY_AGENT_TOOL_TOKEN", "").strip()
        or os.getenv("AGENTSCOPE_SERVICE_TOKEN", "").strip()
    )
    return base_url, token


def create_dobby_agent_tool_catalog() -> list[AgentToolDescriptor]:
    """Return no fixed business catalogue; all such capabilities are external."""
    return []


def _is_team_completion_interaction(
    definition: dict[str, Any],
    initialization_role: str | None,
) -> bool:
    """Return whether this durable write completes a team assignment."""
    policy = definition.get("policy") or {}
    table_name = str(policy.get("table_name") or "")
    table_operation = str(definition.get("table_operation") or "")
    return (
        initialization_role
        in {
            "project",
            "personnel",
            "wbs",
            "risks",
            "quality_requirements",
        }
        and table_name == "project_initialization_draft_sections"
        and table_operation in {"create", "update"}
    ) or (
        initialization_role == "validator"
        and table_name == "project_initialization_drafts"
        and table_operation == "update"
    )


def _team_completion_message(
    initialization_role: str | None,
) -> str | None:
    """Return the continuation instruction delivered to the team leader."""
    if initialization_role == "validator":
        return (
            "核验状态与问题已写入初始化草稿；请立即重新读取草稿状态，"
            "完成核验与最终汇总任务并提示用户核对，不要等待其他汇报。"
        )
    if initialization_role in {
        "project",
        "personnel",
        "wbs",
        "risks",
        "quality_requirements",
    }:
        return (
            "负责的草稿分区已经持久化完成；请读取分区状态继续编排，"
            "不要等待额外汇报。"
        )
    return None


def _initialization_section_read_error(
    arguments: dict[str, Any],
) -> str | None:
    """Reject unbounded section reads before they can exhaust model context."""
    fields = arguments.get("fields")
    if not isinstance(fields, list) or not fields:
        return (
            "读取初始化草稿分区必须显式指定 fields。请先读取不含 payload 的"
            "轻量清单；需要 payload 时按 section 分别读取。"
        )
    if "payload" not in fields:
        return None
    filters = arguments.get("filters")
    allowed_sections = {
        "project",
        "personnel",
        "wbs",
        "risks",
        "quality_requirements",
    }
    if (
        not isinstance(filters, dict)
        or filters.get("section") not in allowed_sections
        or arguments.get("limit") != 1
    ):
        return (
            "包含 payload 的初始化分区读取必须使用一个明确的 section 筛选，"
            "并设置 limit=1；禁止一次读取多个大型分区。"
        )
    section = filters["section"]
    if section != "project":
        json_offset = arguments.get("json_offset")
        json_limit = arguments.get("json_limit")
        if (
            arguments.get("json_field") != "payload"
            or not isinstance(json_offset, int)
            or isinstance(json_offset, bool)
            or json_offset < 0
            or not isinstance(json_limit, int)
            or isinstance(json_limit, bool)
            or not 1 <= json_limit <= 20
        ):
            return (
                "数组型初始化分区 payload 必须分页读取：设置 "
                "json_field=payload、json_offset>=0、1<=json_limit<=20，"
                "并根据返回的 _json_page.has_more/next_offset 继续读取。"
            )
    return None


def _initialization_attachment_chunk_read_error(
    arguments: dict[str, Any],
) -> str | None:
    """Ensure parsed attachment text is fetched by bounded manifest IDs."""
    fields = arguments.get("fields")
    if not isinstance(fields, list) or not fields:
        return (
            "读取初始化附件解析分块必须显式指定 fields；请使用 manifest 中的"
            " chunk_id，禁止无边界读取。"
        )
    if "content" not in fields:
        return None
    record_id = arguments.get("record_id")
    record_ids = arguments.get("record_ids")
    if record_ids is not None:
        return (
            "包含 content 的解析正文不能批量读取多个分块；请逐个使用 "
            "record_id，并对每个分块进行文本分页。"
        )
    if (
        not isinstance(record_id, int)
        or isinstance(record_id, bool)
        or record_id <= 0
        or arguments.get("limit") != 1
    ):
        return (
            "读取解析正文必须使用 record_id=manifest 中的 chunk_id，并设置 "
            "limit=1。"
        )
    text_offset = arguments.get("text_offset")
    text_limit = arguments.get("text_limit")
    if (
        arguments.get("text_field") != "content"
        or not isinstance(text_offset, int)
        or isinstance(text_offset, bool)
        or text_offset < 0
        or not isinstance(text_limit, int)
        or isinstance(text_limit, bool)
        or not 1 <= text_limit <= 6000
    ):
        return (
            "解析正文必须分页读取：设置 text_field=content、text_offset>=0、"
            "1<=text_limit<=6000，并根据返回的 "
            "_text_page.has_more/next_offset 继续读取到末页。"
        )
    return None


async def create_dobby_agent_tools(
    user_id: str,
    agent_id: str,
    session_id: str,
    *,
    platform_session_id: str | None = None,
    platform_agent_id: str | None = None,
    read_only: bool = False,
    initialization_role: str | None = None,
    database_interactions: list[dict[str, Any]] | None = None,
) -> list[ToolBase]:
    """Build only the capabilities supplied by external catalogues."""
    del user_id
    context_session_id = platform_session_id or session_id
    context_agent_id = platform_agent_id or agent_id
    base_url, token = _gateway_settings()
    if not token:
        logger.warning(
            "Platform capabilities disabled: no internal service token configured.",
        )
        return []

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{base_url}/context",
                headers={"Authorization": f"Bearer {token}"},
                params={"agentscope_session_id": context_session_id},
            )
        if response.status_code in {403, 404}:
            return []
        response.raise_for_status()
        context = response.json().get("data") or {}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Unable to resolve platform capability context: %s", exc)
        return []

    if str(context.get("agent_id") or "") != context_agent_id:
        return []

    tools: list[ToolBase] = []
    for definition in database_interactions or []:
        changes_business_data = not bool(definition.get("read_only", True))
        if read_only and changes_business_data:
            continue
        # A specialist's successful draft write is the durable completion
        # boundary for its assignment.  Report it to the team leader at that
        # point instead of requiring another potentially very large model
        # round-trip merely to call TeamSay.  The validator uses the same
        # signal when it finalizes the draft status.
        team_report_on_success = _is_team_completion_interaction(
            definition,
            initialization_role,
        )
        tools.append(
            DobbyDatabaseInteractionTool(
                definition=definition,
                session_id=context_session_id,
                actor_agent_id=agent_id,
                base_url=base_url,
                token=token,
                requires_confirmation=bool(
                    definition.get("requires_confirmation"),
                ),
                changes_business_data=changes_business_data,
                team_report_on_success=team_report_on_success,
                team_report_message=_team_completion_message(
                    initialization_role,
                ),
                bounded_initialization_section_reads=(
                    initialization_role is not None
                ),
            ),
        )

    return tools
