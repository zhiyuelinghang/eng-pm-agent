"""Server-side gateway client for the local AgentScope runtime."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from .config import Settings
from .agent_pending_input import pending_input_message


class AgentScopeGatewayError(RuntimeError):
    """A stable exception raised for AgentScope transport/API failures."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class AgentScopeReply:
    """Terminal or parked result of a single AgentScope chat turn."""

    status: str
    content: str
    message_id: str | None
    raw_message: dict[str, Any] | None
    raw_messages: list[dict[str, Any]] = field(default_factory=list)
    projected: bool = False


@dataclass(slots=True)
class AgentScopeConfirmationSubmission:
    """AgentScope acknowledgement for one submitted HITL decision."""

    existing_ids: set[str]
    routed_session_id: str


@dataclass(slots=True)
class AgentScopeRunCompletion:
    """Thread-safe bridge from the AgentScope SSE relay to ``chat``.

    The platform opens one event stream and one blocking chat worker.  The
    stream resolves this object from AgentScope's durable ``run_completed``
    event, allowing the worker to return without repeatedly polling message,
    status, and team endpoints.  A slow fallback probe remains available for
    browser disconnects or old AgentScope processes during rolling restarts.
    """

    _event: threading.Event = field(default_factory=threading.Event)
    _reply: AgentScopeReply | None = None
    _error: AgentScopeGatewayError | None = None

    def resolve(self, reply: AgentScopeReply) -> None:
        if self._event.is_set():
            return
        self._reply = reply
        self._event.set()

    def reject(self, error: AgentScopeGatewayError) -> None:
        if self._event.is_set():
            return
        self._error = error
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)

    def is_set(self) -> bool:
        return self._event.is_set()

    def result(self) -> AgentScopeReply:
        if self._error is not None:
            raise self._error
        if self._reply is None:
            raise AgentScopeGatewayError(
                "AgentScope 已发出完成信号，但没有返回运行结果。",
                status_code=502,
            )
        return self._reply


@dataclass(slots=True)
class AgentScopeTeamState:
    """Persistent collaboration state for one leader session."""

    team_exists: bool = False
    members_pending: bool = False
    leader_summary_pending: bool = False

    @property
    def pending(self) -> bool:
        return self.members_pending or self.leader_summary_pending


