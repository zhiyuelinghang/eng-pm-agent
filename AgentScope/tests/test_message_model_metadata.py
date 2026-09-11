from agentscope.event import ModelCallStartEvent
from agentscope.message import AssistantMsg, Msg


def test_source_reply_keeps_actual_models_after_serialization():
    message = AssistantMsg(id="reply", name="助手", content=[], metadata={"existing": True})
    for name in ("model-a", "model-a", "fallback-b"):
        message.append_event(ModelCallStartEvent(reply_id="reply", model_name=name))
    restored = Msg.model_validate(message.model_dump())
    assert restored.metadata == {"existing": True, "model_names": ["model-a", "fallback-b"]}
    restored.append_event(ModelCallStartEvent(reply_id="other", model_name="unrelated"))
    assert restored.metadata["model_names"] == ["model-a", "fallback-b"]
