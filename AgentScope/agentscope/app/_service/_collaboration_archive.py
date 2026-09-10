"""Keep safe member progress on the exact message which assigned its work.

The live projection is intentionally deleted with a team. This archive belongs
to the assigning message and survives transport disconnects and team cleanup.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..._logging import logger
from ._session_projection import SessionProjection

ARCHIVE_KEY = "collaboration_progress_archive"
PROGRESS_KIND = "collaboration_progress"
_TOOLS = {"AgentInvite", "AgentCreate", "TeamSay"}
_PROGRESS_FIELDS = {
    "team_id", "team_name", "worker_session_id", "worker_agent_id",
    "worker_agent_name", "work_revision", "work_status", "assigned_at",
    "started_at", "settled_at", "reply_id", "updated_at",
}
_ACTIVITY_FIELDS = {
    "kind", "label", "state", "reply_id", "tool_call_id", "tool_name", "created_at",
}
_TERMINAL = {"reported", "completed", "failed", "interrupted"}


def identity(value: Any) -> tuple | None:
    if not isinstance(value, dict):
        return None
    identifiers = tuple(value.get(key) for key in ("team_id", "worker_session_id", "worker_agent_id"))
    revision = value.get("work_revision")
    if not all(isinstance(item, str) and item for item in identifiers):
        return None
    if type(revision) is not int or revision <= 0:
        return None
    return (*identifiers, revision)


def assignment_anchors(message: Any) -> list[tuple[str, dict]]:
    raw = message.model_dump(mode="json") if hasattr(message, "model_dump") else message
    if not isinstance(raw, dict) or raw.get("role") != "assistant":
        return []
    blocks = raw.get("content") or []
    calls = {(block.get("id"), block.get("name")) for block in blocks
             if isinstance(block, dict) and block.get("type") == "tool_call" and block.get("name") in _TOOLS}
    anchors = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_result" or block.get("state") != "success":
            continue
        if (block.get("id"), block.get("name")) not in calls:
            continue
        metadata = block.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        members = metadata.get("collaboration_members")
        values = [metadata.get("collaboration_member"), *(members if isinstance(members, list) else [])]
        anchors.extend((str(block["id"]), value) for value in values if identity(value))
    return anchors


def safe_progress(value: dict) -> dict:
    """Allowlist operational fields; never persist tool arguments or text."""
    result = {key: value[key] for key in _PROGRESS_FIELDS if key in value and isinstance(value[key], (str, int, type(None)))}

    def activity(raw):
        if not isinstance(raw, dict):
            return None
        item = {key: raw[key] for key in _ACTIVITY_FIELDS if isinstance(raw.get(key), str)}
        presentation = raw.get("presentation")
        if isinstance(presentation, dict):
            item["presentation"] = {key: presentation[key] for key in ("label", "source", "category") if isinstance(presentation.get(key), str)}
        return item

    activities = value.get("activities")
    result["activities"] = [item for raw in (activities if isinstance(activities, list) else [])[-12:] if (item := activity(raw))]
    result["current_activity"] = activity(value.get("current_activity"))
    return result


def _lock(message_bus, parent_sid):
    return message_bus.acquire_lock(f"agentscope:collaboration:archive:{parent_sid}", ttl_secs=30)


def _observed_progress(team, member, value):
    """Reject snapshots mislabeled with a queued, not-yet-started revision."""
    revision = value.get("work_revision")
    if identity(value) is None or value.get("team_id") != team.id or value.get("worker_agent_id") != member.agent_id:
        return None
    if revision not in {member.active_revision, member.settled_revision} or revision <= 0:
        return None
    result = dict(value)
    if member.settled_revision < revision:
        if result.get("work_status") in {"completed", "reported", "failed", "interrupted"}:
            result["work_status"] = "running"
            result["settled_at"] = None
            result["activities"] = [item for item in result.get("activities") or [] if item.get("kind") != "finished"]
            if (result.get("current_activity") or {}).get("kind") == "finished":
                result["current_activity"] = None
    elif member.work_revision == revision:
        result["work_status"] = member.work_status
        result["settled_at"] = member.settled_at.isoformat() if member.settled_at else result.get("settled_at")
    return result


def _merge(message, parent_sid, previous=None, progress=()):
    anchors = assignment_anchors(message)
    anchor_keys = {(call_id, identity(member)) for call_id, member in anchors}
    archive = {}
    for source in (previous, message):
        metadata = getattr(source, "metadata", None) or {}
        saved = metadata.get(ARCHIVE_KEY)
        for entry in saved if isinstance(saved, list) else []:
            if not isinstance(entry, dict) or entry.get("leader_session_id") != parent_sid or entry.get("assignment_message_id") != message.id:
                continue
            value = entry.get("progress")
            key = (entry.get("assignment_tool_call_id"), identity(value))
            if key not in anchor_keys:
                continue
            existing = archive.get(key)
            if existing is None or str(value.get("updated_at") or "") >= str(existing["progress"].get("updated_at") or ""):
                archive[key] = {"leader_session_id": parent_sid, "assignment_message_id": message.id,
                                "assignment_tool_call_id": key[0], "progress": _preserve_settlement(existing, value)}
    for value in progress:
        for call_id, member in anchors:
            if identity(value) != identity(member):
                continue
            key = (call_id, identity(value))
            existing = archive.get(key)
            if existing is not None and str(existing["progress"].get("updated_at") or "") > str(value.get("updated_at") or ""):
                continue
            archive[key] = {
                "leader_session_id": parent_sid, "assignment_message_id": message.id,
                "assignment_tool_call_id": call_id, "progress": _preserve_settlement(existing, value),
            }
    metadata = {**(getattr(previous, "metadata", None) or {}), **(message.metadata or {})}
    metadata.update({key: value for key, value in (getattr(previous, "metadata", None) or {}).items() if key.startswith("platform_")})
    if archive:
        metadata[ARCHIVE_KEY] = list(archive.values())
    else:
        metadata.pop(ARCHIVE_KEY, None)
    return message.model_copy(update={"metadata": metadata})


def _preserve_settlement(existing, value):
    result = safe_progress(value)
    previous = (existing or {}).get("progress") or {}
    if previous.get("work_status") in _TERMINAL and result.get("work_status") not in _TERMINAL:
        result["work_status"] = previous["work_status"]
        result["settled_at"] = previous.get("settled_at")
    return result


async def _current_progress(storage, message_bus, user_id, parent_sid, message):
    """Read only projections belonging to assignments present in this message."""
    projection = SessionProjection(message_bus)
    snapshots = []
    for team_id in {member["team_id"] for _, member in assignment_anchors(message)}:
        team = await storage.get_team(user_id, team_id)
        if team is None:
            continue
        for value in await projection.list(team.session_id, PROGRESS_KIND):
            member = next((item for item in team.data.members if item.session_id == value.get("worker_session_id") and (item.inviter_session_id or team.session_id) == parent_sid), None)
            if member is not None and (observed := _observed_progress(team, member, value)):
                snapshots.append(observed)
    return snapshots


async def save_message_with_collaboration_progress(storage, message_bus, user_id, session_id, message):
    """Save normal runtime content without overwriting concurrent archives."""
    async with _lock(message_bus, session_id):
        previous = await storage.get_message(user_id, session_id, message.id)
        try:
            snapshots = await _current_progress(storage, message_bus, user_id, session_id, message)
            updated = _merge(message, session_id, previous, snapshots)
        except Exception:
            logger.exception("Unable to merge collaboration history for session %s message %s", session_id, message.id)
            updated = message.model_copy(update={"metadata": {**(getattr(previous, "metadata", None) or {}), **(message.metadata or {})}})
            if (getattr(previous, "metadata", None) or {}).get(ARCHIVE_KEY):
                updated.metadata[ARCHIVE_KEY] = deepcopy(previous.metadata[ARCHIVE_KEY])
        if previous is None:
            await storage.upsert_message(user_id, session_id, updated)
        elif not await storage.update_message_if_exists(user_id, session_id, updated):
            return None
        message.metadata = updated.metadata
        return updated


async def patch_message_metadata(storage, message_bus, user_id, session_id, message_id, metadata):
    async with _lock(message_bus, session_id):
        message = await storage.get_message(user_id, session_id, message_id)
        if message is None:
            return None
        updated = message.model_copy(update={"metadata": {**(message.metadata or {}), **metadata}})
        # The observational archive is owned by the runtime, not by arbitrary
        # metadata patches from a presentation client.
        if (message.metadata or {}).get(ARCHIVE_KEY):
            updated.metadata[ARCHIVE_KEY] = deepcopy(message.metadata[ARCHIVE_KEY])
        else:
            updated.metadata.pop(ARCHIVE_KEY, None)
        if not await storage.update_message_if_exists(user_id, session_id, updated):
            return None
        return updated


async def archive_member_progress(storage, message_bus, user_id, parent_sid, progress):
    """Best-effort archive to an exact successful assignment, never the tail."""
    if identity(progress) is None:
        return False
    try:
        async with _lock(message_bus, parent_sid):
            before = None
            while True:
                messages, has_more = await storage.list_messages(user_id, parent_sid, limit=100, before=before)
                for message in reversed(messages):
                    if any(identity(member) == identity(progress) for _, member in assignment_anchors(message)):
                        updated = _merge(message, parent_sid, progress=[progress])
                        return await storage.update_message_if_exists(user_id, parent_sid, updated)
                if not has_more or not messages:
                    return False
                cursor = messages[0].id
                if cursor == before:
                    return False
                before = cursor
    except Exception:
        logger.exception("Unable to archive collaboration progress for session %s worker %s revision %s", parent_sid, progress.get("worker_session_id"), progress.get("work_revision"))
        return False


async def archive_before_worker_delete(storage, message_bus, user_id, team, worker_sid):
    """Copy the last observed state before cleanup; deletion implies no success."""
    try:
        member = next((item for item in team.data.members if item.session_id == worker_sid), None)
        if member is None:
            return
        parent_sid = member.inviter_session_id or team.session_id
        for progress in await SessionProjection(message_bus).list(team.session_id, PROGRESS_KIND):
            if progress.get("team_id") == team.id and progress.get("worker_session_id") == worker_sid and progress.get("worker_agent_id") == member.agent_id:
                observed = _observed_progress(team, member, progress)
                if observed:
                    await archive_member_progress(storage, message_bus, user_id, parent_sid, observed)
    except Exception:
        logger.exception("Unable to archive member progress before deleting session %s", worker_sid)


async def archive_member_settlement(storage, message_bus, user_id, team, member, revision, status, reply_id):
    """Persist the authoritative settlement, independent of platform SSE."""
    try:
        parent_sid = member.inviter_session_id or team.session_id
        snapshots = await SessionProjection(message_bus).list(team.session_id, PROGRESS_KIND)
        observed = next((value for value in snapshots if value.get("team_id") == team.id and value.get("worker_session_id") == member.session_id and value.get("worker_agent_id") == member.agent_id and value.get("work_revision") == revision), {})
        agent = await storage.get_agent(member.owner_id, member.agent_id)
        settled_at = member.settled_at.isoformat() if member.settled_at else None
        value = {**observed, "team_id": team.id, "team_name": team.data.name,
                 "worker_session_id": member.session_id, "worker_agent_id": member.agent_id,
                 "worker_agent_name": agent.data.name if agent else member.agent_id,
                 "work_revision": revision, "work_status": status, "reply_id": reply_id,
                 "settled_at": settled_at, "updated_at": settled_at}
        if member.work_revision == revision:
            value["assigned_at"] = member.assigned_at.isoformat() if member.assigned_at else None
            value["started_at"] = member.started_at.isoformat() if member.started_at else None
        # If another assignment is queued, only the earlier snapshot may
        # supply its timestamps; the member's current assignment dates differ.
        await archive_member_progress(storage, message_bus, user_id, parent_sid, value)
    except Exception:
        logger.exception("Unable to archive settled collaboration for team %s worker %s revision %s", team.id, member.session_id, revision)
