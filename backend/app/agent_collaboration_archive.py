"""Read runtime-owned progress archives anchored to this exact message/turn."""
from typing import Any


def _identity(value: Any):
    if not isinstance(value, dict):
        return None
    ids = tuple(value.get(key) for key in ("team_id", "worker_session_id", "worker_agent_id"))
    revision = value.get("work_revision")
    if not all(isinstance(item, str) and item for item in ids) or type(revision) is not int or revision <= 0:
        return None
    return (*ids, revision)


def merge_archived_collaborations(messages: list[dict], session_id: str | None, current: list[dict]) -> list[dict]:
    if not session_id:
        return current
    result = {_identity(value): value for value in current if _identity(value)}
    unkeyed = [value for value in current if not _identity(value)]
    for message in messages:
        calls = {(block.get("id"), block.get("name")) for block in message.get("content") or []
                 if isinstance(block, dict) and block.get("type") == "tool_call" and block.get("name") in {"AgentInvite", "AgentCreate", "TeamSay"}}
        anchors = set()
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result" or block.get("state") != "success" or (block.get("id"), block.get("name")) not in calls:
                continue
            metadata = block.get("metadata")
            if not isinstance(metadata, dict):
                continue
            members = metadata.get("collaboration_members")
            for member in [metadata.get("collaboration_member"), *(members if isinstance(members, list) else [])]:
                if _identity(member):
                    anchors.add((block.get("id"), _identity(member)))
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        archive = metadata.get("collaboration_progress_archive")
        for entry in archive if isinstance(archive, list) else []:
            if not isinstance(entry, dict) or entry.get("leader_session_id") != session_id or entry.get("assignment_message_id") != message.get("id"):
                continue
            value = entry.get("progress")
            key = _identity(value)
            if (entry.get("assignment_tool_call_id"), key) not in anchors:
                continue
            existing = result.get(key)
            terminal = {"reported", "completed", "failed", "interrupted"}
            if existing and existing.get("work_status") in terminal and value.get("work_status") not in terminal:
                continue
            if existing is None or (value.get("work_status") in terminal and existing.get("work_status") not in terminal) or str(value.get("updated_at") or "") >= str(existing.get("updated_at") or ""):
                result[key] = _safe_progress(value)
    return [*unkeyed, *result.values()]


def _safe_progress(value):
    fields = {"team_id", "team_name", "worker_session_id", "worker_agent_id", "worker_agent_name", "work_revision", "work_status", "assigned_at", "started_at", "settled_at", "reply_id", "updated_at"}
    result = {key: value[key] for key in fields if key in value and isinstance(value[key], (str, int, type(None)))}
    def activity(raw):
        if not isinstance(raw, dict):
            return None
        item = {key: raw[key] for key in ("kind", "label", "state", "reply_id", "tool_call_id", "tool_name", "created_at") if isinstance(raw.get(key), str)}
        presentation = raw.get("presentation")
        if isinstance(presentation, dict):
            item["presentation"] = {key: presentation[key] for key in ("label", "source", "category") if isinstance(presentation.get(key), str)}
        return item
    values = value.get("activities")
    result["activities"] = [item for raw in (values if isinstance(values, list) else [])[-12:] if (item := activity(raw))]
    result["current_activity"] = activity(value.get("current_activity"))
    return result
