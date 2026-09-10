"""Legacy collaboration uses the shared platform model without an AI_* path."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app import collaboration_api
from backend.app.agentscope_client import AgentScopeClient, AgentScopeGatewayError
from backend.app.config import Settings


def _client():
    return AgentScopeClient(Settings(
        agentscope_base_url="http://test.invalid",
        database_url="postgresql://user:password@localhost/test",
        agentscope_service_token="test-service-token",
    ))


def test_client_sends_only_prompts_with_service_auth_and_waits_for_generation():
    client = _client()
    client._request = Mock(return_value={"content": "  模型建议  "})
    assert client.complete_platform_text(system_prompt="范围", prompt="问题") == "模型建议"
    client._request.assert_called_once_with(
        "POST", "/platform/model-completion",
        json={"system_prompt": "范围", "prompt": "问题"}, wait_for_response=True,
    )
    assert client.headers == {"Authorization": "Bearer test-service-token"}


@pytest.mark.parametrize("payload", [{}, {"content": " "}, {"content": ["invalid"]}])
def test_client_rejects_missing_text(payload):
    client = _client()
    client._request = Mock(return_value=payload)
    with pytest.raises(AgentScopeGatewayError) as error:
        client.complete_platform_text(system_prompt="范围", prompt="问题")
    assert error.value.status_code == 502


def _collaboration_context(monkeypatch):
    db = Mock()
    db.scalars.return_value.all.return_value = []
    db.execute.return_value.all.return_value = [
        ("验收记录.txt", "验收", "示例验收内容", "ready", None),
    ]
    project = SimpleNamespace(
        name="示例项目", construction_unit_name="示例单位",
        engineering_type_description="示例说明",
    )
    task = SimpleNamespace(
        id="project-task", title="补充验收记录", state="open",
        due_at=None, scope={"project_id": 7},
    )
    other = SimpleNamespace(id="other-task", scope={"project_id": 8})
    monkeypatch.setattr(collaboration_api, "project_or_404", Mock(return_value=project))
    monkeypatch.setattr(collaboration_api, "get_engine", Mock(return_value=SimpleNamespace(
        list_tasks=Mock(return_value=[task, other]),
    )))
    return db


def test_collaboration_keeps_project_evidence_and_related_tasks(monkeypatch):
    db = _collaboration_context(monkeypatch)
    gateway = SimpleNamespace(complete_platform_text=Mock(return_value="共享模型建议"))
    monkeypatch.setattr(collaboration_api, "_agentscope_client", Mock(return_value=gateway))

    answer, related = collaboration_api.collaboration_reply(7, "检查缺口", db)

    assert answer == "共享模型建议"
    assert related == ["project-task"]
    prompt = gateway.complete_platform_text.call_args.kwargs["prompt"]
    for expected in ("示例项目", "示例验收内容", "补充验收记录", "检查缺口"):
        assert expected in prompt
    assert "other-task" not in prompt
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_collaboration_preserves_existing_business_fallback(monkeypatch):
    db = _collaboration_context(monkeypatch)
    gateway = SimpleNamespace(complete_platform_text=Mock(
        side_effect=AgentScopeGatewayError("暂不可用", status_code=503),
    ))
    monkeypatch.setattr(collaboration_api, "_agentscope_client", Mock(return_value=gateway))
    answer, related = collaboration_api.collaboration_reply(7, "检查缺口", db)
    assert "优先处理「补充验收记录」" in answer
    assert related == ["project-task"]
