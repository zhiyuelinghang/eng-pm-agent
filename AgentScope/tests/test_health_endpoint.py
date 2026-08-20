"""Readiness endpoint regression tests."""

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from fastapi import Response, status

from agentscope.app._router._health import get_health


class HealthEndpointTest(IsolatedAsyncioTestCase):
    """Health checks must distinguish optional and required components."""

    @staticmethod
    def _request(**overrides: object) -> SimpleNamespace:
        component_names = (
            "storage",
            "message_bus",
            "workspace_manager",
            "background_task_manager",
            "chat_run_registry",
            "scheduler_manager",
            "resource_access_service",
            "permission_review_service",
            "chat_service",
            "session_service",
        )
        state = SimpleNamespace(
            **{name: object() for name in component_names},
        )
        for name, value in overrides.items():
            setattr(state, name, value)
        return SimpleNamespace(
            app=SimpleNamespace(state=state, version="test-version"),
        )

    async def test_optional_services_can_be_disabled(self) -> None:
        response = Response()

        payload = await get_health(self._request(), response, "user")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(payload.status, "ok")
        self.assertEqual(payload.components["mcp_registry"], "disabled")
        self.assertEqual(payload.components["knowledge_base"], "disabled")

    async def test_missing_required_service_returns_not_ready(self) -> None:
        response = Response()

        payload = await get_health(
            self._request(chat_service=None),
            response,
            "user",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        self.assertEqual(payload.status, "not_ready")
        self.assertEqual(payload.components["chat_service"], "not_ready")
