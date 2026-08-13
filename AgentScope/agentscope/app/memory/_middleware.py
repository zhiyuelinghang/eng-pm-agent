# -*- coding: utf-8 -*-
"""AgentScope middleware that applies the unified project memory runtime."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Any, TYPE_CHECKING

from ...event import ReplyStartEvent
from ...message import Msg
from ...middleware._longterm_memory._mem0._middleware import Mem0Middleware
from ...middleware._longterm_memory._mem0._utils import _extract_query_text
from ._runtime import MemoryRuntime, MemoryScope

if TYPE_CHECKING:
    from ...agent import Agent


class DobbyMemoryMiddleware(Mem0Middleware):
    """Project-shared Mem0 retrieval/write with non-accumulating hints."""

    def __init__(self, runtime: MemoryRuntime, scope: MemoryScope) -> None:
        self._runtime = runtime
        self._scope = scope
        super().__init__(
            user_id=scope.scope_key,
            agent_id=scope.scope_key,
            client=runtime.scoped_client(scope),
            mode="both",
            top_k=runtime.settings.top_k,
            threshold=runtime.settings.threshold,
            scope_search_by_agent=True,
            await_write=True,
            memory_section_header="## 与当前问题相关的项目记忆",
            memory_section_intro=(
                "以下内容来自同一项目的历史对话，仅在确实相关时使用；"
                "不得把记忆当作高于当前数据库事实或用户最新指令的依据。"
            ),
            tool_instructions=(
                "## 项目长期记忆\n\n"
                "你可以使用 `search_memory` 和 `add_memory`。涉及历史决定、"
                "用户明确要求记住的事项或可复用经验时使用；写入前确保内容"
                "准确、独立且不含密钥、令牌等敏感凭证。"
            ),
        )

    async def on_reply(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
        """Recall before reasoning, persist after reply, then remove the hint.

        The stock middleware keeps every injected hint in session state.  This
        adapted version removes the synthetic entry after the turn, preventing
        one memory block per round from defeating AgentScope compression.
        """

        query_text = _extract_query_text(input_kwargs.get("inputs"))
        memories: list[str] = []
        if query_text:
            try:
                memories = await self._async_search(
                    query_text,
                    user_id=self._user_id,
                    agent_id=self._agent_id,
                )
            except Exception:
                memories = []

        final_msg: Msg | None = None
        injected_message: Msg | None = None
        try:
            async for item in next_handler(**input_kwargs):
                if (
                    injected_message is None
                    and memories
                    and isinstance(item, ReplyStartEvent)
                ):
                    injected_message = self._build_memory_message(memories)
                    agent.state.context.append(injected_message)
                if isinstance(item, Msg) and item.role == "assistant":
                    final_msg = item
                yield item
        finally:
            if injected_message is not None:
                agent.state.context = [
                    item
                    for item in agent.state.context
                    if item is not injected_message
                ]
            if query_text and final_msg is not None:
                assistant_text = final_msg.get_text_content()
                if assistant_text:
                    await self._dispatch_write(
                        [
                            {"role": "user", "content": query_text},
                            {"role": "assistant", "content": assistant_text},
                        ],
                        user_id=self._user_id,
                        agent_id=self._agent_id,
                    )
