# -*- coding: utf-8 -*-
"""Read-only project-knowledge tool backed by a bound WeKnora robot."""

from __future__ import annotations

import json
import logging
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
        "查询当前工程项目绑定的 WeKnora 机器人。仅当用户的问题需要查阅"
        "工程资料、图纸方案、规范标准、历史案例或文件内容时调用；普通闲聊、"
        "平台数据库状态和无需资料依据的问题不要调用。返回答案与资料引用后，"
        "应由当前 AgentScope 智能体结合用户问题继续组织最终回复。"
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
    ) -> None:
        super().__init__()
        self._connection = connection
        self._robot_id = robot_id.strip()

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
        async with client.stream(
            "POST",
            self._url(f"/agent-chat/{quote(session_id, safe='')}"),
            params={"resource_urls": "public"},
            json={
                "query": query,
                "agent_enabled": True,
                "agent_id": self._robot_id,
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
        return answer, references

    async def call(self, query: str) -> ToolChunk:
        query = query.strip()
        if not query:
            return ToolChunk(
                content=[TextBlock(text="资料查询不能为空。")],
                state=ToolResultState.ERROR,
                is_last=True,
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
                metadata={
                    "operation": self.name,
                    "weknora_robot_id": self._robot_id,
                    "reference_count": len(references),
                },
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
                metadata={"operation": self.name},
            )
