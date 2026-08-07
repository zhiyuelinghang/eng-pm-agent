# -*- coding: utf-8 -*-
"""Durable lifecycle bookkeeping for asynchronous team work.

Session ``running``/``idle`` is only a transient process state. A queued
member can still be idle before its run starts, and a leader can become idle
while waiting for reports. This module records assignments and settlements in
the team record so callers can determine whether the *business turn* is really
finished.
"""
from datetime import UTC, datetime
from typing import Literal, TYPE_CHECKING

from .message_bus import MessageBusKeys
from .storage._utils import _ensure_team_members

if TYPE_CHECKING:
    from .message_bus import MessageBus
    from .storage import StorageBase, TeamMember, TeamRecord

MemberTerminalStatus = Literal[
    "reported",
    "completed",
    "failed",
    "interrupted",
]


def _prepare_member_assignment(
    team: "TeamRecord",
    member: "TeamMember",
) -> int:
    """Advance one member to a fresh queued assignment in memory."""
    team.data.work_revision += 1
    member.work_revision = team.data.work_revision
    if member.active_revision <= member.settled_revision:
        member.active_revision = 0
        member.work_status = "queued"
        member.started_at = None
    member.assigned_at = datetime.now(UTC)
    member.settled_at = None
    member.last_reply_id = None
    member.last_error = None
    return member.work_revision


def team_work_is_pending(team: "TeamRecord") -> bool:
    """Return whether a team still owes member work or a leader summary."""
    if any(
        member.settled_revision < member.work_revision
        for member in team.data.members
    ):
        return True
    return team.data.leader_completed_revision < team.data.work_revision


async def assign_team_member(
    storage: "StorageBase",
    message_bus: "MessageBus",
    *,
    user_id: str,
    team_id: str,
    member_session_id: str,
) -> int | None:
    """Advance and persist one member assignment.

    Returns the assigned revision, or ``None`` when the team/member vanished.
    """
    async with message_bus.acquire_lock(
        MessageBusKeys.team_lifecycle_lock(team_id),
        ttl_secs=30,
    ):
        team = await storage.get_team(user_id, team_id)
        if team is None:
            return None
        members = await _ensure_team_members(storage, user_id, team)
        member = next(
            (
                item
                for item in members
                if item.session_id == member_session_id
            ),
            None,
        )
        if member is None:
            return None
        revision = _prepare_member_assignment(team, member)
        await storage.upsert_team(user_id, team)
        return revision


async def add_and_assign_team_member(
    storage: "StorageBase",
    message_bus: "MessageBus",
    *,
    user_id: str,
    team_id: str,
    member: "TeamMember",
) -> int | None:
    """Atomically append a new member and record its first assignment.

    Several ``AgentInvite`` calls can run in parallel in one model turn.  A
    stale read followed by a whole-team upsert would otherwise let the last
    invite overwrite members appended by the other calls.  Membership and
    the first work revision therefore share the team lifecycle lock.
    """
    async with message_bus.acquire_lock(
        MessageBusKeys.team_lifecycle_lock(team_id),
        ttl_secs=30,
    ):
        team = await storage.get_team(user_id, team_id)
        if team is None:
            return None
        members = await _ensure_team_members(storage, user_id, team)
        if any(
            item.agent_id == member.agent_id
            or item.session_id == member.session_id
            for item in members
        ):
            return None

        assigned = member.model_copy(deep=True)
        revision = _prepare_member_assignment(team, assigned)
        team.data.members = [*members, assigned]
        if assigned.role == "created" and assigned.agent_id not in (
            team.data.member_ids
        ):
            team.data.member_ids = [
                *team.data.member_ids,
                assigned.agent_id,
            ]
        await storage.upsert_team(user_id, team)
        return revision


