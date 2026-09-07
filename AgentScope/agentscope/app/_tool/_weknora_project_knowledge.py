# -*- coding: utf-8 -*-
"""Read-only project-knowledge tool backed by a bound WeKnora robot."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from ...message import TextBlock, ToolResultState
from ...permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from ...tool import ToolBase, ToolChunk
from ..storage import WeKnoraConnectionConfig


logger = logging.getLogger(__name__)


class WeKnoraProjectKnowledgeTool(ToolBase):
    """Ask only the WeKnora robot bound to the current platform project."""

    name = "weknora_query_project_knowledge"
    description = (
        "查询当前工程项目绑定的 WeKnora 机器人。仅向用户明确点名或"
        "Dobby 动态调用的受权资料助手提供。查询范围已由平台后端按当前用户"
        "权限锁定，"
        "不得扩大或改写。返回答案与资料引用后，应结合用户问题组织最终回复。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": 4000,
                "description": (
                    "发送给项目知识机器人的完整、可独立理解的资料查询。"
                ),
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    is_concurrency_safe = True
    is_read_only = True
    is_state_injected = False
    is_external_tool = False
    is_mcp = False

    def __init__(
        self,
        *,
        connection: WeKnoraConnectionConfig,
        robot_id: str,
        project_id: str | None = None,
        platform_user_id: str | None = None,
        platform_conversation_id: str | None = None,
        knowledge_base_ids: list[str] | None = None,
        knowledge_ids: list[str] | None = None,
        restricted: bool = False,
        scope_resolver: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        super().__init__()
        self._connection = connection
        self._robot_id = robot_id.strip()
        self._project_id = (project_id or "").strip()
        self._platform_user_id = (platform_user_id or "").strip()
        self._platform_conversation_id = (
            platform_conversation_id or ""
        ).strip()
        self._scope_supplied = knowledge_base_ids is not None
        self._knowledge_base_ids = tuple(
            dict.fromkeys(
                value.strip()
                for value in (knowledge_base_ids or [])
                if value.strip()
            ),
        )
        self._knowledge_ids = tuple(
            dict.fromkeys(
                value.strip()
                for value in (knowledge_ids or [])
                if value.strip()
            ),
        )
        self._restricted = restricted
        self._scope_resolver = scope_resolver

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        del tool_input, context
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="只读查询当前项目已绑定的 WeKnora 机器人。",
        )

    def _url(self, path: str) -> str:
        prefix = self._connection.api_prefix.rstrip("/")
        return f"{self._connection.base_url}{prefix}/{path.lstrip('/')}"

    def _audit_metadata(self, reference_count: int = 0) -> dict[str, Any]:
        """Return the immutable platform identity and permission boundary."""

        return {
            "operation": self.name,
            "weknora_robot_id": self._robot_id,
            "platform_user_id": self._platform_user_id,
            "platform_project_id": self._project_id,
            "platform_conversation_id": self._platform_conversation_id,
            "knowledge_access_mode": (
                "restricted" if self._restricted else "project"
            ),
            "knowledge_base_ids": list(self._knowledge_base_ids),
            "knowledge_ids": list(self._knowledge_ids),
            "reference_count": reference_count,
        }

    @staticmethod
    def _payload_detail(payload: object) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ("message", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    async def _create_session(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            self._url("/sessions"),
            json={"agent_id": self._robot_id},
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("success") is False:
            raise RuntimeError(
                self._payload_detail(payload) or "WeKnora 创建会话失败。",
            )
        data = payload.get("data") if isinstance(payload, dict) else None
        session_id = str(data.get("id") or "") if isinstance(data, dict) else ""
        if not session_id:
            raise RuntimeError("WeKnora 创建会话后未返回 session_id。")
        return session_id

    async def _ask(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        query: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        answer_parts: list[str] = []
        references: list[dict[str, Any]] = []
        chat_route = "knowledge-chat" if self._knowledge_ids else "agent-chat"
        async with client.stream(
            "POST",
            self._url(f"/{chat_route}/{quote(session_id, safe='')}"),
            params={"resource_urls": "public"},
            json={
                "query": query,
                # WeKnora agent mode may invoke wiki tools outside an explicit
                # file allowlist. Restricted users therefore use normal RAG.
                "agent_enabled": not bool(self._knowledge_ids),
                "agent_id": self._robot_id,
                "knowledge_base_ids": list(self._knowledge_base_ids),
                "knowledge_ids": list(self._knowledge_ids),
                "channel": "api",
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].lstrip())
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                response_type = str(event.get("response_type") or "")
                if response_type == "answer":
                    answer_parts.append(str(event.get("content") or ""))
                elif response_type == "references":
                    raw = event.get("knowledge_references")
                    if isinstance(raw, list):
                        references.extend(
                            item for item in raw if isinstance(item, dict)
                        )
                elif response_type == "error":
                    raise RuntimeError(
                        str(event.get("content") or "WeKnora 查询失败。"),
                    )
                elif response_type == "complete":
                    break
        answer = "".join(answer_parts).strip()
        if not answer:
            raise RuntimeError("WeKnora 未返回可用答案。")
        allowed_knowledge_ids = set(self._knowledge_ids)
        allowed_base_ids = set(self._knowledge_base_ids)
        if allowed_knowledge_ids:
            references = [
                item
                for item in references
                if str(item.get("knowledge_id") or "")
                in allowed_knowledge_ids
            ]
        elif self._restricted:
            references = []
        elif allowed_base_ids:
            references = [
                item
                for item in references
                if not item.get("knowledge_base_id")
                or str(item.get("knowledge_base_id")) in allowed_base_ids
            ]
        if self._project_id:
            rewritten: list[dict[str, Any]] = []
            encoded_project_id = quote(self._project_id, safe="")
            for raw in references:
                reference = dict(raw)
                knowledge_id = str(
                    reference.get("knowledge_id") or "",
                ).strip()
                if knowledge_id:
                    base = (
                        f"/api/projects/{encoded_project_id}/"
                        "engineering-documents/knowledge/"
                        f"{quote(knowledge_id, safe='')}"
                    )
                    # Never expose WeKnora's direct resource address to the
                    # platform conversation.  These routes re-check the
                    # current project and user permission on every access.
                    reference["preview_url"] = f"{base}/preview"
                    reference["download_url"] = f"{base}/download"
                rewritten.append(reference)
            references = rewritten
        return answer, references

    async def call(self, query: str) -> ToolChunk:
        query = query.strip()
        if not query:
            return ToolChunk(
                content=[TextBlock(text="资料查询不能为空。")],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata=self._audit_metadata(),
            )
        if self._scope_resolver is not None:
            return await self._call_with_current_scope(query)
        if self._restricted and not self._knowledge_ids:
            return ToolChunk(
                content=[TextBlock(text="当前账号没有可查询的工程资料权限。")],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata=self._audit_metadata(),
            )
        if self._scope_supplied and not self._knowledge_base_ids:
            return ToolChunk(
                content=[TextBlock(text="当前项目没有可查询的工程资料。")],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata=self._audit_metadata(),
            )

        headers = {
            self._connection.auth_header: (
                self._connection.api_key.get_secret_value()
            ),
            "Accept": "application/json, text/event-stream",
        }
        session_id = ""
        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=None,
                    write=30.0,
                    pool=10.0,
                ),
                follow_redirects=True,
                trust_env=False,
            ) as client:
                session_id = await self._create_session(client)
                try:
                    answer, references = await self._ask(
                        client,
                        session_id,
                        query,
                    )
                finally:
                    try:
                        await client.delete(
                            self._url(
                                f"/sessions/{quote(session_id, safe='')}",
                            ),
                        )
                    except httpx.HTTPError:
                        logger.warning(
                            "Unable to delete transient WeKnora session %s",
                            session_id,
                        )
            return ToolChunk(
                content=[
                    TextBlock(
                        text=json.dumps(
                            {
                                "answer": answer,
                                "references": references,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
                state=ToolResultState.SUCCESS,
                is_last=True,
                metadata=self._audit_metadata(len(references)),
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            logger.warning("WeKnora project knowledge query failed: %s", exc)
            return ToolChunk(
                content=[
                    TextBlock(
                        text=f"当前项目的 WeKnora 资料查询失败：{exc}",
                    ),
                ],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata=self._audit_metadata(),
            )

    async def _call_with_current_scope(self, query: str) -> ToolChunk:
        """Keep concurrent calls isolated and fail closed on revoked access."""
        try:
            scope = await self._scope_resolver()
            if (
                str(scope.get("user_id")) != self._platform_user_id
                or str(scope.get("project_id")) != self._project_id
                or not scope.get("weknora_query_enabled")
                or not scope.get("weknora_catalogue_ready")
                or not scope.get("weknora_agent_id")
            ):
                raise RuntimeError("当前会话的项目资料授权不可用，请刷新后重试。")
            scoped_tool = WeKnoraProjectKnowledgeTool(
                connection=self._connection,
                robot_id=scope["weknora_agent_id"],
                project_id=str(scope["project_id"]),
                platform_user_id=str(scope["user_id"]),
                platform_conversation_id=str(scope["conversation_id"]),
                knowledge_base_ids=scope.get("weknora_knowledge_base_ids") or [],
                knowledge_ids=scope.get("weknora_knowledge_ids") or [],
                restricted=True,
            )
            result = await scoped_tool.call(query)
            if result.state != ToolResultState.SUCCESS:
                return result
            current = await self._scope_resolver()
            if (
                any(current.get(key) != scope.get(key) for key in (
                    "user_id", "project_id", "conversation_id", "weknora_agent_id",
                    "weknora_query_enabled", "weknora_catalogue_ready",
                ))
                or not set(scope.get("weknora_knowledge_ids") or []).issubset(
                    current.get("weknora_knowledge_ids") or [],
                )
            ):
                raise RuntimeError("查询期间资料权限发生变化，本次结果已丢弃，请重新查询。")
            return result
        except (RuntimeError, ValueError, httpx.HTTPError) as exc:
            return ToolChunk(
                content=[TextBlock(text=f"项目资料权限校验失败：{exc}")],
                state=ToolResultState.ERROR, is_last=True,
                metadata=self._audit_metadata(),
            )
