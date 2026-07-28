"""Server-side gateway client for the local AgentScope runtime."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx

from .config import Settings


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


class AgentScopeClient:
    """Minimal backend-only client for catalogue and chat operations."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.agentscope_base_url.rstrip("/")
        self._service_token = settings.agentscope_service_token.strip()
        if not self._service_token:
            raise ValueError(
                "AGENTSCOPE_SERVICE_TOKEN 未配置，平台后端不能连接 AgentScope。",
            )
        self._timeout = settings.agentscope_request_timeout_seconds
        self._poll_interval = settings.agentscope_poll_interval_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._service_token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                headers=self.headers,
                params=params,
                json=json,
                timeout=min(self._timeout, 30.0),
            )
        except httpx.HTTPError as exc:
            raise AgentScopeGatewayError(
                f"无法连接 AgentScope：{exc}",
                status_code=503,
            ) from exc
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
            connect=min(self._timeout, 30.0),
            read=None,
            write=min(self._timeout, 30.0),
            pool=min(self._timeout, 30.0),
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

    def get_catalog(self) -> dict[str, Any]:
        return self._request("GET", "/agent/platform/catalog")

    def create_session(
        self,
        *,
        agent: dict[str, Any],
        workspace_id: str,
        name: str,
    ) -> str:
        if not agent.get("model_ready"):
            raise AgentScopeGatewayError(
                f"智能体「{agent.get('name', agent.get('id'))}」尚未配置固定模型，"
                "不能由工程平台直接运行。",
                status_code=409,
            )
        body: dict[str, Any] = {
            "agent_id": agent["id"],
            "workspace_id": workspace_id,
            "name": name,
            "knowledge_config": agent.get("knowledge_config"),
        }
        created = self._request("POST", "/sessions/", json=body)
        session_id = str(created["session_id"])
        self.sync_session(agent=agent, session_id=session_id)
        return session_id

    def sync_session(
        self,
        *,
        agent: dict[str, Any],
        session_id: str,
    ) -> None:
        """Apply the latest admin-managed runtime policy to a session."""
        permission_mode = str(agent.get("permission_mode") or "auto")
        self._request(
            "PATCH",
            f"/sessions/{session_id}",
            params={"agent_id": str(agent["id"])},
            json={
                "permission_mode": permission_mode,
                "knowledge_config": agent.get("knowledge_config"),
            },
        )

    def list_messages(self, session_id: str, agent_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/sessions/{session_id}/messages",
            params={"agent_id": agent_id, "limit": "200"},
        )

    def session_status(self, session_id: str, agent_id: str) -> str:
        payload = self._request(
            "GET",
            f"/sessions/{session_id}/status",
            params={"agent_id": agent_id},
        )
        return str(payload["status"])

    def session_team_state(
        self,
        session_id: str,
        agent_id: str,
    ) -> tuple[bool, bool]:
        """Return ``(team_exists, member_work_is_pending)``.

        A leader may legitimately retain a team after answering. Team
        existence alone therefore cannot be used as a completion signal.
        Member sessions are checked individually so the gateway waits for
        actual collaboration work, not for an optional ``TeamDelete`` call.
        """
        payload = self._request(
            "GET",
            "/sessions/",
            params={"agent_id": agent_id},
        )
        for view in payload.get("sessions", []):
            session = view.get("session") or {}
            if str(session.get("id")) == session_id:
                team = view.get("team")
                if not session.get("team_id") or not team:
                    return False, False
                for member in team.get("members") or []:
                    member_agent = member.get("agent") or {}
                    member_session_id = str(member.get("session_id") or "")
                    member_agent_id = str(member_agent.get("id") or "")
                    if (
                        member_session_id
                        and member_agent_id
                        and self.session_status(
                            member_session_id,
                            member_agent_id,
                        )
                        != "idle"
                    ):
                        return True, True
                return True, False
        raise AgentScopeGatewayError(
            f"AgentScope 会话 {session_id} 不存在或不可见。",
            status_code=409,
        )

    @staticmethod
    def _message_text(message: dict[str, Any] | None) -> str:
        if not message:
            return ""
        blocks = message.get("content") or []
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

    def chat(
        self,
        *,
        agent_id: str,
        session_id: str,
        content: str,
        sender_name: str,
        metadata: dict[str, Any],
    ) -> AgentScopeReply:
        before = self.list_messages(session_id, agent_id)
        existing_ids = {
            str(message.get("id"))
            for message in before.get("messages", [])
            if message.get("id")
        }
        user_message_id = uuid4().hex
        self._request(
            "POST",
            "/chat/",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "input": {
                    "id": user_message_id,
                    "name": sender_name,
                    "role": "user",
                    "content": [{"type": "text", "text": content}],
                    "metadata": metadata,
                },
            },
        )

        deadline = time.monotonic() + self._timeout
        observed_running = False
        last_assistant: dict[str, Any] | None = None
        new_assistants: list[dict[str, Any]] = []
        settled_message_id: str | None = None
        settled_since: float | None = None
        settle_seconds = max(0.6, self._poll_interval * 2)
        while time.monotonic() < deadline:
            messages_payload = self.list_messages(session_id, agent_id)
            new_assistants = [
                message
                for message in messages_payload.get("messages", [])
                if message.get("role") == "assistant"
                and str(message.get("id")) not in existing_ids
            ]
            if new_assistants:
                last_assistant = new_assistants[-1]

            status = self.session_status(session_id, agent_id)
            observed_running = observed_running or status == "running"
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
                )
                if team_work_pending:
                    settled_message_id = None
                    settled_since = None
                else:
                    candidate_id = str(last_assistant.get("id") or "")
                    if candidate_id != settled_message_id:
                        settled_message_id = candidate_id
                        settled_since = time.monotonic()
                    elif (
                        settled_since is not None
                        and time.monotonic() - settled_since
                        >= settle_seconds
                    ):
                        return AgentScopeReply(
                            status="completed",
                            content=self._message_text(last_assistant)
                            or "智能体已完成处理，但未返回文本内容。",
                            message_id=last_assistant.get("id"),
                            raw_message=last_assistant,
                            raw_messages=new_assistants,
                        )
            elif observed_running:
                settled_message_id = None
                settled_since = None
            time.sleep(max(0.1, self._poll_interval))

        raise AgentScopeGatewayError(
            f"等待智能体响应超过 {self._timeout:g} 秒，请稍后重试。",
            status_code=504,
        )

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
    ) -> AgentScopeReply:
        """Resume a parked reply after a platform user's decision."""
        before = self.list_messages(session_id, agent_id)
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
        )
        if str(trigger.get("session_id") or session_id) != session_id:
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

        deadline = time.monotonic() + self._timeout
        last_assistant: dict[str, Any] | None = None
        relevant: list[dict[str, Any]] = []
        settled_since: float | None = None
        settle_seconds = max(0.6, self._poll_interval * 2)
        while time.monotonic() < deadline:
            messages_payload = self.list_messages(session_id, agent_id)
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
            status = self.session_status(session_id, agent_id)
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
                )
                if team_work_pending:
                    settled_since = None
                elif settled_since is None:
                    settled_since = time.monotonic()
                elif time.monotonic() - settled_since >= settle_seconds:
                    return AgentScopeReply(
                        status="completed",
                        content=self._message_text(last_assistant)
                        or "智能体已完成处理，但未返回文本内容。",
                        message_id=last_assistant.get("id"),
                        raw_message=last_assistant,
                        raw_messages=relevant,
                    )
            else:
                settled_since = None
            time.sleep(max(0.1, self._poll_interval))

        raise AgentScopeGatewayError(
            f"等待智能体确认结果超过 {self._timeout:g} 秒，请稍后重试。",
            status_code=504,
        )
