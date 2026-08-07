"""Runtime tools backed by the platform database-interaction catalogue.

The adapter is intentionally domain-neutral.  Interaction-specific paging,
completion signalling and other runtime constraints arrive as declarative
``runtime_policy`` data from the engineering platform rather than being
hard-coded against an agent role or interaction name here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ...message import TextBlock, ToolResultState
from ...permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from ...tool import ToolBase, ToolChunk
from ._manager import (
    DatabaseInteractionGatewayError,
    DatabaseInteractionManager,
)


logger = logging.getLogger(__name__)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _single_record_text_page_error(
    policy: dict[str, Any],
    arguments: dict[str, Any],
) -> str | None:
    fields = arguments.get("fields")
    if not isinstance(fields, list) or not fields:
        return "读取大文本记录必须显式指定 fields，禁止无边界读取。"

    content_field = str(policy.get("content_field") or "content")
    if content_field not in fields:
        return None
    if arguments.get("record_ids") is not None:
        return "包含大文本的记录不能批量读取，请逐个使用 record_id。"
    if not _positive_int(arguments.get("record_id")) or arguments.get("limit") != 1:
        return "读取大文本必须指定单个有效 record_id，并设置 limit=1。"

    offset = arguments.get("text_offset")
    page_size = arguments.get("text_limit")
    max_page_size = int(policy.get("max_page_size") or 6000)
    if (
        arguments.get("text_field") != content_field
        or not _non_negative_int(offset)
        or not _positive_int(page_size)
        or page_size > max_page_size
    ):
        return (
            f"字段 {content_field} 必须分页读取：设置 "
            f"text_field={content_field}、text_offset>=0、"
            f"1<=text_limit<={max_page_size}，并按分页结果继续读取。"
        )
    return None


def _single_partition_json_page_error(
    policy: dict[str, Any],
    arguments: dict[str, Any],
) -> str | None:
    fields = arguments.get("fields")
    if not isinstance(fields, list) or not fields:
        return "读取分区记录必须显式指定 fields，先读取轻量清单。"

    payload_field = str(policy.get("payload_field") or "payload")
    if payload_field not in fields:
        return None

    partition_field = str(policy.get("partition_field") or "section")
    partitions = policy.get("partitions")
    filters = arguments.get("filters")
    partition = filters.get(partition_field) if isinstance(filters, dict) else None
    if (
        not isinstance(partitions, dict)
        or partition not in partitions
        or arguments.get("limit") != 1
    ):
        return (
            f"包含 {payload_field} 的读取必须按一个明确的 "
            f"{partition_field} 分区筛选，并设置 limit=1。"
        )

    partition_policy = partitions.get(partition) or {}
    if not bool(partition_policy.get("paged")):
        return None

    offset = arguments.get("json_offset")
    page_size = arguments.get("json_limit")
    max_page_size = int(policy.get("max_page_size") or 20)
    if (
        arguments.get("json_field") != payload_field
        or not _non_negative_int(offset)
        or not _positive_int(page_size)
        or page_size > max_page_size
    ):
        return (
            f"数组字段 {payload_field} 必须分页读取：设置 "
            f"json_field={payload_field}、json_offset>=0、"
            f"1<=json_limit<={max_page_size}，并按分页结果继续读取。"
        )
    return None


def runtime_argument_error(
    runtime_policy: dict[str, Any] | None,
    arguments: dict[str, Any],
) -> str | None:
    """Validate arguments using a reusable declarative runtime guard."""
    guard = dict((runtime_policy or {}).get("argument_guard") or {})
    guard_type = guard.get("type")
    if not guard_type:
        return None
    if guard_type == "single_record_text_page":
        return _single_record_text_page_error(guard, arguments)
    if guard_type == "single_partition_json_page":
        return _single_partition_json_page_error(guard, arguments)
    return "数据库交互包含平台无法识别的运行约束，请联系管理员。"


class DatabaseInteractionTool(ToolBase):
    """One assigned database operation resolved from platform state."""

    is_concurrency_safe = False
    is_external_tool = False
    is_state_injected = False
    is_mcp = False
    assignment_source = "database"

    def __init__(
        self,
        *,
        definition: dict[str, Any],
        manager: DatabaseInteractionManager,
        session_id: str,
        actor_agent_id: str,
        platform_agent_id: str,
    ) -> None:
        super().__init__()
        self.name = str(definition["key"])
        self.description = str(definition.get("description") or "")
        self.input_schema = dict(definition.get("input_schema") or {})
        self.is_read_only = bool(definition.get("read_only", True))
        self._manager = manager
        self._session_id = session_id
        self._actor_agent_id = actor_agent_id
        self._platform_agent_id = platform_agent_id
        self._requires_confirmation = bool(
            definition.get("requires_confirmation"),
        )
        self._runtime_policy = dict(definition.get("runtime_policy") or {})

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        del tool_input, context
        if not self._requires_confirmation:
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message="该数据库交互已通过平台白名单和会话授权。",
            )
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message="该数据库交互会修改业务数据，需要权限审核。",
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        validation_error = runtime_argument_error(self._runtime_policy, kwargs)
        if validation_error is not None:
            return ToolChunk(
                content=[TextBlock(text=validation_error)],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata={"operation": self.name},
            )
        try:
            payload = await self._manager.execute_interaction(
                session_id=self._session_id,
                actor_agent_id=self._actor_agent_id,
                platform_agent_id=self._platform_agent_id,
                interaction_key=self.name,
                arguments=kwargs,
            )
        except DatabaseInteractionGatewayError as exc:
            logger.warning("Database interaction request failed: %s", exc)
            return ToolChunk(
                content=[
                    TextBlock(
                        text=f"数据库交互失败（{exc.status_code}）：{exc.detail}",
                    ),
                ],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata={"operation": self.name},
            )

        completion = dict(self._runtime_policy.get("team_completion") or {})
        report_message = str(completion.get("message") or "").strip()
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
                "platform_data_changed": not self.is_read_only,
                "team_report_on_success": bool(completion.get("enabled")),
                "team_report_message": report_message or None,
            },
        )


async def create_database_interaction_tools(
    *,
    manager: DatabaseInteractionManager,
    agent_id: str,
    session_id: str,
    platform_agent_id: str | None = None,
    platform_session_id: str | None = None,
    legacy_allowed_names: list[str] | None = None,
    read_only: bool = False,
) -> list[ToolBase]:
    """Resolve and instantiate the interactions assigned to one agent."""
    context_session_id = platform_session_id or session_id
    context_agent_id = platform_agent_id or agent_id
    context = await manager.resolve_context(context_session_id)
    if context is None or str(context.get("agent_id") or "") != context_agent_id:
        return []

    definitions = await manager.list_runtime(
        agent_id=agent_id,
        session_id=context_session_id,
        legacy_allowed_names=legacy_allowed_names,
    )
    tools: list[ToolBase] = []
    for definition in definitions:
        if read_only and not bool(definition.get("read_only", True)):
            continue
        tools.append(
            DatabaseInteractionTool(
                definition=definition,
                manager=manager,
                session_id=context_session_id,
                actor_agent_id=agent_id,
                platform_agent_id=context_agent_id,
            ),
        )
    return tools
