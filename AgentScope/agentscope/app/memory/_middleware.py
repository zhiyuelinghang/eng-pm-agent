# -*- coding: utf-8 -*-
"""AgentScope lifecycle adapter for the complete Dobby memory module."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
import json
import logging
from typing import Any, TYPE_CHECKING

from ...event import ReplyEndEvent, ReplyStartEvent
from ...message import Msg, TextBlock, ToolResultState
from ...middleware import MiddlewareBase
from ...permission import PermissionBehavior, PermissionDecision
from ...tool import ToolBase, ToolChunk, ToolResponse
from ._runtime import MemoryRuntime, MemoryScope, MemoryTarget
from ._scope_router import route_memory_content

if TYPE_CHECKING:
    from ...agent import Agent


logger = logging.getLogger(__name__)
_STATE_KEY = "dobby_memory_state"
_RECORDED_TASKS_KEY = "dobby_memory_recorded_tasks"
_INJECTED_FLAG = "dobby_memory_injected"


def _input_text(inputs: Any) -> str:
    """Extract the newest user text from AgentScope reply inputs."""

    items = inputs if isinstance(inputs, list) else [inputs]
    for item in reversed(items):
        if isinstance(item, Msg) and item.role == "user":
            return item.get_text_content() or ""
    return ""


def _summary_text(summary: Any) -> str:
    if isinstance(summary, str):
        return summary
    if isinstance(summary, list):
        return "\n".join(
            block.text
            for block in summary
            if getattr(block, "type", None) == "text"
        )
    return str(summary or "")


def _task_map(agent: "Agent") -> dict[str, dict[str, Any]]:
    """Translate AgentScope tasks to the upstream lifecycle contract."""

    tasks: dict[str, dict[str, Any]] = {}
    for task in agent.state.tasks_context.tasks:
        raw = task.model_dump(mode="json")
        status = raw.get("state")
        tasks[str(raw.get("id") or len(tasks))] = {
            **raw,
            "status": "done" if status == "completed" else status,
            "description": raw.get("description") or raw.get("subject") or "",
            "outcome": "success" if status == "completed" else status,
        }
    return tasks


def _state_messages(raw_messages: Any) -> list[Msg]:
    result: list[Msg] = []
    for item in raw_messages or []:
        if isinstance(item, Msg):
            result.append(item)
        elif isinstance(item, dict):
            try:
                result.append(Msg.model_validate(item))
            except Exception:
                continue
    return result


def _serializable_state(state: dict[str, Any]) -> dict[str, Any]:
    """Convert DobbyState to data that AgentState can persist as JSON."""

    payload = dict(state)
    payload["messages"] = [
        msg.model_dump(mode="json") if isinstance(msg, Msg) else msg
        for msg in state.get("messages", [])
    ]
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _response_text(item: Any) -> str:
    if isinstance(item, Msg):
        return item.get_text_content() or ""
    blocks = getattr(item, "content", []) or []
    return "\n".join(
        block.text
        for block in blocks
        if getattr(block, "type", None) == "text"
    )


class _DobbyMemoryTool(ToolBase):
    """Expose one unmodified upstream ``memory_tools`` schema to AgentScope."""

    is_external_tool = False
    is_state_injected = False
    is_mcp = False
    is_concurrency_safe = False

    def __init__(self, middleware: "DobbyMemoryMiddleware", schema: dict) -> None:
        super().__init__()
        function = schema["function"]
        self.name = str(function["name"])
        self.description = str(function.get("description") or "")
        self.input_schema = dict(function.get("parameters") or {})
        self.is_read_only = self.name != "add_memory"
        self._middleware = middleware

    async def check_permissions(self, *_args: Any, **_kwargs: Any) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Dobby 原版记忆工具已由平台自动授权。",
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        from utils.memory_tools import execute_tool

        state = self._middleware.active_state or {}
        if self.name == "search_memory":
            results = await self._middleware.manager.recall_scopes(
                str(kwargs.get("query") or ""),
                [target.as_dict() for target in self._middleware.scope.memory_targets],
                top_k=min(max(int(kwargs.get("top_k") or 5), 1), 10),
            )
            if not results:
                result = "未找到相关记忆。"
            else:
                lines = []
                for index, item in enumerate(results, 1):
                    content = str(item.get("memory") or item)
                    score = float(item.get("score") or 0)
                    lines.append(f"{index}. {content} (相关度: {score:.2f})")
                result = "\n".join(lines)
        elif self.name == "add_memory":
            agent = self._middleware.active_agent
            if agent is None:
                result = "写入记忆失败: 当前没有活动中的智能体会话。"
            else:
                count = await self._middleware._remember_routed(
                    agent,
                    str(kwargs.get("content") or ""),
                    importance=float(kwargs.get("importance") or 0.5),
                    memory_type="explicit",
                    source="explicit_tool",
                )
                result = (
                    f"已保存 {count} 条记忆。"
                    if count
                    else "写入记忆失败: 没有可保存的内容。"
                )
        else:
            result = await execute_tool(
                self.name,
                kwargs,
                user_id=self._middleware.scope.scope_key,
                agent_id=self._middleware.scope.scope_key,
                state=state,
                kb_names=state.get("bound_knowledge_bases") or None,
                project_id=self._middleware.scope.scope_key,
            )
        failed = "失败:" in result or result.startswith("未知工具:")
        return ToolChunk(
            content=[TextBlock(text=result)],
            state=(ToolResultState.ERROR if failed else ToolResultState.SUCCESS),
            is_last=True,
            metadata={"source": "platform-memory", "operation": self.name},
        )


class DobbyMemoryMiddleware(MiddlewareBase):
    """Map AgentScope turns onto upstream Dobby session and memory APIs."""

    def __init__(
        self,
        runtime: MemoryRuntime,
        scope: MemoryScope,
        settings: Any | None = None,
    ) -> None:
        self.runtime = runtime
        self.scope = scope
        self.settings = (
            dict(settings.model_dump())
            if hasattr(settings, "model_dump")
            else dict(settings or {})
        )
        self.manager = runtime.manager(scope, settings)
        self.active_state: dict[str, Any] | None = None
        self.active_agent: Agent | None = None
        self._tool_names: list[str] = []

    async def get_middleware_key(self) -> str:
        return f"DobbyMemoryMiddleware:{self.scope.scope_key}"

    async def list_tools(self) -> list[ToolBase]:
        from utils.memory_tools import TOOL_SCHEMAS

        return [_DobbyMemoryTool(self, schema) for schema in TOOL_SCHEMAS]

    async def _load_state(self, agent: "Agent") -> dict[str, Any]:
        from utils.langgraph_utils import DobbyState

        raw = agent.state.middle_context.get(_STATE_KEY)
        if isinstance(raw, dict):
            payload = dict(raw)
            payload["messages"] = _state_messages(payload.get("messages"))
            state = DobbyState(**payload)
        else:
            state = await self.manager.start_session(
                session_id=self.scope.session_id,
                project_id=self.scope.scope_key,
                role_id=self.scope.agent_id,
            )
        self._sync_from_agent(agent, state)
        self.active_state = state
        self.active_agent = agent
        return state

    async def end_persisted_session(self, agent_state: Any) -> None:
        """Run the upstream session-end lifecycle before durable deletion."""

        from utils.langgraph_utils import DobbyState

        raw = agent_state.middle_context.get(_STATE_KEY)
        if not isinstance(raw, dict):
            return
        payload = dict(raw)
        payload["messages"] = _state_messages(payload.get("messages"))
        await self.manager.end_session(DobbyState(**payload))

    def _sync_from_agent(self, agent: "Agent", state: dict[str, Any]) -> None:
        state["thread_id"] = self.scope.session_id
        state["project_id"] = self.scope.scope_key
        state["current_role"] = self.scope.agent_id
        state["memory_targets"] = [
            target.as_dict()
            for target in self.scope.memory_targets
        ]
        state["summary"] = _summary_text(agent.state.summary)
        state["tasks"] = _task_map(agent)
        state["messages"] = [
            msg
            for msg in agent.state.context
            if not msg.metadata.get(_INJECTED_FLAG)
        ]
        state["message_count"] = len(state["messages"])
        context_size = int(getattr(getattr(agent, "model", None), "context_size", 0) or 0)
        if context_size > 0:
            state["max_token_budget"] = context_size
        state["compression_trigger_ratio"] = float(
            self.settings.get("compression_trigger_ratio", 0.8),
        )
        state["historian_trigger_ratio"] = float(
            self.settings.get("historian_trigger_ratio", 0.3),
        )

    @staticmethod
    async def _call_agent_model(
        agent: "Agent",
        messages: list[Msg],
        intent: str = "compress",
    ) -> Msg:
        """Use the dedicated memory model, or preserve the legacy fallback."""

        from agentscope.message import AssistantMsg
        from utils.langgraph_utils import (
            _call_model as fallback_call,
            has_runtime_memory_model,
        )

        if has_runtime_memory_model():
            return await fallback_call(messages, intent=intent)

        model = getattr(agent, "model", None)
        if model is None:
            return await fallback_call(messages, intent=intent)

        def first_text(content: Any) -> str:
            if isinstance(content, str):
                return content
            for block in content or []:
                text = getattr(block, "text", None)
                if text:
                    return str(text)
                if isinstance(block, dict) and block.get("text"):
                    return str(block["text"])
            return ""

        result = model(messages)
        last_content = ""
        if hasattr(result, "__aiter__"):
            async for chunk in result:
                content = (
                    chunk.get("content", [])
                    if hasattr(chunk, "get")
                    else getattr(chunk, "content", [])
                )
                text = first_text(content)
                if text:
                    last_content = text
        elif hasattr(result, "__await__"):
            response = await result
            last_content = first_text(getattr(response, "content", response))
        else:
            last_content = first_text(getattr(result, "content", result))
        return AssistantMsg("assistant", last_content or "(empty response)")

    @staticmethod
    def _target_metadata(
        target: MemoryTarget,
        *,
        session_id: str,
        source_agent_id: str,
        source: str,
    ) -> dict[str, Any]:
        metadata = {
            key: value
            for key, value in target.as_dict().items()
            if key not in {"user_id", "agent_id"} and value is not None
        }
        metadata.update({
            "source": source,
            "source_session_id": session_id,
            "source_agent_id": source_agent_id,
        })
        return metadata

    async def _remember_routed(
        self,
        agent: "Agent",
        content: str,
        *,
        importance: float,
        memory_type: str,
        source: str,
    ) -> int:
        """Classify and persist content without widening an uncertain scope."""

        from ..storage._model._platform_settings import (
            DEFAULT_MEMORY_SCOPE_PROMPT,
        )

        routed = await route_memory_content(
            content=content,
            scope=self.scope,
            prompt_template=str(
                self.settings.get("memory_scope_prompt")
                or DEFAULT_MEMORY_SCOPE_PROMPT
            ),
            call_model=lambda messages: self._call_agent_model(
                agent,
                messages,
                intent="scope",
            ),
        )
        infer_sync = (
            bool(self.settings.get("mem0_infer_enabled", False))
            and not bool(self.settings.get("mem0_infer_async", True))
        )
        infer_async = (
            bool(self.settings.get("mem0_infer_enabled", False))
            and bool(self.settings.get("mem0_infer_async", True))
        )
        stored = 0
        for item in routed:
            target = self.scope.memory_target(item.scope_type)
            metadata = self._target_metadata(
                target,
                session_id=self.scope.session_id,
                source_agent_id=self.scope.agent_id,
                source=source,
            )
            created = await self.manager.remember(
                item.content,
                importance=max(0.0, min(1.0, importance)),
                memory_type=memory_type,
                user_id=target.user_id,
                agent_id=target.agent_id,
                metadata=metadata,
                infer=infer_sync,
            )
            stored += len(created)
            if infer_async:
                from utils.langgraph_utils import _background_enrich_memory

                asyncio.create_task(
                    _background_enrich_memory(
                        item.content,
                        target.user_id,
                        target.agent_id,
                        {
                            "memory_type": memory_type,
                            "importance": max(0.0, min(1.0, importance)),
                            "role": self.scope.agent_id,
                            **metadata,
                        },
                    ),
                    name=(
                        "dobby-memory-enrich:"
                        f"{self.scope.session_id}:{item.scope_type}"
                    ),
                )
        return stored

    def _save_state(self, agent: "Agent", state: dict[str, Any]) -> None:
        agent.state.middle_context[_STATE_KEY] = _serializable_state(state)
        self.active_state = state

    @staticmethod
    def _previous_assistant(agent: "Agent") -> str:
        for msg in reversed(agent.state.context):
            if msg.role == "assistant":
                text = msg.get_text_content()
                if text:
                    return text
        return ""

    @staticmethod
    def _injection_messages(assembly: Any) -> list[Msg]:
        """Keep only upstream generated layers, without duplicating history."""

        injected: list[Msg] = []
        for index, msg in enumerate(assembly.messages):
            if index == 0 or not isinstance(msg, Msg) or msg.role != "system":
                continue
            text = msg.get_text_content() or ""
            if text.startswith("<summary>"):
                continue
            clone = msg.model_copy(deep=True)
            clone.metadata[_INJECTED_FLAG] = True
            clone.metadata["source"] = "platform-memory"
            injected.append(clone)
        return injected

    async def on_reply(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        query = _input_text(input_kwargs.get("inputs"))
        previous_response = self._previous_assistant(agent)
        state = await self._load_state(agent)
        self._tool_names = []

        injected: list[Msg] = []
        if query:
            try:
                assembly = await self.manager.assemble_context(
                    state,
                    query,
                    system_prompt=getattr(agent, "_system_prompt", None),
                    mode="auto",
                )
                injected = self._injection_messages(assembly)
                state["last_context_mode"] = assembly.mode_used
                state["last_context_tokens"] = assembly.token_estimate
                state["last_context_warnings"] = assembly.budget_warnings
            except Exception:
                logger.exception("Dobby context assembly failed; continuing without injection")

        final_msg: Msg | None = None
        terminal_events: list[ReplyEndEvent] = []

        async def _finalize_turn() -> None:
            if injected:
                injected_ids = {msg.id for msg in injected}
                agent.state.context = [
                    msg for msg in agent.state.context if msg.id not in injected_ids
                ]

            self._sync_from_agent(agent, state)
            try:
                if query and final_msg is not None:
                    await self._record_completed_turn(
                        agent,
                        state,
                        query=query,
                        response=final_msg.get_text_content() or "",
                        previous_response=previous_response,
                    )
            finally:
                # Persist the synchronized lifecycle state even when a
                # memory-side write fails. ChatService will still surface the
                # original exception as a terminal error event.
                self._save_state(agent, state)

        try:
            async for item in next_handler(**input_kwargs):
                if isinstance(item, ReplyStartEvent) and injected:
                    agent.state.context.extend(injected)
                if isinstance(item, Msg) and item.role == "assistant":
                    final_msg = item
                if isinstance(item, ReplyEndEvent):
                    # Agent._reply_impl emits ReplyEndEvent before its final
                    # AssistantMsg. Holding the terminal event lets us capture
                    # that message and finish all Dobby writes before clients
                    # are told the session is ready for another turn.
                    terminal_events.append(item)
                    continue
                yield item
        except BaseException:
            await _finalize_turn()
            raise
        else:
            await _finalize_turn()
            for terminal_event in terminal_events:
                yield terminal_event

    async def _record_completed_turn(
        self,
        agent: "Agent",
        state: dict[str, Any],
        *,
        query: str,
        response: str,
        previous_response: str,
    ) -> None:
        from utils.audit_logger import get_audit_logger
        from utils.decay_curves import record_user_activity
        from utils.graphiti_client import record_task_events
        from utils.lifecycle import extract_experiences
        from utils.skill_compiler import _extract_correction_rule
        from utils.skill_events import record_success_pattern, record_user_correction

        audit = get_audit_logger()
        await record_user_activity(self.scope.scope_key)
        await audit.log_message(
            "user",
            query,
            session_id=self.scope.session_id,
            project_id=self.scope.scope_key,
        )
        if response:
            await audit.log_message(
                self.scope.agent_id,
                response,
                session_id=self.scope.session_id,
                project_id=self.scope.scope_key,
            )

        await self._remember_routed(
            agent,
            query,
            importance=0.5,
            memory_type="interaction",
            source="conversation",
        )

        if _extract_correction_rule(query):
            await record_user_correction(
                project_id=self.scope.scope_key,
                role_id=self.scope.agent_id,
                user_message=query,
                previous_response=previous_response,
            )

        distinct_tools = list(dict.fromkeys(self._tool_names))
        if len(distinct_tools) >= 3:
            await record_success_pattern(
                project_id=self.scope.scope_key,
                role_id=self.scope.agent_id,
                tool_sequence=distinct_tools,
                tool_count=len(self._tool_names),
            )

        tasks = _task_map(agent)
        already = set(agent.state.middle_context.get(_RECORDED_TASKS_KEY) or [])
        newly_done = {
            task_id: details
            for task_id, details in tasks.items()
            if details.get("status") == "done" and task_id not in already
        }
        if newly_done:
            await record_task_events(self.scope.scope_key, newly_done)
            await extract_experiences(
                self.scope.scope_key,
                newly_done,
                state.get("messages", []),
            )
            already.update(newly_done)
            agent.state.middle_context[_RECORDED_TASKS_KEY] = sorted(already)

    async def on_acting(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        from utils.skill_events import record_tool_error

        tool_call = input_kwargs.get("tool_call")
        tool_name = str(getattr(tool_call, "name", "") or "")
        if tool_name:
            self._tool_names.append(tool_name)

        final_state: Any = None
        final_text = ""
        async for item in next_handler(**input_kwargs):
            if isinstance(item, (ToolChunk, ToolResponse)):
                final_state = item.state
                text = _response_text(item)
                if text:
                    final_text = text
            yield item

        if tool_name and final_state in {
            ToolResultState.ERROR,
            ToolResultState.DENIED,
            ToolResultState.INTERRUPTED,
        }:
            await record_tool_error(
                project_id=self.scope.scope_key,
                role_id=self.scope.agent_id,
                tool_name=tool_name,
                error_message=final_text or str(final_state),
            )

    async def on_compress_context(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> None:
        from utils.audit_logger import get_audit_logger
        from utils.compression import estimate_tokens

        state = self.active_state or await self._load_state(agent)
        self._sync_from_agent(agent, state)
        before_tokens = estimate_tokens(state.get("messages", []))
        compressed = await self.manager.compress_if_needed(
            state,
            call_model=lambda messages: self._call_agent_model(agent, messages),
        )
        if not compressed:
            self._save_state(agent, state)
            return

        agent.state.summary = state.get("summary", "")
        agent.state.context = _state_messages(state.get("messages", []))
        self._save_state(agent, state)
        await get_audit_logger().log_compress(
            before_tokens,
            estimate_tokens(state.get("messages", [])),
            str(state.get("summary", "")),
            session_id=self.scope.session_id,
            project_id=self.scope.scope_key,
        )
