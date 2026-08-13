from __future__ import annotations

from scripts.backfill_unified_memory import (
    _history_messages,
    _message_text,
    _resolve_bindings,
)


def _session(
    session_id: str,
    *,
    user_id: str = "user-a",
    agent_id: str = "",
    team_id: str | None = None,
    project_id: str | None = None,
) -> dict:
    context = None
    if project_id is not None:
        context = {"project_id": project_id, "user_id": user_id}
    return {
        "id": session_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "team_id": team_id,
        "payload": {
            "config": {
                "workspace_id": "workspace-a",
                "platform_context": context,
            },
            "state": {},
        },
    }


def test_team_worker_inherits_leader_project_binding() -> None:
    sessions = [
        _session("leader", project_id="7"),
        _session(
            "worker",
            agent_id="agent-a",
            team_id="team-a",
        ),
        _session("unbound", agent_id="agent-b"),
    ]
    teams = [
        {
            "id": "team-a",
            "user_id": "user-a",
            "session_id": "leader",
            "payload": {},
        },
    ]

    bindings = _resolve_bindings(sessions, teams)

    assert bindings["leader"].project_id == "7"
    assert bindings["worker"].project_id == "7"
    assert "unbound" not in bindings


def test_history_backfill_keeps_only_plain_user_assistant_text() -> None:
    rows = [
        {
            "session_id": "session-a",
            "msg_id": "message-a",
            "created_at": "2026-08-13T00:00:00",
            "payload": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "确认 PostgreSQL 方案"},
                    {"type": "image", "source": "ignored"},
                ],
            },
        },
        {
            "session_id": "session-a",
            "msg_id": "message-b",
            "created_at": "2026-08-13T00:00:01",
            "payload": {
                "role": "system",
                "content": [{"type": "text", "text": "ignored"}],
            },
        },
    ]

    messages = _history_messages(rows)

    assert len(messages) == 1
    assert messages[0].text == "确认 PostgreSQL 方案"
    assert _message_text(
        {"content": [{"type": "text", "text": "binary\x00payload"}]},
    ) is None
