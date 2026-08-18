"""Tests for independent management login and global configuration scope."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from agentscope.app._auth import AgentScopeAuthConfig
from agentscope.app._router._auth import auth_router
from agentscope.app.deps import get_current_user_id


def _app() -> FastAPI:
    app = FastAPI()
    app.state.auth_config = AgentScopeAuthConfig(
        admin_username="agentscope-admin",
        admin_password="management-password",
        signing_secret="management-signing-secret-for-tests",
        service_token="engineering-platform-service-token",
        global_config_id="platform-global-config",
        management_token_ttl_seconds=3600,
    )
    app.include_router(auth_router)

    @app.get("/admin-probe")
    async def admin_probe(
        config_id: str = Depends(get_current_user_id),
    ) -> dict[str, str]:
        return {"config_id": config_id}

    @app.get("/agent/platform/catalog")
    async def platform_catalog_probe(
        config_id: str = Depends(get_current_user_id),
    ) -> dict[str, str]:
        return {"config_id": config_id}

    @app.get("/agent/platform/weknora/knowledge-bases")
    async def weknora_runtime_probe(
        config_id: str = Depends(get_current_user_id),
    ) -> dict[str, str]:
        return {"config_id": config_id}

    @app.post("/agent/platform/weknora/agent-query")
    async def weknora_agent_query_probe(
        config_id: str = Depends(get_current_user_id),
    ) -> dict[str, str]:
        return {"config_id": config_id}

    @app.post("/agent/platform/weknora/sessions")
    async def weknora_session_probe(
        config_id: str = Depends(get_current_user_id),
    ) -> dict[str, str]:
        return {"config_id": config_id}

    @app.post("/agent/platform/weknora/sessions/{session_id}/stop")
    async def weknora_session_stop_probe(
        session_id: str,
        config_id: str = Depends(get_current_user_id),
    ) -> dict[str, str]:
        return {"config_id": config_id, "session_id": session_id}

    @app.get("/agent/platform/weknora/project-bindings")
    async def weknora_binding_probe(
        config_id: str = Depends(get_current_user_id),
    ) -> dict[str, str]:
        return {"config_id": config_id}

    return app


def test_management_account_only_authorizes_global_configuration() -> None:
    client = TestClient(_app())
    login = client.post(
        "/auth/login",
        json={
            "username": "agentscope-admin",
            "password": "management-password",
        },
    )
    assert login.status_code == 200

    response = client.get(
        "/admin-probe",
        headers={
            "Authorization": (f"Bearer {login.json()['access_token']}"),
        },
    )
    assert response.status_code == 200
    assert response.json() == {"config_id": "platform-global-config"}


def test_arbitrary_user_header_cannot_log_in_when_auth_is_enabled() -> None:
    response = TestClient(_app()).get(
        "/admin-probe",
        headers={"X-User-ID": "some-platform-user"},
    )
    assert response.status_code == 401


def test_platform_service_can_read_catalog_but_not_management_api() -> None:
    client = TestClient(_app())
    headers = {
        "Authorization": "Bearer engineering-platform-service-token",
    }

    catalog = client.get("/agent/platform/catalog", headers=headers)
    forbidden = client.get("/admin-probe", headers=headers)

    assert catalog.status_code == 200
    assert catalog.json() == {"config_id": "platform-global-config"}
    assert forbidden.status_code == 403


def test_platform_service_can_only_use_robot_scoped_weknora_runtime() -> None:
    client = TestClient(_app())
    headers = {
        "Authorization": "Bearer engineering-platform-service-token",
    }

    scoped = client.get(
        "/agent/platform/weknora/knowledge-bases",
        params={"weknora_agent_id": "project-robot"},
        headers=headers,
    )
    unscoped = client.get(
        "/agent/platform/weknora/knowledge-bases",
        headers=headers,
    )
    agent_query = client.post(
        "/agent/platform/weknora/agent-query",
        headers=headers,
    )
    session = client.post(
        "/agent/platform/weknora/sessions",
        headers=headers,
    )
    session_stop = client.post(
        "/agent/platform/weknora/sessions/session-1/stop",
        headers=headers,
    )
    project_bindings = client.get(
        "/agent/platform/weknora/project-bindings",
        headers=headers,
    )

    assert scoped.status_code == 200
    assert scoped.json() == {"config_id": "platform-global-config"}
    assert agent_query.status_code == 200
    assert session.status_code == 200
    assert session_stop.status_code == 200
    assert unscoped.status_code == 403
    assert project_bindings.status_code == 403


def test_invalid_management_password_is_rejected() -> None:
    response = TestClient(_app()).post(
        "/auth/login",
        json={
            "username": "agentscope-admin",
            "password": "incorrect",
        },
    )
    assert response.status_code == 401
