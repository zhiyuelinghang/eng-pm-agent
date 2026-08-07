# -*- coding: utf-8 -*-
"""Project safe team-member progress onto the leader session.

The worker's own event stream contains model and tool execution events that a
leader-only client cannot see.  This projector mirrors a deliberately small,
safe subset of those events into a durable leader-side feed.  It never copies
thinking or generated text; the payload only contains lifecycle state and
tool identifiers suitable for an operational progress card.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ....event import (
    ModelCallStartEvent,
    ReplyEndEvent,
    ReplyStartEvent,
    RequireExternalExecutionEvent,
    RequireUserConfirmEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
)
from ....types import ReplyFinishedReason
from ...storage._utils import _ensure_team_members

if TYPE_CHECKING:
    from ....event import AgentEvent
    from ...storage import AgentRecord, SessionRecord, StorageBase, TeamMember
    from .._session_projection import SessionProjection


class CollaborationProgressProjector:
    """Mirror one worker's operational progress onto its team leader."""

    KIND = "collaboration_progress"
    EVT_UPDATE = "collaboration_member_updated"
    _MAX_ACTIVITIES = 12

    def __init__(self, storage: "StorageBase") -> None:
        self._storage = storage

    @staticmethod
    def entry_id(worker_session_id: str) -> str:
        return worker_session_id

    @staticmethod
    def _iso(value: Any) -> str | None:
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    @staticmethod
    def _terminal_status(event: ReplyEndEvent) -> str:
        reason = event.finished_reason
        if reason == ReplyFinishedReason.INTERRUPTED:
            return "interrupted"
        if reason in {
            ReplyFinishedReason.ERROR,
            ReplyFinishedReason.EXCEED_MAX_ITERS,
        }:
            return "failed"
        return "completed"

    @classmethod
    def _activity_for_event(
        cls,
        event: "AgentEvent",
        existing: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        if isinstance(event, ReplyStartEvent):
            return {
                "kind": "started",
                "label": "开始处理分配任务",
                "state": "running",
                "reply_id": event.reply_id,
                "created_at": now,
            }
        if isinstance(event, ModelCallStartEvent):
            return {
                "kind": "analysis",
                "label": "正在分析任务",
                "state": "running",
                "reply_id": event.reply_id,
                "created_at": now,
            }
        if isinstance(event, ToolCallStartEvent):
            return {
                "kind": "tool",
                "label": "正在执行工具",
                "state": "running",
                "reply_id": event.reply_id,
                "tool_call_id": event.tool_call_id,
                "tool_name": event.tool_call_name,
                "created_at": now,
            }
        if isinstance(event, ToolResultEndEvent):
            tool_name = None
            for activity in reversed((existing or {}).get("activities") or []):
                if activity.get("tool_call_id") == event.tool_call_id:
                    tool_name = activity.get("tool_name")
                    break
            succeeded = str(event.state) == "success"
            return {
                "kind": "tool",
                "label": "工具执行完成" if succeeded else "工具执行失败",
                "state": "success" if succeeded else "error",
                "reply_id": event.reply_id,
                "tool_call_id": event.tool_call_id,
                "tool_name": tool_name,
                "created_at": now,
            }
        if isinstance(event, RequireUserConfirmEvent):
            return {
                "kind": "waiting",
                "label": "等待人工确认",
                "state": "waiting",
                "reply_id": event.reply_id,
                "created_at": now,
            }
        if isinstance(event, RequireExternalExecutionEvent):
            return {
                "kind": "waiting",
                "label": "等待外部工具返回",
                "state": "waiting",
                "reply_id": event.reply_id,
                "created_at": now,
            }
        if isinstance(event, ReplyEndEvent):
            status = cls._terminal_status(event)
            labels = {
                "completed": "分配任务已完成",
                "failed": "分配任务执行失败",
                "interrupted": "分配任务已中断",
            }
            return {
                "kind": "finished",
                "label": labels[status],
                "state": status,
                "reply_id": event.reply_id,
                "created_at": now,
            }
        return None

    @classmethod
    def _append_activity(
        cls,
        activities: list[dict[str, Any]],
        activity: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if activities:
            previous = activities[-1]
            fingerprint = (
                previous.get("kind"),
                previous.get("state"),
                previous.get("tool_call_id"),
                previous.get("tool_name"),
            )
            incoming = (
                activity.get("kind"),
                activity.get("state"),
                activity.get("tool_call_id"),
                activity.get("tool_name"),
            )
            if fingerprint == incoming:
                return [*activities[:-1], activity]
        return [*activities, activity][-cls._MAX_ACTIVITIES :]

    async def maybe_project(
        self,
        user_id: str,
        session_record: "SessionRecord",
        agent_record: "AgentRecord",
        event: "AgentEvent",
        projection: "SessionProjection",
    ) -> None:
        if not session_record.team_id or not isinstance(
            event,
            (
                ReplyStartEvent,
                ModelCallStartEvent,
                ToolCallStartEvent,
                ToolResultEndEvent,
                RequireUserConfirmEvent,
                RequireExternalExecutionEvent,
                ReplyEndEvent,
            ),
        ):
            return

        team = await self._storage.get_team(user_id, session_record.team_id)
        if team is None or team.session_id == session_record.id:
            return
        member: "TeamMember | None" = next(
            (
                item
                for item in await _ensure_team_members(
                    self._storage,
                    user_id,
                    team,
                )
                if item.session_id == session_record.id
            ),
            None,
        )
        if member is None:
            return

        stored = next(
            (
                item
                for item in await projection.list(team.session_id, self.KIND)
                if item.get("worker_session_id") == session_record.id
            ),
            None,
        )
        activity = self._activity_for_event(event, stored)
        if activity is None:
            return

        same_revision = (
            stored is not None
            and int(stored.get("work_revision") or 0) == member.work_revision
        )
        activities = list(stored.get("activities") or []) if same_revision else []
        activities = self._append_activity(activities, activity)
        status = member.work_status
        if isinstance(event, ReplyStartEvent):
            status = "running"
        elif isinstance(event, ReplyEndEvent):
            status = self._terminal_status(event)

        payload = {
            "team_id": team.id,
            "team_name": team.data.name,
            "worker_session_id": session_record.id,
            "worker_agent_id": agent_record.id,
            "worker_agent_name": agent_record.data.name,
            "work_revision": member.work_revision,
            "work_status": status,
            "assigned_at": self._iso(member.assigned_at),
            "started_at": (
                activity["created_at"]
                if isinstance(event, ReplyStartEvent)
                else self._iso(member.started_at)
                or (stored or {}).get("started_at")
            ),
            "settled_at": (
                activity["created_at"]
                if isinstance(event, ReplyEndEvent)
                else self._iso(member.settled_at)
            ),
            "reply_id": activity.get("reply_id"),
            "current_activity": activity,
            "activities": activities,
            "updated_at": activity["created_at"],
        }
        await projection.upsert(
            team.session_id,
            self.KIND,
            self.entry_id(session_record.id),
            payload,
        )
        await projection.publish(team.session_id, self.EVT_UPDATE, payload)

    @classmethod
    async def purge(
        cls,
        projection: "SessionProjection",
        leader_sid: str,
    ) -> None:
        await projection.purge(leader_sid, cls.KIND)

    @classmethod
    async def drop_worker(
        cls,
        projection: "SessionProjection",
        leader_sid: str,
        worker_sid: str,
    ) -> None:
        await projection.delete(
            leader_sid,
            cls.KIND,
            cls.entry_id(worker_sid),
        )
