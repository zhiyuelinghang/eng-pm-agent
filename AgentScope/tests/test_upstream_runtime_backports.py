"""Regression tests for selected AgentScope upstream runtime backports."""

import base64
from types import SimpleNamespace
from typing import Any, AsyncGenerator
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.credential import CredentialBase
from agentscope.event import ToolResultEndEvent, ToolResultStartEvent
from agentscope.message import (
    AssistantMsg,
    Base64Source,
    DataBlock,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultState,
    UserMsg,
)
from agentscope.middleware import MiddlewareBase
from agentscope.model import (
    ChatModelBase,
    ChatResponse,
    ChatUsage,
    FinishedReason,
)
from agentscope.model._utils import _StreamAccumulator
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from agentscope.state import AgentState
from agentscope.tool import (
    ToolBase,
    ToolChunk,
    ToolChoice,
    ToolResponse,
    Toolkit,
)


class ChatResponseFinishedReasonBackportTest(TestCase):
    """Keep explicit model interruption reasons visible as attributes."""

    def test_explicit_finished_reason_matches_mapping(self) -> None:
        response = ChatResponse(
            content=[],
            is_last=True,
            finished_reason=FinishedReason.INTERRUPTED,
        )

        self.assertEqual(
            response.finished_reason,
            response["finished_reason"],
        )
        self.assertEqual(
            response.finished_reason,
            FinishedReason.INTERRUPTED,
        )


class ToolResponseStateBackportTest(TestCase):
    """An observed tool error must remain the terminal aggregate state."""

    def test_error_is_not_downgraded_by_later_terminal_chunks(self) -> None:
        for later_state in (
            ToolResultState.INTERRUPTED,
            ToolResultState.DENIED,
        ):
            with self.subTest(later_state=later_state):
                response = ToolResponse()
                response.append_chunk(
                    ToolChunk(content=[], state=ToolResultState.ERROR),
                )
                response.append_chunk(
                    ToolChunk(content=[], state=later_state),
                )

                self.assertEqual(response.state, ToolResultState.ERROR)


class StreamAccumulatorTest(TestCase):
    """Verify constant-time fragment collection preserves response data."""

    def test_mixed_stream_fragments_are_joined_once(self) -> None:
        usage = ChatUsage(input_tokens=11, output_tokens=7, time=0.25)
        accumulator = _StreamAccumulator()
        chunks = [
            ChatResponse(
                id="response-id",
                is_last=False,
                content=[
                    ThinkingBlock(id="thinking", thinking="先"),
                    TextBlock(id="text", text="答"),
                    ToolCallBlock(id="tool", name="", input='{"x":'),
                    DataBlock(
                        id="audio",
                        source=Base64Source(
                            data=base64.b64encode(b"\x00").decode("ascii"),
                            media_type="audio/pcm",
                        ),
                    ),
                ],
            ),
            ChatResponse(
                id="response-id",
                is_last=False,
                usage=usage,
                content=[
                    ThinkingBlock(
                        id="thinking",
                        thinking="想",
                        signature="provider-signature",
                    ),
                    TextBlock(id="text", text="案"),
                    ToolCallBlock(
                        id="tool",
                        name="calculator",
                        input="1}",
                    ),
                    DataBlock(
                        id="audio",
                        source=Base64Source(
                            data=base64.b64encode(b"\x01\x02").decode(
                                "ascii",
                            ),
                            media_type="audio/pcm",
                        ),
                    ),
                ],
            ),
        ]

        for chunk in chunks:
            accumulator.append_chat_response(chunk)
            accumulator.id = chunk.id

        response = accumulator.build()

        self.assertTrue(response.is_last)
        self.assertEqual(response.id, "response-id")
        self.assertIs(response.usage, usage)
        self.assertEqual(len(response.content), 4)

        thinking, text, tool_call, audio = response.content
        self.assertIsInstance(thinking, ThinkingBlock)
        self.assertEqual(thinking.thinking, "先想")
        self.assertEqual(thinking.signature, "provider-signature")
        self.assertIsInstance(text, TextBlock)
        self.assertEqual(text.text, "答案")
        self.assertIsInstance(tool_call, ToolCallBlock)
        self.assertEqual(tool_call.name, "calculator")
        self.assertEqual(tool_call.input, '{"x":1}')
        self.assertIsInstance(audio, DataBlock)
        self.assertIsInstance(audio.source, Base64Source)
        self.assertEqual(
            base64.b64decode(audio.source.data),
            b"\x00\x01\x02",
        )

    def test_non_audio_data_block_uses_latest_complete_asset(self) -> None:
        accumulator = _StreamAccumulator()
        for raw_data in (b"old", b"new"):
            accumulator.append_chat_response(
                ChatResponse(
                    is_last=False,
                    content=[
                        DataBlock(
                            id="image",
                            source=Base64Source(
                                data=base64.b64encode(raw_data).decode(
                                    "ascii",
                                ),
                                media_type="image/png",
                            ),
                        ),
                    ],
                ),
            )

        image = accumulator.build().content[0]
        self.assertIsInstance(image, DataBlock)
        self.assertIsInstance(image.source, Base64Source)
        self.assertEqual(base64.b64decode(image.source.data), b"new")


