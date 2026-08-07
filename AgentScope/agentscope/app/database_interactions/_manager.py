"""Trusted proxy from AgentScope management/runtime to the Dobby database."""

from __future__ import annotations

import json
from typing import Any

import httpx


class DatabaseInteractionGatewayError(RuntimeError):
    """Stable transport/API error surfaced by the AgentScope proxy."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class DatabaseInteractionManager:
    """Manage the platform catalogue while keeping DB credentials server-side."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = 20.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        expect_data: bool = True,
        unwrap_data: bool = True,
        timeout: float | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=timeout if timeout is not None else self._timeout,
            ) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json=payload,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise DatabaseInteractionGatewayError(
                503,
                f"工程平台数据库交互服务不可用：{exc}",
            ) from exc
        if response.is_error:
            try:
                body = response.json()
                detail = body.get("detail", body)
            except ValueError:
                detail = response.text or response.reason_phrase
            if not isinstance(detail, str):
                detail = json.dumps(detail, ensure_ascii=False)
            raise DatabaseInteractionGatewayError(response.status_code, detail)
        if not expect_data or response.status_code == 204:
            return None
        body = response.json()
        return body.get("data", body) if unwrap_data else body

    async def resolve_context(self, session_id: str) -> dict[str, Any] | None:
        """Resolve the trusted engineering-platform context for a session."""
        try:
            return await self._request(
                "GET",
                "/agent-tools/context",
                params={"agentscope_session_id": session_id},
            )
        except DatabaseInteractionGatewayError as exc:
            if exc.status_code in {403, 404}:
                return None
            raise

    async def list_catalog(
        self,
        agent_id: str,
        legacy_allowed_names: list[str] | None,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "POST",
            "/database-interactions/catalog",
            payload={
                "agent_id": agent_id,
                "legacy_allowed_names": legacy_allowed_names,
            },
        )

    async def list_runtime(
        self,
        *,
        agent_id: str,
        session_id: str,
        legacy_allowed_names: list[str] | None,
    ) -> list[dict[str, Any]]:
        return await self._request(
            "POST",
            "/database-interactions/runtime",
            payload={
                "agent_id": agent_id,
                "agentscope_session_id": session_id,
                "legacy_allowed_names": legacy_allowed_names,
            },
        )

    async def execute_interaction(
        self,
        *,
        session_id: str,
        actor_agent_id: str,
        platform_agent_id: str,
        interaction_key: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one assigned interaction through the trusted gateway."""
        result = await self._request(
            "POST",
            "/database-interactions/execute",
            payload={
                "agentscope_session_id": session_id,
                "actor_agent_id": actor_agent_id,
                "platform_agent_id": platform_agent_id,
                "interaction_key": interaction_key,
                "access_mode": "agent",
                "arguments": arguments,
            },
            unwrap_data=False,
            timeout=max(self._timeout, 60.0),
        )
        if not isinstance(result, dict):
            raise DatabaseInteractionGatewayError(
                502,
                "工程平台数据库交互返回了无效结果。",
            )
        return result

    async def update_assignments(
        self,
        agent_id: str,
        interaction_ids: list[int],
    ) -> list[dict[str, Any]]:
        return await self._request(
            "PUT",
            f"/database-interactions/assignments/{agent_id}",
            payload={"interaction_ids": interaction_ids},
        )

    async def delete_assignments(self, agent_id: str) -> None:
        await self._request(
            "DELETE",
            f"/database-interactions/assignments/{agent_id}",
            expect_data=False,
        )

    async def list_tables(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/database-interactions/tables")

    async def list_policies(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/database-interactions/policies")

    async def create_interaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/database-interactions/interactions",
            payload=payload,
        )

    async def update_interaction(
        self,
        interaction_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"/database-interactions/interactions/{interaction_id}/table",
            payload=payload,
        )

    async def delete_interaction(self, interaction_id: int) -> None:
        await self._request(
            "DELETE",
            f"/database-interactions/interactions/{interaction_id}",
            expect_data=False,
        )
