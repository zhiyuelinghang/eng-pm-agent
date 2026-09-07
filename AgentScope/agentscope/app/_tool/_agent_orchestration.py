# -*- coding: utf-8 -*-
"""High-level, permission-aware orchestration tools for the platform main agent.

The tools deliberately keep the candidate catalogue out of the main agent's
prompt.  Candidates are resolved from fresh management-centre configuration
only when ``agent_search`` or ``agent_invoke`` is called.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import Field

from ._agent_invite import AgentInvite, _display_name
from ._team_create import TeamCreate
from ._team_tool_base import _TeamToolBase
from ..access import ResourceKind
from ..storage._utils import _ensure_team_members
from ...message import TextBlock, ToolResultState
from ...tool import ParamsBase, ToolChunk

if TYPE_CHECKING:
    from ..message_bus import MessageBus
    from ..storage import AgentRecord, StorageBase
    from ..workspace_manager import WorkspaceManagerBase
    from .._service._access import ResourceAccessService


_MAX_SEARCH_RESULTS = 5
_MAX_TASK_CHARS = 12_000


def _error(message: str) -> ToolChunk:
    return ToolChunk(
        content=[TextBlock(text=message)],
        state=ToolResultState.ERROR,
    )


class _AgentSearchParams(ParamsBase):
    query: str = Field(
        min_length=1,
        max_length=500,
        description="所需专业能力、业务类别或预期产出的简短描述。",
    )
    limit: int = Field(
        default=3,
        ge=1,
        le=_MAX_SEARCH_RESULTS,
        description="返回候选数量，最多 5 个。",
    )


class _AgentInvokeParams(ParamsBase):
    agent_id: str = Field(
        min_length=1,
        max_length=128,
        description="agent_search 返回的目标智能体 ID。",
    )
    task: str = Field(
        min_length=1,
        max_length=_MAX_TASK_CHARS,
        description=(
            "边界明确的任务说明。只传完成任务所需的事实、引用、约束和"
            "预期产出，不传无关历史。"
        ),
    )


class _AgentCancelParams(ParamsBase):
    reason: str = Field(
        default="用户停止或总控取消当前协同",
        max_length=500,
        description="取消原因，写入本次运行结果。",
    )


class _AgentRetryOrSwitchParams(_AgentInvokeParams):
    reason: str = Field(
        default="专业智能体失败，按总控恢复策略重新执行",
        max_length=500,
        description="重试或切换的原因。",
    )


class _OrchestrationBase(_TeamToolBase):
    """Shared dynamic catalogue and audit helpers."""

    def __init__(
        self,
        storage: "StorageBase",
        message_bus: "MessageBus",
        workspace_manager: "WorkspaceManagerBase",
        resource_access_service: "ResourceAccessService",
        user_id: str,
        session_id: str,
        agent_id: str,
        caller_owner_id: str | None = None,
    ) -> None:
        super().__init__(
            storage,
            message_bus,
            workspace_manager,
            user_id,
            session_id,
            agent_id,
        )
        self._access = resource_access_service
        self._caller_owner_id = caller_owner_id or user_id

    async def _authorised_candidates(self) -> list["AgentRecord"]:
        views = await self._access.list_resource(
            self._caller_owner_id,
            ResourceKind.AGENT,
        )
        return [
            view
            for view in views
            if view.id != self._agent_id
            and view.data.platform_config.enabled
            and view.data.platform_config.allow_global_main_call
            and view.data.invite_config.invitable
            and (view.data.invite_config.invite_description or "").strip()
        ]

    async def _resolve_target(
        self,
        agent_id: str,
    ) -> "AgentRecord | None":
        return next(
            (
                candidate
                for candidate in await self._authorised_candidates()
                if candidate.id == agent_id
            ),
            None,
        )

    async def _trace_context(self) -> dict[str, Any]:
        session = await self._storage.get_session(
            self._user_id,
            self._agent_id,
            self._session_id,
        )
        context = session.config.platform_context if session is not None else None
        return {
            "platform_user_id": getattr(context, "user_id", None),
            "project_id": getattr(context, "project_id", None),
            "conversation_id": getattr(context, "conversation_id", None),
            "root_session_id": getattr(context, "root_session_id", None)
            or self._session_id,
        }


class AgentSearch(_OrchestrationBase):
    """Find a small ranked subset of agents authorised for Dobby."""

    name: str = "agent_search"
    description: str = (
        "按能力描述动态搜索当前管理中心允许 Dobby 调用的智能体。"
        "只在任务需要专业判断、专属工具或复杂多阶段执行时使用；普通问答和"
        "参数明确的通用业务操作不需要搜索。返回少量摘要，不加载候选工具定义。"
    )
    input_schema: dict = _AgentSearchParams.model_json_schema()

    async def __call__(self, query: str, limit: int = 3) -> ToolChunk:
        candidates = await self._authorised_candidates()
        folded_query = query.casefold()
        terms = {
            token.casefold()
            for token in query.replace("/", " ").replace("，", " ").split()
            if token.strip()
        }

        def bigrams(value: str) -> set[str]:
            compact = "".join(char for char in value.casefold() if char.isalnum())
            return {
                compact[index : index + 2]
                for index in range(max(0, len(compact) - 1))
            }

        query_bigrams = bigrams(query)

        def score(record: "AgentRecord") -> tuple[int, int, int, int, str, str]:
            config = record.data.platform_config
            haystack = " ".join(
                (
                    record.data.name,
                    config.category,
                    config.description or "",
                    record.data.invite_config.invite_description or "",
                ),
            ).casefold()
            matches = sum(1 for term in terms if term in haystack)
            labels = (record.data.name, config.category)
            label_hits = sum(
                1
                for label in labels
                for candidate in (
                    label.casefold(),
                    label.casefold().removesuffix("助手").removesuffix("智能体")
                    .removesuffix("管理"),
                )
                if len(candidate) >= 2 and candidate in folded_query
            )
            overlap = len(query_bigrams & bigrams(haystack))
            return (
                -label_hits,
                -matches,
                -overlap,
                config.sort_order,
                record.data.name,
                record.id,
            )

        selected = sorted(candidates, key=score)[: min(limit, _MAX_SEARCH_RESULTS)]
        summaries = [
            {
                "agent_id": record.id,
                "name": record.data.name,
                "category": record.data.platform_config.category,
                "agent_level": record.data.platform_config.agent_level,
                "capability": (
                    record.data.platform_config.description
                    or record.data.invite_config.invite_description
                    or ""
                ).strip()[:1200],
            }
            for record in selected
        ]
        payload = {
            "query": query,
            "candidates": summaries,
            "count": len(summaries),
        }
        return ToolChunk(
            content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
            metadata={
                "orchestration": {
                    "operation": "search",
                    **await self._trace_context(),
                    "candidate_ids": [item["agent_id"] for item in summaries],
                },
            },
        )


class AgentInvoke(_OrchestrationBase):
    """Invoke one freshly authorised existing agent through a team session."""

    name: str = "agent_invoke"
    description: str = (
        "调用 agent_search 选出的一个既有智能体。执行前重新检查启用状态、"
        "可邀请状态和 Dobby 调用许可；自动建立受控协同运行，不创建新智能体。"
    )
    input_schema: dict = _AgentInvokeParams.model_json_schema()

    async def __call__(self, agent_id: str, task: str) -> ToolChunk:
        if len(task) > _MAX_TASK_CHARS:
            return _error("agent_invoke：任务说明过长，请只传必要上下文和引用。")
        target = await self._resolve_target(agent_id.strip())
        if target is None:
            return _error(
                "agent_invoke：目标不在当前 Dobby 授权范围内，或已被停用/取消邀请。",
            )
        session = await self._storage.get_session(
            self._user_id,
            self._agent_id,
            self._session_id,
        )
        if session is None:
            return _error("agent_invoke：当前总控会话不存在。")
        if session.team_id is None:
            created = await TeamCreate(
                self._storage,
                self._message_bus,
                self._workspace_manager,
                self._user_id,
                self._session_id,
                self._agent_id,
            )(
                name=f"Dobby 协同运行 {self._session_id[:8]}",
                description="由 Dobby 动态调度、可观测且可取消的专业智能体运行。",
            )
            if created.state == ToolResultState.ERROR:
                return created
        invite = AgentInvite(
            self._storage,
            self._message_bus,
            self._workspace_manager,
            self._user_id,
            self._session_id,
            self._agent_id,
            [target],
            caller_owner_id=self._caller_owner_id,
        )
        result = await invite(_display_name(target.data.name, target.id), task)
        if result.state == ToolResultState.ERROR:
            return result
        trace = await self._trace_context()
        result.metadata = {
            **(result.metadata or {}),
            "orchestration": {
                "operation": "invoke",
                **trace,
                "worker_agent_id": target.id,
                "worker_agent_name": target.data.name,
                "invoked_at": datetime.now(UTC).isoformat(),
            },
        }
        return result


class AgentRunStatus(_OrchestrationBase):
    """Return durable per-member state for the current Dobby run."""

    name: str = "agent_run_status"
    description: str = (
        "查看当前协同运行中各智能体的 queued/running/reported/completed/failed/"
        "interrupted 状态、修订号和阶段时间。"
    )
    input_schema: dict = ParamsBase.model_json_schema()

    async def __call__(self) -> ToolChunk:
        session = await self._storage.get_session(
            self._user_id,
            self._agent_id,
            self._session_id,
        )
        team = (
            await self._storage.get_team(self._user_id, session.team_id)
            if session is not None and session.team_id is not None
            else None
        )
        members = (
            await _ensure_team_members(self._storage, self._user_id, team)
            if team is not None
            else []
        )
        rows: list[dict[str, Any]] = []
        for member in members:
            record = await self._storage.get_agent(member.owner_id, member.agent_id)
            rows.append(
                {
                    "agent_id": member.agent_id,
                    "name": record.data.name if record is not None else member.agent_id,
                    "status": member.work_status,
                    "work_revision": member.work_revision,
                    "settled_revision": member.settled_revision,
                    "assigned_at": member.assigned_at.isoformat()
                    if member.assigned_at
                    else None,
                    "started_at": member.started_at.isoformat()
                    if member.started_at
                    else None,
                    "settled_at": member.settled_at.isoformat()
                    if member.settled_at
                    else None,
                    "last_error": member.last_error,
                },
            )
        pending = any(
            row["settled_revision"] < row["work_revision"]
            for row in rows
        )
        failed = any(row["status"] == "failed" for row in rows)
        payload = {
            "team_id": team.id if team is not None else None,
            "status": (
                "idle"
                if team is None
                else "running"
                if pending
                else "recovery_required"
                if failed
                else "completed"
            ),
            "members": rows,
            "pending": pending,
        }
        return ToolChunk(
            content=[TextBlock(text=json.dumps(payload, ensure_ascii=False))],
            metadata={"orchestration": {"operation": "status", **await self._trace_context()}},
        )


class AgentCancel(_OrchestrationBase):
    """Cancel and clean up the current Dobby collaboration run."""

    name: str = "agent_cancel"
    description: str = "停止当前协同运行并清理其临时智能体会话；不修改业务数据。"
    input_schema: dict = _AgentCancelParams.model_json_schema()

    async def __call__(self, reason: str = "用户停止或总控取消当前协同") -> ToolChunk:
        session = await self._storage.get_session(
            self._user_id,
            self._agent_id,
            self._session_id,
        )
        if session is None or session.team_id is None:
            return ToolChunk(content=[TextBlock(text="当前没有需要取消的协同运行。")])
        team = await self._storage.get_team(self._user_id, session.team_id)
        if team is None or team.session_id != self._session_id:
            return _error("agent_cancel：当前会话不是协同运行的总控。")
        from .._service import SessionService  # noqa: PLC0415

        team_id = team.id
        await SessionService(
            storage=self._storage,
            message_bus=self._message_bus,
        ).delete_team(self._user_id, team_id)
        return ToolChunk(
            content=[TextBlock(text=f"协同运行 {team_id} 已停止：{reason}")],
            metadata={
                "orchestration": {
                    "operation": "cancel",
                    **await self._trace_context(),
                    "team_id": team_id,
                    "reason": reason,
                },
            },
        )


class AgentRetryOrSwitch(AgentInvoke):
    """Dispose a failed run and invoke the selected recovery agent."""

    name: str = "agent_retry_or_switch"
    description: str = (
        "当专业智能体失败时，由 Dobby 先清理失败运行，再重试原智能体或切换到"
        "另一个当前授权智能体。恢复仍会重新校验权限。"
    )
    input_schema: dict = _AgentRetryOrSwitchParams.model_json_schema()

    async def __call__(
        self,
        agent_id: str,
        task: str,
        reason: str = "专业智能体失败，按总控恢复策略重新执行",
    ) -> ToolChunk:
        if len(task) > _MAX_TASK_CHARS:
            return _error(
                "agent_retry_or_switch：任务说明过长，请只传必要上下文和引用。",
            )
        if await self._resolve_target(agent_id.strip()) is None:
            return _error(
                "agent_retry_or_switch：恢复目标不在当前 Dobby 授权范围内。",
            )
        session = await self._storage.get_session(
            self._user_id,
            self._agent_id,
            self._session_id,
        )
        previous_team_id = session.team_id if session is not None else None
        if previous_team_id is not None:
            team = await self._storage.get_team(self._user_id, previous_team_id)
            if team is not None and team.session_id == self._session_id:
                from .._service import SessionService  # noqa: PLC0415

                await SessionService(
                    storage=self._storage,
                    message_bus=self._message_bus,
                ).delete_team(self._user_id, team.id)
        result = await super().__call__(agent_id=agent_id, task=task)
        if result.state != ToolResultState.ERROR:
            orchestration = dict((result.metadata or {}).get("orchestration") or {})
            orchestration.update(
                {
                    "operation": "retry_or_switch",
                    "previous_team_id": previous_team_id,
                    "reason": reason,
                },
            )
            result.metadata = {**(result.metadata or {}), "orchestration": orchestration}
        return result


__all__ = [
    "AgentCancel",
    "AgentInvoke",
    "AgentRetryOrSwitch",
    "AgentRunStatus",
    "AgentSearch",
]
