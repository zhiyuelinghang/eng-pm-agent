from backend.app.agent_api_support import _resolved_runtime_trace
from backend.app.agentscope_client import AgentScopeReply


def test_source_models_survive_missing_or_empty_stream_summary():
    messages = [
        {"id": "a", "metadata": {"model_names": ["actual-model"], "platform_runtime_trace": {"model_names": ["actual-model"]}}},
        {"id": "b", "metadata": {"model_names": ["fallback-model"]}},
    ]
    reply = AgentScopeReply(status="completed", content="完成", message_id="b", raw_message=messages[-1], raw_messages=messages)
    for summary in (None, {"model_names": []}):
        assert _resolved_runtime_trace(reply, summary)["model_names"] == ["actual-model", "fallback-model"]