class _StreamingTestModel(ChatModelBase):
    """Small deterministic model used to exercise the public stream wrapper."""

    async def _call_api(
        self,
        model_name: str,
        messages: list,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        async def _chunks() -> AsyncGenerator[ChatResponse, None]:
            yield ChatResponse(
                id="stream-id",
                is_last=False,
                content=[TextBlock(id="text", text="完成")],
            )
            yield ChatResponse(
                id="stream-id",
                is_last=False,
                content=[],
                usage=ChatUsage(
                    input_tokens=3,
                    output_tokens=2,
                    time=0.1,
                ),
            )

        return _chunks()


class StreamingModelWrapperTest(IsolatedAsyncioTestCase):
    """Ensure usage-only carrier chunks stay internal to the wrapper."""

    async def test_usage_carrier_is_hidden_and_final_response_keeps_usage(
        self,
    ) -> None:
        model = _StreamingTestModel(
            credential=CredentialBase(),
            model="test",
            parameters=_StreamingTestModel.Parameters(),
            stream=True,
            max_retries=0,
        )

        stream = await model(
            [UserMsg(name="user", content="test")],
        )
        self.assertNotIsInstance(stream, ChatResponse)
        chunks = [chunk async for chunk in stream]

        self.assertEqual(len(chunks), 2)
        self.assertFalse(chunks[0].is_last)
        self.assertTrue(chunks[1].is_last)
        self.assertEqual(chunks[1].id, "stream-id")
        self.assertEqual(chunks[1].content[0].text, "完成")
        self.assertEqual(chunks[1].usage.input_tokens, 3)
        self.assertEqual(chunks[1].usage.output_tokens, 2)


class _MutationProbeTool(ToolBase):
    name = "MutationProbe"
    description = "Record permission and execution inputs."
    input_schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    is_concurrency_safe = True
    is_read_only = False
    is_external_tool = False
    is_mcp = False

    def __init__(self) -> None:
        super().__init__()
        self.permission_values: list[str] = []
        self.execution_values: list[str] = []

    async def check_permissions(
        self,
        tool_input: dict,
        context: PermissionContext,
    ) -> PermissionDecision:
        self.permission_values.append(tool_input["value"])
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="allowed",
        )

    async def call(self, value: str) -> ToolChunk:
        self.execution_values.append(value)
        return ToolChunk(content=[TextBlock(text=value)])


class _RoundCountingModel:
    """Deterministic two-response model for iteration accounting."""

    model = "round-counting-model"
    context_size = 100_000

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses
        self.call_count = 0

    async def __call__(self, **_: Any) -> ChatResponse:
        response = self._responses[self.call_count]
        self.call_count += 1
        return response

    async def count_tokens(self, *_: Any, **__: Any) -> int:
        return 1


