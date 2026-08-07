import asyncio

import pytest

from agentscope.app.database_interactions import (
    DatabaseInteractionGatewayError,
    DatabaseInteractionManager,
)
from agentscope.app.database_interactions import _manager as manager_module
from agentscope.app._router._database_interaction import (
    database_interaction_router,
)


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""
        self.reason_phrase = "error"

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self) -> dict:
        return self._payload


def test_agent_management_exposes_table_policies_as_read_only() -> None:
    policy_routes = [
        route
        for route in database_interaction_router.routes
        if route.path.startswith("/database-interactions/policies")
    ]

    assert len(policy_routes) == 1
    assert policy_routes[0].path == "/database-interactions/policies"
    assert policy_routes[0].methods == {"GET"}


def test_catalog_uses_backend_owned_declarative_catalog(monkeypatch) -> None:
    calls: list[tuple[str, str, dict | None]] = []

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def request(self, method, url, headers, json=None):
            del headers
            calls.append((method, url, json))
            return _Response(
                200,
                {
                    "success": True,
                    "data": [{"id": 1, "key": "dobby_overview"}],
                },
            )

    monkeypatch.setattr(manager_module.httpx, "AsyncClient", _Client)
    manager = DatabaseInteractionManager(
        base_url="http://platform/api/internal",
        token="service-token",
    )

    first = asyncio.run(manager.list_catalog("agent-1", None))
    second = asyncio.run(manager.list_catalog("agent-1", []))

    assert first == second == [{"id": 1, "key": "dobby_overview"}]
    assert not any(url.endswith("/bootstrap") for _, url, _ in calls)
    assert sum(url.endswith("/catalog") for _, url, _ in calls) == 2


def test_gateway_error_keeps_backend_status_and_detail(monkeypatch) -> None:
    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def request(self, *_args, **_kwargs):
            return _Response(409, {"detail": "白名单仍被交互引用"})

    monkeypatch.setattr(manager_module.httpx, "AsyncClient", _Client)
    manager = DatabaseInteractionManager(
        base_url="http://platform/api/internal",
        token="service-token",
    )

    with pytest.raises(DatabaseInteractionGatewayError) as error:
        asyncio.run(manager.list_policies())

    assert error.value.status_code == 409
    assert error.value.detail == "白名单仍被交互引用"
