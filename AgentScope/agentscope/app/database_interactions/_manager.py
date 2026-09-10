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

    async def resolve_memory_scope(self, session_id: str) -> dict[str, Any]:
        return await self._request("GET", "/agent-tools/memory-scope",
                                   params={"agentscope_session_id": session_id}, timeout=5)

    async def memory_identity_catalog(self) -> dict[str, Any]:
        return await self._request("GET", "/agent-tools/memory-catalog", timeout=5)

    async def business_learning_sources(self, after_id: int = 0, limit: int = 50):
        return await self._request('GET', '/agent-tools/business-learning/sources',
                                   params={'after_id': after_id, 'limit': limit})

    async def business_learning_validate(self, snapshot: dict):
        return await self._request('POST', '/agent-tools/business-learning/validate',
                                   payload={'snapshot': snapshot})

    async def group_learning_channels(self, after_channel: int = 0):
        return await self._request('GET', '/agent-tools/group-learning/channels', params={'after_channel': after_channel})

    async def group_learning_source(self, channel_id: int, after_revision: int, limit: int = 50):
        return await self._request('GET', f'/agent-tools/group-learning/channels/{channel_id}',
            params={'after_revision': after_revision, 'limit': limit})

    async def group_learning_validate(self, snapshot: dict):
        return await self._request('POST', '/agent-tools/group-learning/validate', payload={'snapshot': snapshot})

    async def group_learning_changes(self, channel_id: int, after_revision: int):
        return await self._request('GET', f'/agent-tools/group-learning/channels/{channel_id}/changes', params={'after_revision': after_revision})

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

    async def resolve_knowledge_scope(
        self, *, session_id: str, actor_agent_id: str,
    ) -> dict[str, Any]:
        """Fetch current platform membership and document permissions."""
        return await self._request(
            "GET", "/agent-tools/knowledge-scope",
            params={"agentscope_session_id": session_id, "actor_agent_id": actor_agent_id},
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

    async def preview_interaction(
        self, *, session_id: str, actor_agent_id: str, platform_agent_id: str,
        interaction_key: str, arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = await self._request("POST", "/database-interactions/preview", payload={
            "agentscope_session_id": session_id, "actor_agent_id": actor_agent_id,
            "platform_agent_id": platform_agent_id, "interaction_key": interaction_key,
            "arguments": arguments,
        })
        if not isinstance(result, dict):
            raise DatabaseInteractionGatewayError(502, "业务变更预览返回了无效结果。")
        return result

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