class AgentIterationAccountingBackportTest(IsolatedAsyncioTestCase):
    """Reasoning plus its tool execution should consume one round."""

    async def test_tool_round_allows_final_reasoning_at_max_iters_two(
        self,
    ) -> None:
        tool = _MutationProbeTool()
        model = _RoundCountingModel(
            [
                ChatResponse(
                    content=[
                        ToolCallBlock(
                            id="round-tool-call",
                            name=tool.name,
                            input='{"value":"original"}',
                        ),
                    ],
                    is_last=True,
                ),
                ChatResponse(
                    content=[TextBlock(text="done")],
                    is_last=True,
                ),
            ],
        )
        agent = Agent(
            name="worker",
            system_prompt="test",
            model=model,
            toolkit=Toolkit(tools=[tool]),
            react_config=ReActConfig(max_iters=2),
            injection_config=InjectionConfig(inject_runtime_state=False),
        )

        reply = await agent.reply(UserMsg(name="user", content="run"))

        self.assertEqual(reply.finished_reason, "completed")
        self.assertEqual(
            [block.text for block in reply.get_content_blocks("text")],
            ["done"],
        )
        self.assertEqual(model.call_count, 2)
        self.assertEqual(agent.state.cur_iter, 2)
        self.assertEqual(tool.execution_values, ["original"])


class _MutatingPermissionMiddleware(MiddlewareBase):
    async def on_check_permission(
        self,
        agent: Agent,
        input_kwargs: dict,
        next_handler,
    ) -> PermissionDecision:
        input_kwargs["tool_input"]["value"] = "middleware-copy"
        input_kwargs["tool_call"].input = '{"value":"middleware-copy"}'
        return await next_handler(**input_kwargs)


class PermissionMiddlewareIsolationTest(IsolatedAsyncioTestCase):
    """Permission hooks may inspect copies but cannot rewrite execution."""

    async def test_middleware_mutation_does_not_change_tool_invocation(
        self,
    ) -> None:
        tool = _MutationProbeTool()
        tool_call = ToolCallBlock(
            id="tool-call",
            name=tool.name,
            input='{"value":"original"}',
        )
        agent = Agent(
            name="worker",
            system_prompt="test",
            model=SimpleNamespace(
                count_tokens=AsyncMock(return_value=1),
            ),
            toolkit=Toolkit(tools=[tool]),
            state=AgentState(
                context=[
                    UserMsg(name="user", content="run"),
                    AssistantMsg(name="worker", content=[tool_call]),
                ],
            ),
            middlewares=[_MutatingPermissionMiddleware()],
        )

        events = [
            event async for event in agent._execute_tool_call(tool_call)
        ]

        self.assertEqual(tool.permission_values, ["middleware-copy"])
        self.assertEqual(tool.execution_values, ["original"])
        self.assertEqual(tool_call.input, '{"value":"original"}')
        self.assertTrue(
            any(isinstance(event, ToolResultEndEvent) for event in events),
        )


class ExternalToolInterruptBackportTest(IsolatedAsyncioTestCase):
    """Keep an external tool's event lifecycle balanced on interruption."""

    async def test_submitted_call_does_not_emit_duplicate_start(self) -> None:
        tool_call = ToolCallBlock(
            id="external-tool-call",
            name="ExternalTool",
            input="{}",
            state=ToolCallState.SUBMITTED,
        )
        agent = Agent(
            name="worker",
            system_prompt="test",
            model=SimpleNamespace(
                count_tokens=AsyncMock(return_value=1),
            ),
            toolkit=Toolkit(tools=[]),
            state=AgentState(
                context=[
                    AssistantMsg(name="worker", content=[tool_call]),
                ],
            ),
        )

        events = [
            event async for event in agent._close_unfinished_tool_calls()
        ]

        self.assertFalse(
            any(isinstance(event, ToolResultStartEvent) for event in events),
        )
        self.assertEqual(
            sum(isinstance(event, ToolResultEndEvent) for event in events),
            1,
        )
        self.assertEqual(tool_call.state, ToolCallState.FINISHED)
        tool_results = agent.state.context[-1].get_content_blocks(
            "tool_result",
        )
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0].id, tool_call.id)