class AgentScopeClient:
    """Minimal backend-only client for catalogue and chat operations."""

    _CATALOG_CACHE_SECONDS = 15.0

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.agentscope_base_url.rstrip("/")
        self._service_token = settings.agentscope_service_token.strip()
        if not self._service_token:
            raise ValueError(
                "AGENTSCOPE_SERVICE_TOKEN 未配置，平台后端不能连接 AgentScope。",
            )
        # This timeout protects short control-plane HTTP requests only.
        # Agent turns themselves deliberately have no wall-clock deadline:
        # complex tool loops and multi-agent work may legitimately run for
        # much longer than one request timeout.
        self._request_timeout = settings.agentscope_request_timeout_seconds
        self._poll_interval = settings.agentscope_poll_interval_seconds
        self._catalog_cache: dict[str, Any] | None = None
        self._catalog_cached_at = 0.0
        self._session_sync_payloads: dict[tuple[str, str], str] = {}
        self._http_client: httpx.Client | None = None
        self._http_client_lock = threading.Lock()

    def _transport(self) -> httpx.Client:
        # The gateway is shared across request threads. Reuse the connection
        # pool and TLS context instead of rebuilding them for every local call.
        with self._http_client_lock:
            if self._http_client is None:
                self._http_client = httpx.Client()
            return self._http_client

    def close(self) -> None:
        with self._http_client_lock:
            if self._http_client is not None:
                self._http_client.close()
                self._http_client = None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._service_token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        wait_for_response: bool = False,
        not_found_ok: bool = False,
    ) -> Any:
        timeout: float | httpx.Timeout
        if wait_for_response:
            timeout = httpx.Timeout(
                connect=min(self._request_timeout, 30.0),
                read=None,
                write=min(self._request_timeout, 30.0),
                pool=min(self._request_timeout, 30.0),
            )
        else:
            timeout = min(self._request_timeout, 30.0)
        try:
            response = self._transport().request(
                method,
                f"{self._base_url}{path}",
                headers=self.headers,
                params=params,
                json=json,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise AgentScopeGatewayError(
                f"无法连接 AgentScope：{exc}",
                status_code=503,
            ) from exc
        if response.status_code == 404 and not_found_ok:
            return None
        if response.is_error:
            try:
                payload = response.json()
                detail = payload.get("detail", payload)
            except ValueError:
                detail = response.text or response.reason_phrase
            raise AgentScopeGatewayError(
                f"AgentScope 请求失败（{response.status_code}）：{detail}",
                status_code=502 if response.status_code >= 500 else 409,
            )
        if response.status_code == 204:
            return None
        return response.json()

    def _request_multipart(
        self,
        path: str,
        *,
        params: dict[str, Any],
        data: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
    ) -> Any:
        try:
            response = self._transport().post(
                f"{self._base_url}{path}",
                headers=self.headers,
                params=params,
                data=data,
                files=files,
                timeout=max(self._request_timeout, 120.0),
            )
        except httpx.HTTPError as exc:
            raise AgentScopeGatewayError(
                f"无法连接 AgentScope：{exc}",
                status_code=503,
            ) from exc
        if response.is_error:
            try:
                detail = response.json().get("detail", response.json())
            except ValueError:
                detail = response.text or response.reason_phrase
            raise AgentScopeGatewayError(
                f"AgentScope 请求失败（{response.status_code}）：{detail}",
                status_code=502 if response.status_code >= 500 else 409,
            )
        return response.json()

    def _request_bytes(
        self,
        path: str,
        *,
        params: dict[str, Any],
    ) -> tuple[bytes, str, str]:
        try:
            response = self._transport().get(
                f"{self._base_url}{path}",
                headers=self.headers,
                params=params,
                timeout=max(self._request_timeout, 120.0),
            )
        except httpx.HTTPError as exc:
            raise AgentScopeGatewayError(
                f"无法连接 AgentScope：{exc}",
                status_code=503,
            ) from exc
        if response.is_error:
            try:
                detail = response.json().get("detail", response.json())
            except ValueError:
                detail = response.text or response.reason_phrase
            raise AgentScopeGatewayError(
                f"AgentScope 请求失败（{response.status_code}）：{detail}",
                status_code=502 if response.status_code >= 500 else 409,
            )
        return (
            response.content,
            response.headers.get("content-type", "application/octet-stream"),
            response.headers.get("content-disposition", ""),
        )

    @asynccontextmanager
    async def event_stream(
        self,
        session_id: str,
        agent_id: str,
    ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        """Open AgentScope's authenticated session-event SSE stream.

        The browser must never connect to AgentScope directly because doing
        so would expose the platform service token and bypass platform project
        authorization.  The platform API opens this stream server-side and
        relays only the authorized conversation to its caller.
        """
        timeout = httpx.Timeout(
            connect=min(self._request_timeout, 30.0),
            read=None,
            write=min(self._request_timeout, 30.0),
            pool=min(self._request_timeout, 30.0),
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "GET",
                    f"{self._base_url}/sessions/{session_id}/stream",
                    headers=self.headers,
                    params={"agent_id": agent_id},
                ) as response:
                    if response.is_error:
                        raw = (await response.aread()).decode(
                            response.encoding or "utf-8",
                            errors="replace",
                        )
                        try:
                            payload = json.loads(raw)
                            detail = payload.get("detail", payload)
                        except (ValueError, AttributeError):
                            detail = raw or response.reason_phrase
                        raise AgentScopeGatewayError(
                            "AgentScope 事件流请求失败"
                            f"（{response.status_code}）：{detail}",
                            status_code=(
                                502 if response.status_code >= 500 else 409
                            ),
                        )
                    yield self._iter_sse_events(response)
        except AgentScopeGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise AgentScopeGatewayError(
                f"无法连接 AgentScope 事件流：{exc}",
                status_code=503,
            ) from exc

    @staticmethod
    async def _iter_sse_events(
        response: httpx.Response,
    ) -> AsyncIterator[dict[str, Any]]:
        """Parse complete JSON payloads from an AgentScope SSE response."""
        data_lines: list[str] = []
        async for line in response.aiter_lines():
            if line == "":
                if not data_lines:
                    continue
                raw = "\n".join(data_lines)
                data_lines.clear()
                try:
                    payload = json.loads(raw)
                except ValueError as exc:
                    raise AgentScopeGatewayError(
                        f"AgentScope 返回了无法解析的事件：{raw[:500]}",
                    ) from exc
                if isinstance(payload, dict):
                    yield payload
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            raw = "\n".join(data_lines)
            try:
                payload = json.loads(raw)
            except ValueError as exc:
                raise AgentScopeGatewayError(
                    f"AgentScope 返回了无法解析的事件：{raw[:500]}",
                ) from exc
            if isinstance(payload, dict):
                yield payload

    def get_catalog(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return the agent catalogue without repeating the same control call.

        Agent definitions change far less often than chat turns. A short cache
        keeps ordinary messages off the control plane while still making admin
        changes visible within a few seconds.
        """
        now = time.monotonic()
        if (
            not force_refresh
            and self._catalog_cache is not None
            and now - self._catalog_cached_at < self._CATALOG_CACHE_SECONDS
        ):
            return self._catalog_cache
        catalogue = self._request("GET", "/agent/platform/catalog")
        if not isinstance(catalogue, dict):
            raise AgentScopeGatewayError("AgentScope 智能体目录返回格式无效。")
        self._catalog_cache = catalogue
        self._catalog_cached_at = now
        return catalogue

    @staticmethod
    def _weknora_scope_params(agent_id: str) -> dict[str, str]:
        return {"weknora_agent_id": agent_id}

    def list_weknora_knowledge_bases(self, agent_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            "/agent/platform/weknora/knowledge-bases",
            params=self._weknora_scope_params(agent_id),
        )

    def get_weknora_folder_tree(
        self,
        agent_id: str,
        knowledge_base_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/knowledge/folders",
            params=self._weknora_scope_params(agent_id),
        )

    def list_weknora_knowledge(
        self,
        agent_id: str,
        knowledge_base_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        folder_path: str | None = None,
        folder_recursive: bool = False,
        keyword: str = "",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            **self._weknora_scope_params(agent_id),
            "page": page,
            "page_size": page_size,
            "folder_recursive": str(folder_recursive).lower(),
        }
        if folder_path is not None:
            params["folder_path"] = folder_path
        if keyword:
            params["keyword"] = keyword
        return self._request(
            "GET",
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/knowledge",
            params=params,
        )

    def search_weknora_knowledge(
        self,
        agent_id: str,
        knowledge_base_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/search",
            params=self._weknora_scope_params(agent_id),
            json=payload,
        )

    def update_weknora_folder(
        self,
        agent_id: str,
        knowledge_base_id: str,
        *,
        source_path: str,
        target_path: str,
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/knowledge/folders",
            params=self._weknora_scope_params(agent_id),
            json={"source_path": source_path, "target_path": target_path},
        )

    def create_weknora_folder(
        self,
        agent_id: str,
        knowledge_base_id: str,
        *,
        folder_path: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/knowledge/folders",
            params=self._weknora_scope_params(agent_id),
            json={"folder_path": folder_path},
        )

    def delete_weknora_folder(
        self,
        agent_id: str,
        knowledge_base_id: str,
        *,
        folder_path: str,
        recursive: bool = False,
    ) -> None:
        self._request(
            "DELETE",
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/knowledge/folders",
            params={
                **self._weknora_scope_params(agent_id),
                "folder_path": folder_path,
                "recursive": str(recursive).lower(),
            },
            wait_for_response=recursive,
        )

    def move_weknora_knowledge(
        self,
        agent_id: str,
        knowledge_base_id: str,
        *,
        knowledge_ids: list[str],
        folder_path: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/knowledge/move",
            params=self._weknora_scope_params(agent_id),
            json={
                "knowledge_ids": knowledge_ids,
                "folder_path": folder_path,
            },
        )

    def create_weknora_url_knowledge(
        self,
        agent_id: str,
        knowledge_base_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/knowledge/url",
            params=self._weknora_scope_params(agent_id),
            json=payload,
        )

    def ask_weknora_agent(
        self,
        agent_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/platform/weknora/agent-query",
            json={"weknora_agent_id": agent_id, **payload},
            wait_for_response=True,
        )

    @asynccontextmanager
    async def weknora_agent_stream(
        self,
        agent_id: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        """Open the authorized AgentScope-to-WeKnora answer stream."""

        timeout = httpx.Timeout(
            connect=min(self._request_timeout, 30.0),
            read=None,
            write=min(self._request_timeout, 30.0),
            pool=min(self._request_timeout, 30.0),
        )
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/agent/platform/weknora/"
                    "agent-query/stream",
                    headers={
                        **self.headers,
                        "Accept": "text/event-stream",
                    },
                    json={"weknora_agent_id": agent_id, **payload},
                ) as response:
                    if response.is_error:
                        raw = (await response.aread()).decode(
                            response.encoding or "utf-8",
                            errors="replace",
                        )
                        try:
                            parsed = json.loads(raw)
                            detail = parsed.get("detail", parsed)
                        except (ValueError, AttributeError):
                            detail = raw or response.reason_phrase
                        raise AgentScopeGatewayError(
                            "AgentScope WeKnora 事件流请求失败"
                            f"（{response.status_code}）：{detail}",
                            status_code=(
                                502 if response.status_code >= 500 else 409
                            ),
                        )
                    yield self._iter_sse_events(response)
        except AgentScopeGatewayError:
            raise
        except httpx.HTTPError as exc:
            raise AgentScopeGatewayError(
                f"无法连接 AgentScope WeKnora 事件流：{exc}",
                status_code=503,
            ) from exc

    def create_weknora_agent_session(
        self,
        agent_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/platform/weknora/sessions",
            json={"weknora_agent_id": agent_id},
        )

    def stop_weknora_agent_session(
        self,
        agent_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/agent/platform/weknora/sessions/"
            f"{quote(session_id, safe='')}/stop",
            json={"weknora_agent_id": agent_id},
        )

    def upload_weknora_knowledge(
        self,
        agent_id: str,
        knowledge_base_id: str,
        *,
        filename: str,
        content: bytes,
        content_type: str,
        folder_path: str,
        enable_multimodel: bool = True,
    ) -> dict[str, Any]:
        return self._request_multipart(
            "/agent/platform/weknora/knowledge-bases/"
            f"{quote(knowledge_base_id, safe='')}/knowledge/file",
            params=self._weknora_scope_params(agent_id),
            data={
                "enable_multimodel": str(enable_multimodel).lower(),
                "folder_path": folder_path,
            },
            files={"file": (filename, content, content_type)},
        )

    def delete_weknora_knowledge(
        self,
        agent_id: str,
        knowledge_id: str,
    ) -> None:
        self._request(
            "DELETE",
            f"/agent/platform/weknora/knowledge/{quote(knowledge_id, safe='')}",
            params=self._weknora_scope_params(agent_id),
        )

    def get_weknora_knowledge(
        self,
        agent_id: str,
        knowledge_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/agent/platform/weknora/knowledge/{quote(knowledge_id, safe='')}",
            params=self._weknora_scope_params(agent_id),
        )

    def get_weknora_knowledge_content(
        self,
        agent_id: str,
        knowledge_id: str,
        operation: str,
    ) -> tuple[bytes, str, str]:
        if operation not in {"download", "preview"}:
            raise ValueError("operation must be download or preview")
        return self._request_bytes(
            "/agent/platform/weknora/knowledge/"
            f"{quote(knowledge_id, safe='')}/{operation}",
            params=self._weknora_scope_params(agent_id),
        )

    def get_weknora_resource_content(
        self,
        agent_id: str,
        resource_id: str,
    ) -> tuple[bytes, str, str]:
        return self._request_bytes(
            "/agent/platform/weknora/resources/"
            f"{quote(resource_id, safe='')}",
            params=self._weknora_scope_params(agent_id),
        )

    def validate_project_initialization(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the active platform validation MCP without an LLM turn."""
        result = self._request(
            "POST",
            "/mcp-registry/platform/project-initialization-validation",
            json={"payload": payload},
        )
        if not isinstance(result, dict):
            raise AgentScopeGatewayError("项目初始化核验 MCP 返回格式无效。")
        return result

    def create_session(
        self,
        *,
        agent: dict[str, Any],
        workspace_id: str,
        name: str,
        platform_context: dict[str, Any],
    ) -> str:
        if not agent.get("model_ready"):
            raise AgentScopeGatewayError(
                f"智能体「{agent.get('name', agent.get('id'))}」尚未配置固定模型，"
                "不能由工程平台直接运行。",
                status_code=409,
            )
        body: dict[str, Any] = {
            "agent_id": agent["id"],
            "permission_mode": str(agent.get("permission_mode") or "auto"),
            "workspace_id": workspace_id,
            "name": name,
            "knowledge_config": agent.get("knowledge_config"),
            "platform_context": platform_context,
        }
        created = self._request("POST", "/sessions/", json=body)
        session_id = str(created["session_id"])
        if created.get("configuration_applied") is True:
            policy = {
                key: body[key]
                for key in ("permission_mode", "knowledge_config", "platform_context", "name")
            }
            self._session_sync_payloads[(str(agent["id"]), session_id)] = (
                self._session_policy_signature(policy)
            )
            return session_id
        # Older runtimes do not apply permission_mode during creation.
        self.sync_session(
            agent=agent,
            session_id=session_id,
            platform_context=platform_context,
            name=name,
        )
        return session_id

    @staticmethod
    def _session_policy_signature(body: dict[str, Any]) -> str:
        return json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
        )

    def sync_session(
        self,
        *,
        agent: dict[str, Any],
        session_id: str,
        platform_context: dict[str, Any],
        name: str | None = None,
    ) -> bool:
        """Apply runtime policy only when its effective payload changed.

        The platform rebuilds authorization context for every turn. Comparing
        the complete payload preserves that behavior while avoiding an
        identical network PATCH before every ordinary message.
        """
        permission_mode = str(agent.get("permission_mode") or "auto")
        body: dict[str, Any] = {
            "permission_mode": permission_mode,
            "knowledge_config": agent.get("knowledge_config"),
            "platform_context": platform_context,
        }
        if name is not None:
            body["name"] = name
        cache_key = (str(agent["id"]), session_id)
        payload_signature = self._session_policy_signature(body)
        if self._session_sync_payloads.get(cache_key) == payload_signature:
            return False
        self._request(
            "PATCH",
            f"/sessions/{session_id}",
            params={"agent_id": str(agent["id"])},
            json=body,
        )
        self._session_sync_payloads[cache_key] = payload_signature
        return True

    def delete_session(self, session_id: str, agent_id: str) -> None:
        """Delete one AgentScope session and all runtime-owned history."""
        try:
            self._request(
                "DELETE",
                f"/sessions/{quote(session_id, safe='')}",
                params={"agent_id": agent_id},
                not_found_ok=True,
            )
        finally:
            self._session_sync_payloads.pop((str(agent_id), session_id), None)

    def list_messages(
        self,
        session_id: str,
        agent_id: str,
        *,
        before: str | None = None,
        limit: int = 200,
        wait_for_response: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "agent_id": agent_id,
            "limit": str(limit),
        }
        if before:
            params["before"] = before
        return self._request(
            "GET",
            f"/sessions/{session_id}/messages",
            params=params,
            wait_for_response=wait_for_response,
        )

    def list_all_messages(
        self,
        session_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        """Read the complete AgentScope history in chronological order."""
        page = self.list_messages(session_id, agent_id)
        messages = list(page.get("messages", []))
        is_running = bool(page.get("is_running"))
        while page.get("has_more") and messages:
            page = self.list_messages(
                session_id,
                agent_id,
                before=str(messages[0]["id"]),
            )
            older = list(page.get("messages", []))
            messages = [*older, *messages]
            is_running = is_running or bool(page.get("is_running"))
        return {
            "messages": messages,
            "is_running": is_running,
            "has_more": False,
        }

    def update_message_metadata(
        self,
        session_id: str,
        agent_id: str,
        message_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge presentation metadata into the AgentScope source message."""
        return self._request(
            "PATCH",
            f"/sessions/{session_id}/messages/{message_id}/metadata",
            params={"agent_id": agent_id},
            json={"metadata": metadata},
        )

    def session_status(
        self,
        session_id: str,
        agent_id: str,
        *,
        wait_for_response: bool = False,
    ) -> str:
        payload = self._request(
            "GET",
            f"/sessions/{session_id}/status",
            params={"agent_id": agent_id},
            wait_for_response=wait_for_response,
        )
        return str(payload["status"])

    def session_team_state(
        self,
        session_id: str,
        agent_id: str,
        *,
        wait_for_response: bool = False,
    ) -> tuple[bool, bool]:
        """Return ``(team_exists, member_work_is_pending)``.

        A leader may legitimately retain a team after answering. Team
        existence alone therefore cannot be used as a completion signal.
        Member sessions are checked individually so the gateway waits for
        actual collaboration work, not for an optional ``TeamDelete`` call.
        """
        state = self.session_team_state_detail(
            session_id,
            agent_id,
            wait_for_response=wait_for_response,
        )
        return state.team_exists, state.pending

    def session_team_work_pending(
        self,
        session_id: str,
        agent_id: str,
    ) -> bool:
        """Return whether member work or the leader's final summary is due."""
        return self.session_team_state_detail(
            session_id,
            agent_id,
        ).pending

    def session_team_state_detail(
        self,
        session_id: str,
        agent_id: str,
        *,
        wait_for_response: bool = False,
    ) -> AgentScopeTeamState:
        """Read durable member and leader-summary revisions."""
        payload = self._request(
            "GET",
            "/sessions/",
            params={"agent_id": agent_id},
            wait_for_response=wait_for_response,
        )
        for view in payload.get("sessions", []):
            session = view.get("session") or {}
            if str(session.get("id")) == session_id:
                team = view.get("team")
                if not session.get("team_id") or not team:
                    return AgentScopeTeamState()
                team_record = team.get("team") or {}
                team_data = team_record.get("data") or {}
                members_pending = False
                for member in team.get("members") or []:
                    assigned_revision = int(
                        member.get("work_revision") or 0,
                    )
                    settled_revision = int(
                        member.get("settled_revision") or 0,
                    )
                    if settled_revision < assigned_revision:
                        members_pending = True
                work_revision = int(team_data.get("work_revision") or 0)
                leader_completed_revision = int(
                    team_data.get("leader_completed_revision") or 0,
                )
                return AgentScopeTeamState(
                    team_exists=True,
                    members_pending=members_pending,
                    leader_summary_pending=(
                        leader_completed_revision < work_revision
                    ),
                )
        raise AgentScopeGatewayError(
            f"AgentScope 会话 {session_id} 不存在或不可见。",
            status_code=409,
        )

    @staticmethod
    def _message_text(message: dict[str, Any] | None) -> str:
        if not message:
            return ""
        blocks = message.get("content") or []
        finished_reason = str(message.get("finished_reason") or "")
        if finished_reason in {"interrupted", "error"}:
            # Interrupted/error replies do not have a guaranteed final-answer
            # segment. Preserve every user-visible text block produced before
            # execution stopped.
            parts = [
                str(block["text"])
                for block in blocks
                if block.get("type") == "text" and block.get("text")
            ]
            error = message.get("error")
            if error:
                error_text = (
                    str(error.get("message") or error)
                    if isinstance(error, dict)
                    else str(error)
                )
                if error_text and error_text not in parts:
                    parts.append(error_text)
            return "\n".join(parts).strip()
        last_non_text_index = max(
            (
                index
                for index, block in enumerate(blocks)
                if block.get("type") != "text"
            ),
            default=-1,
        )
        final_parts = [
            str(block["text"])
            for index, block in enumerate(blocks)
            if index > last_non_text_index
            and block.get("type") == "text"
            and block.get("text")
        ]
        # Some providers may end a reply with a non-text carrier block. In
        # that case retain the available text instead of returning blank.
        parts = final_parts or [
            str(block["text"])
            for block in blocks
            if block.get("type") == "text" and block.get("text")
        ]
        error = message.get("error")
        if error and not parts:
            parts.append(str(error.get("message") or error))
        return "\n".join(parts).strip()

    @staticmethod
    def _terminal_reply_status(message: dict[str, Any]) -> str:
        finished_reason = str(message.get("finished_reason") or "")
        if message.get("error") or finished_reason == "error":
            return "error"
        if finished_reason == "interrupted":
            return "interrupted"
        if finished_reason == "exceed_max_iters":
            return "exceed_max_iters"
        return "completed"

    def trigger_chat(
        self,
        *,
        agent_id: str,
        session_id: str,
        content: str,
        sender_name: str,
        metadata: dict[str, Any],
        user_message_id: str | None = None,
        content_blocks: list[dict[str, Any]] | None = None,
    ) -> str:
        """Start one AgentScope run and return its correlated input id."""
        resolved_user_message_id = user_message_id or uuid4().hex
        self._request(
            "POST",
            "/chat/",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "input": {
                    "id": resolved_user_message_id,
                    "name": sender_name,
                    "role": "user",
                    "content": [
                        {"type": "text", "text": content},
                        *(content_blocks or []),
                    ],
                    "metadata": metadata,
                },
            },
            wait_for_response=True,
        )
        return resolved_user_message_id

    def chat(
        self,
        *,
        agent_id: str,
        session_id: str,
        content: str,
        sender_name: str,
        metadata: dict[str, Any],
        user_message_id: str | None = None,
        content_blocks: list[dict[str, Any]] | None = None,
        completion: AgentScopeRunCompletion | None = None,
    ) -> AgentScopeReply:
        resolved_user_message_id = self.trigger_chat(
            agent_id=agent_id,
            session_id=session_id,
            content=content,
            sender_name=sender_name,
            metadata=metadata,
            user_message_id=user_message_id,
            content_blocks=content_blocks,
        )

        if completion is not None:
            # Normally the already-open AgentScope event stream resolves this
            # immediately after durable persistence.  Probe slowly only as a
            # recovery path when that stream disappears (for example, the
            # browser navigates away mid-turn or an old AgentScope process is
            # still running during a rolling restart).  This is not a wall
            # clock deadline; long tool and multi-agent runs remain unlimited.
            fallback_probe_seconds = max(5.0, self._poll_interval * 10)
            while not completion.wait(fallback_probe_seconds):
                status = self.session_status(
                    session_id,
                    agent_id,
                    wait_for_response=True,
                )
                if status == "running":
                    continue
                if status in {
                    "awaiting_permission",
                    "awaiting_external_result",
                }:
                    break
                if status == "idle":
                    _, team_work_pending = self.session_team_state(
                        session_id,
                        agent_id,
                        wait_for_response=True,
                    )
                    if team_work_pending:
                        continue
                    break
            if completion.is_set():
                return completion.result()

        last_assistant: dict[str, Any] | None = None
        new_assistants: list[dict[str, Any]] = []
        collaboration_waiting_ids: set[str] = set()
        turn_input_observed = False
        idle_without_reply_polls = 0
        idle_without_reply_limit = max(
            3,
            int(3.0 / max(0.1, self._poll_interval)) + 1,
        )
        while True:
            status = self.session_status(
                session_id,
                agent_id,
                wait_for_response=True,
            )
            if status == "running":
                idle_without_reply_polls = 0
                time.sleep(max(0.1, self._poll_interval))
                continue

            messages_payload = self.list_messages(
                session_id,
                agent_id,
                wait_for_response=True,
            )
            messages = messages_payload.get("messages", [])
            boundary_index = next(
                (
                    index
                    for index, message in enumerate(messages)
                    if str(message.get("id") or "")
                    == resolved_user_message_id
                ),
                -1,
            )
            if boundary_index >= 0:
                turn_input_observed = True
                turn_messages = messages[boundary_index + 1 :]
            elif turn_input_observed:
                # The endpoint returns only the newest page. A very long turn
                # can eventually push its input beyond that page; at that
                # point every newly visible assistant message still belongs
                # to the current turn.
                turn_messages = messages
            else:
                turn_messages = []
            new_assistants = [
                message
                for message in turn_messages
                if message.get("role") == "assistant"
            ]
            if new_assistants:
                last_assistant = new_assistants[-1]

            projected = pending_input_message(messages_payload, last_assistant)
            if projected:
                return AgentScopeReply(
                    status="awaiting_permission", content="协同智能体需要人工确认后才能继续。",
                    message_id=projected["id"], raw_message=projected,
                    raw_messages=[*new_assistants[:-1], projected],
                )

            runtime_running = bool(messages_payload.get("is_running"))
            if runtime_running:
                idle_without_reply_polls = 0
                time.sleep(max(0.1, self._poll_interval))
                continue
            if status == "idle" and not new_assistants:
                idle_without_reply_polls += 1
                if idle_without_reply_polls >= idle_without_reply_limit:
                    _, team_work_pending = self.session_team_state(
                        session_id,
                        agent_id,
                        wait_for_response=True,
                    )
                    if team_work_pending:
                        idle_without_reply_polls = 0
                    else:
                        raise AgentScopeGatewayError(
                            "AgentScope 本次运行已结束，但未生成任何智能体回复。"
                            "请查看 AgentScope 服务日志。",
                            status_code=502,
                        )
            else:
                idle_without_reply_polls = 0
            if status in {
                "awaiting_permission",
                "awaiting_external_result",
            }:
                return AgentScopeReply(
                    status=status,
                    content=self._message_text(last_assistant)
                    or (
                        "智能体需要人工确认后才能继续。"
                        if status == "awaiting_permission"
                        else "智能体正在等待外部工具返回结果。"
                    ),
                    message_id=last_assistant.get("id")
                    if last_assistant
                    else None,
                    raw_message=last_assistant,
                    raw_messages=new_assistants,
                )
            if (
                status == "idle"
                and last_assistant
                and last_assistant.get("finished_at") is not None
            ):
                # AgentInvite is asynchronous: the leader can finish an
                # interim "waiting for member" reply while a team worker is
                # still running, then auto-resume when the worker responds.
                # Do not return that interim reply to the platform.
                _, team_work_pending = self.session_team_state(
                    session_id,
                    agent_id,
                    wait_for_response=True,
                )
                if team_work_pending:
                    if last_assistant.get("id"):
                        collaboration_waiting_ids.add(
                            str(last_assistant["id"]),
                        )
                else:
                    for message in new_assistants:
                        if (
                            str(message.get("id") or "")
                            in collaboration_waiting_ids
                        ):
                            message[
                                "platform_collaboration_status"
                            ] = "continued"
                    return AgentScopeReply(
                        status=self._terminal_reply_status(last_assistant),
                        content=self._message_text(last_assistant)
                        or "智能体已完成处理，但未返回文本内容。",
                        message_id=last_assistant.get("id"),
                        raw_message=last_assistant,
                        raw_messages=new_assistants,
                    )
            time.sleep(max(0.1, self._poll_interval))

    def interrupt(self, *, agent_id: str, session_id: str) -> dict[str, Any]:
        """Request a safe interrupt of a running or parked AgentScope turn."""
        return self._request(
            "POST",
            f"/sessions/{session_id}/interrupt",
            params={"agent_id": agent_id},
        )

    def confirm_tool_call(
        self,
        *,
        agent_id: str,
        session_id: str,
        reply_id: str,
        tool_call: dict[str, Any],
        confirmed: bool,
        rules: list[dict[str, Any]] | None = None,
        wait_for_collaboration: bool = False,
    ) -> AgentScopeReply:
        """Resume a parked reply after a platform user's decision."""
        submission = self.submit_tool_confirmation(
            agent_id=agent_id,
            session_id=session_id,
            reply_id=reply_id,
            tool_call=tool_call,
            confirmed=confirmed,
            rules=rules,
        )
        return self.wait_for_tool_confirmation(
            agent_id=agent_id,
            session_id=session_id,
            reply_id=reply_id,
            tool_call=tool_call,
            submission=submission,
            wait_for_collaboration=wait_for_collaboration,
        )

    def submit_tool_confirmation(
        self,
        *,
        agent_id: str,
        session_id: str,
        reply_id: str,
        tool_call: dict[str, Any],
        confirmed: bool,
        rules: list[dict[str, Any]] | None = None,
    ) -> AgentScopeConfirmationSubmission:
        """Validate and enqueue one HITL decision without waiting for output."""
        before = self.list_messages(
            session_id,
            agent_id,
            wait_for_response=True,
        )
        matching_reply = next(
            (
                message
                for message in before.get("messages", [])
                if str(message.get("id") or "") == reply_id
            ),
            None,
        )
        if matching_reply is not None:
            pending_ids = {
                str(block.get("id") or "")
                for block in matching_reply.get("content", [])
                if block.get("type") == "tool_call"
                and block.get("state") == "asking"
            }
            if str(tool_call.get("id") or "") not in pending_ids:
                raise AgentScopeGatewayError(
                    "该工具确认已经处理或所属回复已经结束，请刷新后查看最新状态。",
                    status_code=409,
                )
        current_calls = [
            block for block in (matching_reply or {}).get("content", [])
            if block.get("type") == "tool_call" and block.get("state") == "asking"
        ]
        for entry in before.get("subagent_hitl", []):
            if entry.get("reply_id") == reply_id:
                current_calls.extend((entry.get("event") or {}).get("tool_calls", []))
        for current in current_calls:
            if str(current.get("id")) == str(tool_call.get("id")) and (
                int(current.get("confirmation_revision") or 0)
                != int(tool_call.get("confirmation_revision") or 0)
            ):
                raise AgentScopeGatewayError("确认内容已更新，请刷新并核对最新变更。", status_code=409)
        existing_ids = {
            str(message.get("id"))
            for message in before.get("messages", [])
            if message.get("id") and str(message.get("id")) != reply_id
        }
        trigger = self._request(
            "POST",
            "/chat/",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "input": {
                    "type": "USER_CONFIRM_RESULT",
                    "id": uuid4().hex,
                    "created_at": datetime.now(UTC).isoformat(),
                    "reply_id": reply_id,
                    "confirm_results": [
                        {
                            "confirmed": confirmed,
                            "tool_call": tool_call,
                            "rules": rules,
                        },
                    ],
                },
            },
            wait_for_response=True,
        )
        return AgentScopeConfirmationSubmission(
            existing_ids=existing_ids,
            routed_session_id=str(
                trigger.get("session_id") or session_id,
            ),
        )

    def wait_for_tool_confirmation(
        self,
        *,
        agent_id: str,
        session_id: str,
        reply_id: str,
        tool_call: dict[str, Any],
        submission: AgentScopeConfirmationSubmission,
        wait_for_collaboration: bool = False,
    ) -> AgentScopeReply:
        """Wait until a submitted HITL decision parks again or completes."""
        if submission.routed_session_id != session_id and not wait_for_collaboration:
            # The confirmation belongs to a team member and AgentScope has
            # routed it through the leader session to that worker. The
            # original platform SSE turn remains open and will receive the
            # worker result plus the leader's resumed final answer.
            return AgentScopeReply(
                status="running",
                content="协同智能体已收到确认结果，正在继续执行。",
                message_id=reply_id,
                raw_message=None,
                projected=True,
            )

        existing_ids = submission.existing_ids
        last_assistant: dict[str, Any] | None = None
        relevant: list[dict[str, Any]] = []
        collaboration_waiting_ids: set[str] = set()
        settled_since: float | None = None
        settle_seconds = max(0.6, self._poll_interval * 2)
        while True:
            messages_payload = self.list_messages(
                session_id,
                agent_id,
                wait_for_response=True,
            )
            relevant = [
                message
                for message in messages_payload.get("messages", [])
                if message.get("role") == "assistant"
                and (
                    str(message.get("id")) == reply_id
                    or str(message.get("id")) not in existing_ids
                )
            ]
            if relevant:
                last_assistant = relevant[-1]
            projected = pending_input_message(messages_payload, last_assistant, tool_call)
            if projected:
                return AgentScopeReply(
                    status="awaiting_permission", content="协同智能体需要下一步人工确认。",
                    message_id=projected["id"], raw_message=projected,
                    raw_messages=[*relevant[:-1], projected],
                )
            status = self.session_status(
                session_id,
                agent_id,
                wait_for_response=True,
            )
            if status in {
                "awaiting_permission",
                "awaiting_external_result",
            }:
                # A subsequent tool may require another decision. Return the
                # latest parked state only after AgentScope has applied this
                # decision to the original call.
                pending = [
                    block
                    for block in (last_assistant or {}).get("content", [])
                    if block.get("type") == "tool_call"
                    and block.get("state") in {"asking", "submitted"}
                ]
                original_still_pending = any(
                    str(block.get("id")) == str(tool_call.get("id"))
                    and int(block.get("confirmation_revision") or 0)
                    <= int(tool_call.get("confirmation_revision") or 0)
                    for block in pending
                )
                if pending and not original_still_pending:
                    return AgentScopeReply(
                        status=status,
                        content=self._message_text(last_assistant)
                        or "智能体需要下一步人工确认。",
                        message_id=(
                            last_assistant.get("id")
                            if last_assistant
                            else reply_id
                        ),
                        raw_message=last_assistant,
                        raw_messages=relevant,
                    )
            if (
                status == "idle"
                and last_assistant
                and last_assistant.get("finished_at") is not None
            ):
                _, team_work_pending = self.session_team_state(
                    session_id,
                    agent_id,
                    wait_for_response=True,
                )
                if team_work_pending:
                    if last_assistant.get("id"):
                        collaboration_waiting_ids.add(
                            str(last_assistant["id"]),
                        )
                    settled_since = None
                elif settled_since is None:
                    settled_since = time.monotonic()
                elif time.monotonic() - settled_since >= settle_seconds:
                    for message in relevant:
                        if (
                            str(message.get("id") or "")
                            in collaboration_waiting_ids
                        ):
                            message[
                                "platform_collaboration_status"
                            ] = "continued"
                    return AgentScopeReply(
                        status=self._terminal_reply_status(last_assistant),
                        content=self._message_text(last_assistant)
                        or "智能体已完成处理，但未返回文本内容。",
                        message_id=last_assistant.get("id"),
                        raw_message=last_assistant,
                        raw_messages=relevant,
                    )
            else:
                settled_since = None
            time.sleep(max(0.1, self._poll_interval))
