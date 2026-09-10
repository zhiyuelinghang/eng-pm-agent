from copy import deepcopy

from backend.app.agent_api_support import _agentscope_platform_messages


def message(mid="assignment", revision=1):
    member = {"team_id": "team", "worker_session_id": "worker", "worker_agent_id": "worker-agent", "work_revision": revision}
    return {"id": mid, "role": "assistant", "finished_at": "2026-09-10T14:01:00Z", "finished_reason": "completed", "content": [
        {"type": "tool_call", "id": "invite", "name": "AgentInvite", "state": "finished"},
        {"type": "tool_result", "id": "invite", "name": "AgentInvite", "state": "success", "metadata": {"collaboration_member": member}},
    ], "metadata": {"collaboration_progress_archive": [{"leader_session_id": "leader", "assignment_message_id": mid, "assignment_tool_call_id": "invite", "progress": {
        **member, "work_status": "completed", "updated_at": "2026-09-10T14:00:00Z", "thinking": "secret", "activities": [{"kind": "tool", "tool_name": "read", "state": "success", "input": "secret"}],
    }}]}}


def collaborations(raw, sid="leader"):
    rows = _agentscope_platform_messages(7, raw, "idle", sid)
    return [(row["extra_data"].get("runtime_trace") or {}).get("collaborations", []) for row in rows if row["role"] == "assistant"]


def test_stream_trace_missing_history_recovers_only_exact_scoped_archive_without_secrets():
    assert collaborations([message()])[0][0]["work_status"] == "completed"
    assert "secret" not in str(collaborations([message()]))
    assert collaborations([message()], "other-session") == [[]]
    for field, value in [("assignment_message_id", "other"), ("assignment_tool_call_id", "other")]:
        raw = message(); raw["metadata"]["collaboration_progress_archive"][0][field] = value
        assert collaborations([raw]) == [[]]
    raw = message(); raw["metadata"]["collaboration_progress_archive"][0]["progress"]["work_revision"] = 2
    assert collaborations([raw]) == [[]]


def test_archives_do_not_cross_user_turns_and_newer_trace_wins_same_revision():
    first = message()
    later = {"id": "later", "role": "assistant", "content": [{"type": "text", "text": "第二轮"}], "metadata": {}, "finished_at": "2026-09-10T15:00:00Z"}
    result = collaborations([first, {"id": "user-2", "role": "user", "content": [{"type": "text", "text": "新任务"}]}, later])
    assert len(result[0]) == 1 and result[1] == []
    trace = deepcopy(first["metadata"]["collaboration_progress_archive"][0]["progress"])
    trace.update(work_status="reported", updated_at="2026-09-10T14:02:00Z")
    first["metadata"]["platform_runtime_trace"] = {"collaborations": [trace]}
    assert collaborations([first])[0][0]["work_status"] == "reported"


def test_malformed_legacy_archive_or_unsuccessful_invite_does_not_break_history():
    for malformed in [None, "old", {"bad": True}]:
        raw = message(); raw["metadata"]["collaboration_progress_archive"] = malformed
        assert collaborations([raw]) == [[]]
    raw = message(); raw["content"][1]["state"] = "error"
    assert collaborations([raw]) == [[]]
