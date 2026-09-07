"""Render authoritative worker confirmation cards for polling clients."""

from typing import Any


def pending_input_message(
    payload: dict[str, Any], last_message: dict[str, Any] | None,
    submitted_tool_call: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    entries = [item for item in payload.get("subagent_hitl", [])
               if item.get("event_type") == "require_user_confirm"]
    if submitted_tool_call is not None:
        entries = [item for item in entries if any(
            str(call.get("id")) != str(submitted_tool_call.get("id"))
            or int(call.get("confirmation_revision") or 0) >
               int(submitted_tool_call.get("confirmation_revision") or 0)
            for call in (item.get("event") or {}).get("tool_calls", [])
        )]
    if not entries:
        return None
    message = dict(last_message or {
        "id": f"pending-{entries[0]['reply_id']}", "role": "assistant", "content": [],
    })
    metadata = dict(message.get("metadata") or {})
    trace = dict(metadata.get("platform_runtime_trace") or {})
    trace["subagent_hitl"] = entries
    metadata["platform_runtime_trace"] = trace
    message["metadata"] = metadata
    return message