async def mark_team_member_running(
    storage: "StorageBase",
    message_bus: "MessageBus",
    *,
    user_id: str,
    team_id: str,
    member_session_id: str,
) -> int | None:
    """Mark a queued member as running and return its assignment revision."""
    async with message_bus.acquire_lock(
        MessageBusKeys.team_lifecycle_lock(team_id),
        ttl_secs=30,
    ):
        team = await storage.get_team(user_id, team_id)
        if team is None or team.session_id == member_session_id:
            return None
        members = await _ensure_team_members(storage, user_id, team)
        member = next(
            (
                item
                for item in members
                if item.session_id == member_session_id
            ),
            None,
        )
        if member is None or member.work_revision <= member.settled_revision:
            return None
        member.active_revision = member.work_revision
        member.work_status = "running"
        member.started_at = datetime.now(UTC)
        await storage.upsert_team(user_id, team)
        return member.active_revision


async def mark_team_leader_running(
    storage: "StorageBase",
    message_bus: "MessageBus",
    *,
    user_id: str,
    team_id: str,
    leader_session_id: str,
) -> int | None:
    """Snapshot the settlement counter seen when a leader turn starts."""
    async with message_bus.acquire_lock(
        MessageBusKeys.team_lifecycle_lock(team_id),
        ttl_secs=30,
    ):
        team = await storage.get_team(user_id, team_id)
        if team is None or team.session_id != leader_session_id:
            return None
        return team.data.settlement_revision


async def settle_team_member(
    storage: "StorageBase",
    message_bus: "MessageBus",
    *,
    user_id: str,
    team_id: str,
    member_session_id: str,
    status: MemberTerminalStatus,
    revision: int | None = None,
    reply_id: str | None = None,
    error: str | None = None,
) -> bool:
    """Settle one assignment exactly once.

    ``revision`` snapshots the work seen when the run started. A later
    assignment delivered while that run is finishing therefore remains
    outstanding instead of being accidentally acknowledged.
    """
    async with message_bus.acquire_lock(
        MessageBusKeys.team_lifecycle_lock(team_id),
        ttl_secs=30,
    ):
        team = await storage.get_team(user_id, team_id)
        if team is None or team.session_id == member_session_id:
            return False
        members = await _ensure_team_members(storage, user_id, team)
        member = next(
            (
                item
                for item in members
                if item.session_id == member_session_id
            ),
            None,
        )
        if member is None:
            return False
        target_revision = (
            member.active_revision or member.work_revision
            if revision is None
            else revision
        )
        target_revision = min(target_revision, member.work_revision)
        if target_revision <= member.settled_revision:
            return False
        member.settled_revision = target_revision
        if member.active_revision == target_revision:
            member.active_revision = 0
        member.work_status = (
            status
            if target_revision == member.work_revision
            else "queued"
        )
        member.settled_at = datetime.now(UTC)
        member.last_reply_id = reply_id
        member.last_error = error
        team.data.settlement_revision += 1
        await storage.upsert_team(user_id, team)
        return True


async def mark_team_leader_completed(
    storage: "StorageBase",
    message_bus: "MessageBus",
    *,
    user_id: str,
    team_id: str,
    leader_session_id: str,
    observed_settlement_revision: int | None = None,
) -> bool:
    """Acknowledge a leader turn only after every member has settled."""
    async with message_bus.acquire_lock(
        MessageBusKeys.team_lifecycle_lock(team_id),
        ttl_secs=30,
    ):
        team = await storage.get_team(user_id, team_id)
        if team is None or team.session_id != leader_session_id:
            return False
        if observed_settlement_revision is None:
            # The leader was not known to be leading this team when its
            # current turn started (for example, it created the team during
            # that turn). It therefore cannot have consumed a report that
            # arrived asynchronously during the same turn.
            return False
        members = await _ensure_team_members(storage, user_id, team)
        if any(
            member.settled_revision < member.work_revision
            for member in members
        ):
            return False
        if team.data.settlement_revision != observed_settlement_revision:
            return False
        if team.data.leader_completed_revision >= team.data.work_revision:
            return False
        team.data.leader_completed_revision = team.data.work_revision
        await storage.upsert_team(user_id, team)
        return True
