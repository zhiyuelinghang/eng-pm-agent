"""Correlate AgentScope run-completion events with one platform SSE turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .agentscope_client import (
    AgentScopeClient,
    AgentScopeGatewayError,
    AgentScopeReply,
    AgentScopeRunCompletion,
)


AGENTSCOPE_RUN_COMPLETED_EVENT = "run_completed"


@dataclass(slots=True)
class AgentScopeCompletionRelay:
    """Hold transient reply events until their durable result is signalled.

    AgentScope may complete a leader run more than once while collaborators
    are working.  This relay correlates the first completion to the platform
    input, keeps intermediate replies for the final trace, and resolves the
    blocking gateway worker only when the whole leader turn is settled.
    """

    client: AgentScopeClient
    user_message_id: str
    completion: AgentScopeRunCompletion = field(
        default_factory=AgentScopeRunCompletion,
    )
    initial_run_completed: bool = False
    pending_reply_end: dict[str, Any] | None = None
    run_messages: list[dict[str, Any]] = field(default_factory=list)
    collaboration_waiting_ids: set[str] = field(default_factory=set)

    @staticmethod
    def handles(runtime_event: dict[str, Any]) -> bool:
        return (
            str(runtime_event.get("type") or "") == "CUSTOM"
            and str(runtime_event.get("name") or "")
            == AGENTSCOPE_RUN_COMPLETED_EVENT
        )

    def hold_reply_end(self, runtime_event: dict[str, Any]) -> None:
        """Hold REPLY_END briefly so completion can annotate team state."""
        self.pending_reply_end = runtime_event

    def flush_reply_end(self) -> dict[str, Any] | None:
        reply_end = self.pending_reply_end
        self.pending_reply_end = None
        return reply_end

    def consume(self, runtime_event: dict[str, Any]) -> dict[str, Any] | None:
        """Consume one internal completion and return any public REPLY_END."""
        value = runtime_event.get("value") or {}
        if not isinstance(value, dict):
            value = {}
        input_message_ids = {
            str(item) for item in value.get("input_message_ids") or []
        }
        if self.user_message_id in input_message_ids:
            self.initial_run_completed = True
        elif not self.initial_run_completed:
            # A late subscriber may replay the previous turn's completion
            # marker before the current run clears it.
            return None

        collaboration_pending = bool(value.get("collaboration_pending"))
        reply_end = self.flush_reply_end()
        if reply_end is not None and collaboration_pending:
            reply_end = {
                **reply_end,
                "platform_collaboration_pending": True,
            }
            reply_id = str(reply_end.get("reply_id") or "")
            if reply_id:
                self.collaboration_waiting_ids.add(reply_id)

        raw_reply = value.get("reply")
        if isinstance(raw_reply, dict):
            reply_id = str(raw_reply.get("id") or "")
            self.run_messages = [
                message
                for message in self.run_messages
                if str(message.get("id") or "") != reply_id
            ]
            self.run_messages.append(raw_reply)

        if collaboration_pending:
            return reply_end

        if not self.run_messages:
            self.completion.reject(
                AgentScopeGatewayError(
                    str(
                        value.get("error")
                        or (
                            "AgentScope 本次运行已结束，但没有生成智能体回复。"
                        )
                    ),
                    status_code=502,
                ),
            )
            return reply_end

        for message in self.run_messages:
            if (
                str(message.get("id") or "")
                in self.collaboration_waiting_ids
            ):
                message["platform_collaboration_status"] = "continued"
        last_assistant = self.run_messages[-1]
        runtime_status = str(
            value.get("runtime_status")
            or self.client._terminal_reply_status(last_assistant)
        )
        self.completion.resolve(
            AgentScopeReply(
                status=runtime_status,
                content=(
                    self.client._message_text(last_assistant)
                    or "智能体已完成处理，但未返回文本内容。"
                ),
                message_id=last_assistant.get("id"),
                raw_message=last_assistant,
                raw_messages=self.run_messages,
            ),
        )
        return reply_end
