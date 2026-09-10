"""The platform gateway shares the saved main model and has no agent run."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentscope.app._auth import AgentScopeAuthConfig, issue_management_token
from agentscope.app._router import _platform_completion as completion
from agentscope.app.storage import ChatModelConfig
from agentscope.message import TextBlock, ThinkingBlock
from agentscope.model import ChatResponse


BODY = {"system_prompt": "遵循项目事实。", "prompt": "列出资料缺口。"}
SERVICE_HEADERS = {"Authorization": "Bearer test-platform-service-token"}


def _app():
    app = FastAPI()
    app.state.auth_config = AgentScopeAuthConfig(
        admin_username="admin", admin_password="test-management-password",
        signing_secret="test-management-signing-secret",
        service_token="test-platform-service-token",
        global_config_id="global-config", management_token_ttl_seconds=3600,
    )
    config = ChatModelConfig(
        type="custom_openai_credential", credential_id="saved-credential",
        model="saved-model", parameters={"temperature": 0, "max_tokens": 19},
    )
    policy = SimpleNamespace(mode="fixed", chat_model_config=config)
    # Only reads are supplied: an accidental session or memory write fails.
    app.state.storage = SimpleNamespace(
        get_platform_settings=AsyncMock(return_value=SimpleNamespace(
            data=SimpleNamespace(global_main_agent_id="main-agent"),
        )),
        get_agent=AsyncMock(return_value=SimpleNamespace(
            data=SimpleNamespace(model_policy=policy),
        )),
    )
    app.state.resource_access_service = object()
    app.include_router(completion.platform_completion_router)
    return app, policy


def test_service_uses_saved_global_model_without_binding_overrides_or_tools(monkeypatch):
    app, policy = _app()
    model = AsyncMock(return_value=ChatResponse(
        content=[ThinkingBlock(thinking="内部推理"), TextBlock(text="  缺少验收记录。  ")],
        is_last=True,
    ))
    factory = AsyncMock(return_value=model)
    monkeypatch.setattr(completion, "get_model", factory)

    response = TestClient(app).post(
        "/platform/model-completion", headers=SERVICE_HEADERS, json=BODY,
    )

    assert response.status_code == 200
    assert response.json() == {"content": "缺少验收记录。"}
    app.state.storage.get_platform_settings.assert_awaited_once_with("global-config")
    app.state.storage.get_agent.assert_awaited_once_with("global-config", "main-agent")
    user_id, config, access = factory.await_args.args
    assert user_id == "global-config"
    assert config.model == "saved-model"
    assert config.credential_id == "saved-credential"
    assert config.parameters == {}
    assert policy.chat_model_config.parameters == {"temperature": 0, "max_tokens": 19}
    assert access is app.state.resource_access_service
    assert model.stream is False
    assert model.await_args.kwargs == {"tools": None}
    assert [message.role for message in model.await_args.args[0]] == ["system", "user"]


@pytest.mark.parametrize("caller", ["anonymous", "management", "legacy"])
def test_completion_rejects_every_non_service_caller(caller, monkeypatch):
    app, _ = _app()
    factory = AsyncMock()
    monkeypatch.setattr(completion, "get_model", factory)
    headers = {}
    expected = 403
    if caller == "management":
        token = issue_management_token(app.state.auth_config).access_token
        headers = {"Authorization": f"Bearer {token}"}
    elif caller == "legacy":
        app.state.auth_config = None
        headers = {"X-User-ID": "legacy-user"}
    else:
        expected = 401

    response = TestClient(app).post("/platform/model-completion", headers=headers, json=BODY)

    assert response.status_code == expected
    factory.assert_not_awaited()
    app.state.storage.get_agent.assert_not_awaited()


def test_request_cannot_select_a_model_or_override_catalogue_parameters(monkeypatch):
    app, _ = _app()
    factory = AsyncMock()
    monkeypatch.setattr(completion, "get_model", factory)
    response = TestClient(app).post(
        "/platform/model-completion", headers=SERVICE_HEADERS,
        json={**BODY, "credential_id": "other", "model": "other", "parameters": {}},
    )
    assert response.status_code == 422
    factory.assert_not_awaited()


@pytest.mark.parametrize("missing", ["main", "fixed_policy", "model"])
def test_missing_main_model_is_a_configuration_error(missing, monkeypatch):
    app, policy = _app()
    if missing == "main":
        app.state.storage.get_platform_settings.return_value = None
    elif missing == "fixed_policy":
        policy.mode = "follow_session"
    else:
        policy.chat_model_config = None
    factory = AsyncMock()
    monkeypatch.setattr(completion, "get_model", factory)
    response = TestClient(app).post(
        "/platform/model-completion", headers=SERVICE_HEADERS, json=BODY,
    )
    assert response.status_code == 409
    factory.assert_not_awaited()


@pytest.mark.parametrize("failure", ["empty", "exception"])
def test_generation_failure_returns_a_safe_error(failure, monkeypatch):
    app, _ = _app()
    model = AsyncMock(return_value=ChatResponse(content=[], is_last=True))
    if failure == "exception":
        model.side_effect = RuntimeError("provider secret: test-secret-value")
    monkeypatch.setattr(completion, "get_model", AsyncMock(return_value=model))
    response = TestClient(app).post(
        "/platform/model-completion", headers=SERVICE_HEADERS, json=BODY,
    )
    assert response.status_code == 502
    assert "test-secret-value" not in response.text
