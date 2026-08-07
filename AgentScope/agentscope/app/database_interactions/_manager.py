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
        expect_data: bool = True,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json=payload,
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
        return body.get("data", body)

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
