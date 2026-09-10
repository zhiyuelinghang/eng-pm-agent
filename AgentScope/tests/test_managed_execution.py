"""Exercise product execution policy with deterministic models and real tools."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from agentscope.agent import Agent, ExecutionPolicy, InjectionConfig, ReActConfig
from agentscope.agent._execution import ExecutionGuard
from agentscope.message import TextBlock, ThinkingBlock, ToolCallBlock, ToolResultBlock, UserMsg
from agentscope.model import ChatResponse
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.state import AgentState
from agentscope.tool import ToolBase, ToolChunk, Toolkit


class Probe(ToolBase):
    name = "progress_probe"
    description = "Return the requested item."
    input_schema = {"type": "object", "properties": {"item": {"type": "integer"}}, "required": ["item"]}
    is_concurrency_safe = True
    is_read_only = True
    is_external_tool = False
    is_mcp = False

    def __init__(self, failing=False, changing=False):
        super().__init__()
        self.calls = []
        self.failing, self.changing = failing, changing

    async def check_permissions(self, tool_input, context):
        return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="allowed")

    async def call(self, item: int) -> ToolChunk:
        self.calls.append(item)
        return ToolChunk(
            content=[TextBlock(text=str(len(self.calls) if self.changing else item))],
            state="error" if self.failing else "success",
        )


class Model:
    model = "test"
    context_size = 100000

    def __init__(self, items, *, ignore_stop=False, thinking_only=False):
        self.items = items
        self.calls = 0
        self.ignore_stop = ignore_stop
        self.thinking_only = thinking_only

    async def count_tokens(self, *args, **kwargs):
        return 1

    async def __call__(self, **kwargs):
        index = self.calls
        self.calls += 1
        choice = kwargs.get("tool_choice")
        if choice and choice.mode == "none" and not self.ignore_stop:
            return ChatResponse(content=[TextBlock(text="已保留成果，仍有工作未完成。")], is_last=True)
        if self.thinking_only:
            return ChatResponse(content=[ThinkingBlock(thinking="继续分析")], is_last=True)
        if index >= len(self.items):
            return ChatResponse(content=[TextBlock(text="完成")], is_last=True)
        return ChatResponse(content=[ToolCallBlock(
            id=f"call-{index}", name=Probe.name, input=f'{{"item":{self.items[index]}}}',
        )], is_last=True)


def make_agent(model, probe=None, policy=None):
    return Agent(
        name="test", system_prompt="test", model=model,
        toolkit=Toolkit(tools=[probe or Probe()]),
        react_config=ReActConfig(max_iters=2),  # A stale saved limit must not stop managed runs.
        execution_policy=policy or ExecutionPolicy(),
        injection_config=InjectionConfig(inject_runtime_state=False),
    )


class ManagedExecutionTest(IsolatedAsyncioTestCase):
    async def test_plain_text_cannot_escape_structured_output_protection(self):
        model = Model([])
        result = await make_agent(model).reply(
            UserMsg(name="user", content="run"),
            structured_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
        )
        self.assertEqual(result.finished_reason, "error")
        self.assertEqual(model.calls, 7)

    async def test_valid_structured_output_finishes_normally(self):
        class StructuredModel(Model):
            async def __call__(self, **kwargs):
                return ChatResponse(content=[ToolCallBlock(
                    id="structured", name="GenerateStructuredOutput", input='{"answer":"完成"}',
                )], is_last=True)
        result = await make_agent(StructuredModel([])).reply(
            UserMsg(name="user", content="run"),
            structured_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
        )
        self.assertEqual(result.finished_reason, "completed")
        self.assertEqual(result.structured_output, {"answer": "完成"})

    async def test_truncated_text_is_continued_and_combined(self):
        class SequenceModel(Model):
            async def __call__(self, **kwargs):
                self.calls += 1
                return ChatResponse(
                    content=[TextBlock(text="第一部分。" if self.calls == 1 else "第二部分。")],
                    is_last=True, metadata={"output_truncated": self.calls == 1},
                )
        model = SequenceModel([])
        result = await make_agent(model).reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "completed")
        self.assertEqual("".join(block.text for block in result.get_content_blocks("text")), "第一部分。第二部分。")
        self.assertEqual(model.calls, 2)

    async def test_partial_tool_arguments_are_never_executed(self):
        class SequenceModel(Model):
            async def __call__(self, **kwargs):
                result = await super().__call__(**kwargs)
                if self.calls == 1:
                    result.metadata["output_truncated"] = True
                return result
        probe = Probe()
        agent = make_agent(SequenceModel([1, 2]), probe)
        result = await agent.reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "completed")
        self.assertEqual(probe.calls, [2])
        self.assertFalse(agent.state.get_unfinished_tool_calls(agent.name))

    async def test_progress_runs_past_twenty_rounds(self):
        probe, model = Probe(), Model(list(range(25)))
        agent = make_agent(model, probe)
        result = await agent.reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "completed")
        self.assertEqual(probe.calls, list(range(25)))

    async def test_repeated_results_stop_and_new_turn_starts_fresh(self):
        probe, model = Probe(), Model([1] * 100)
        agent = make_agent(model, probe)
        result = await agent.reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "error")
        self.assertEqual(len(probe.calls), 7)
        agent.model = Model([2])
        result = await agent.reply(UserMsg(name="user", content="new"))
        self.assertEqual(result.finished_reason, "completed")
        self.assertEqual(probe.calls[-1], 2)

    async def test_same_query_with_changing_result_is_progress(self):
        probe = Probe(changing=True)
        result = await make_agent(Model([1] * 25), probe).reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "completed")
        self.assertEqual(len(probe.calls), 25)

    async def test_failed_rounds_are_bounded_even_when_arguments_change(self):
        probe = Probe(failing=True)
        result = await make_agent(Model(list(range(100))), probe).reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "error")
        self.assertEqual(len(probe.calls), 6)

    async def test_finalizer_cannot_execute_rogue_tool_calls(self):
        probe = Probe()
        agent = make_agent(Model([1] * 100, ignore_stop=True), probe)
        result = await agent.reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "error")
        self.assertEqual(len(probe.calls), 7)
        self.assertFalse(agent.state.get_unfinished_tool_calls(agent.name))

    async def test_empty_reasoning_does_not_spin_forever(self):
        model = Model([], thinking_only=True)
        result = await make_agent(model).reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "error")
        self.assertEqual(model.calls, 7)

    async def test_emergency_ceiling_returns_partial_status(self):
        probe = Probe()
        result = await make_agent(Model(list(range(10))), probe, ExecutionPolicy(max_rounds=3)).reply(UserMsg(name="user", content="run"))
        self.assertEqual(result.finished_reason, "error")
        self.assertEqual(probe.calls, [0, 1, 2])


class GuardPersistenceTest(TestCase):
    def test_approval_wait_does_not_consume_active_budget(self):
        state = AgentState()
        guard = ExecutionGuard(ExecutionPolicy(max_active_seconds=10), state)
        with patch("agentscope.agent._execution.monotonic", side_effect=[0, 2, 1000, 1003]):
            guard.resume()
            guard.park()
            restored = AgentState.model_validate_json(state.model_dump_json())
            resumed = ExecutionGuard(guard.policy, restored)
            resumed.resume()
            self.assertIsNone(resumed.stop_reason())
        self.assertEqual(resumed.data["elapsed"], 5)

    def test_alternating_loop_is_detected_after_state_reload(self):
        state = AgentState()
        guard = ExecutionGuard(ExecutionPolicy(), state)
        for index in range(8):
            item = index % 2
            guard.record_round(
                [ToolCallBlock(id=str(index), name="read", input=f'{{"item":{item}}}')],
                [ToolResultBlock(id=str(index), name="read", output=str(item), state="success")], {},
            )
        restored = ExecutionGuard(guard.policy, AgentState.model_validate_json(state.model_dump_json()))
        self.assertIn("重复", restored.stop_reason())


class ManagedModelTest(IsolatedAsyncioTestCase):
    async def test_compatible_endpoint_uses_legacy_token_field_and_negotiates_only_rejected_shape(self):
        import httpx
        from openai import BadRequestError
        from agentscope.credential import CustomOpenAICredential
        from agentscope.model._openai_chat._model import OpenAIChatModel
        model = object.__new__(OpenAIChatModel)
        model.credential = CustomOpenAICredential(api_key="test", base_url="https://example.com/v1")
        model.parameters = OpenAIChatModel.Parameters(max_tokens=32000)
        model.stream, model.extra_body, model.request_body_overrides = True, None, {}
        model.formatter = SimpleNamespace(format=AsyncMock(return_value=[]))
        rejected = BadRequestError(
            "Unsupported parameter", response=httpx.Response(400, request=httpx.Request("POST", "https://example.com")),
            body={"param": "max_tokens", "code": "unsupported_parameter"},
        )
        create = AsyncMock(side_effect=[rejected, object()])
        model.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        await model._call_api("test", [], None, None)
        self.assertEqual(create.await_args_list[0].kwargs["max_tokens"], 32000)
        self.assertNotIn("max_completion_tokens", create.await_args_list[0].kwargs)
        self.assertEqual(create.await_args_list[1].kwargs["max_completion_tokens"], 32000)
        self.assertNotIn("max_tokens", create.await_args_list[1].kwargs)

        rejected = BadRequestError(
            "Invalid tools", response=httpx.Response(400, request=httpx.Request("POST", "https://example.com")),
            body={"param": "tools", "code": "invalid_request_error"},
        )
        create.reset_mock(side_effect=True)
        create.side_effect = rejected
        with self.assertRaises(BadRequestError):
            await model._call_api("test", [], None, None)
        create.assert_awaited_once()

    async def test_checkpoint_is_throttled_and_retains_state(self):
        from agentscope.app._service._run_checkpoint import RunCheckpoint
        storage = SimpleNamespace(upsert_message=AsyncMock(), update_session_state=AsyncMock())
        agent = make_agent(Model([]))
        agent.state.cur_iter = 1
        reply = UserMsg(name="test", content="progress")
        with patch("agentscope.app._service._run_checkpoint.monotonic", side_effect=[0, 29, 30, 40]):
            checkpoint = RunCheckpoint(storage, "user", "agent", "session")
            await checkpoint.save(agent, reply)
            storage.update_session_state.assert_not_awaited()
            await checkpoint.save(agent, reply)
            await checkpoint.save(agent, reply)
        storage.update_session_state.assert_awaited_once()
        self.assertIs(storage.update_session_state.await_args.kwargs["state"], agent.state)

    async def test_streaming_length_marker_survives_an_empty_finish_chunk(self):
        from datetime import datetime
        from agentscope.model._deepseek._model import DeepSeekChatModel
        from agentscope.model._utils import _StreamAccumulator
        class Stream:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def __aiter__(self):
                for content, finish in [("部分", None), (None, "length")]:
                    yield SimpleNamespace(id="test", usage=None, choices=[SimpleNamespace(
                        finish_reason=finish,
                        delta=SimpleNamespace(content=content, reasoning_content=None, tool_calls=None),
                    )])
        model = object.__new__(DeepSeekChatModel)
        accumulator = _StreamAccumulator()
        async for chunk in model._parse_stream_response(datetime.now(), Stream()):
            accumulator.append_chat_response(chunk)
        self.assertTrue(accumulator.build().metadata["output_truncated"])

    async def test_output_allowance_can_grow_again_after_compression(self):
        from agentscope.app.middleware._managed_model_middleware import ManagedModelMiddleware
        model = SimpleNamespace(
            _managed_output_limit=32000, context_size=64000,
            parameters=SimpleNamespace(max_tokens=None),
        )
        async def count_tokens(*args):
            return model.used
        model.count_tokens = count_tokens
        async def downstream(**kwargs):
            return kwargs["current_model"].parameters.max_tokens
        kwargs = {"current_model": model, "messages": [], "tools": []}
        model.used = 60000
        middleware = ManagedModelMiddleware()
        self.assertEqual(await middleware.on_model_call(None, kwargs, downstream), 2976)
        model.used = 1000
        self.assertEqual(await middleware.on_model_call(None, kwargs, downstream), 32000)

    async def test_model_selection_uses_shared_parameters_without_mutating_records(self):
        from agentscope.app._service._model import managed_chat_model_config
        from agentscope.app.storage import ChatModelConfig
        old = ChatModelConfig(type="custom_openai_credential", credential_id="test", model="test", parameters={"max_tokens": 128})
        self.assertEqual(managed_chat_model_config(old).parameters, {})
        self.assertEqual(old.parameters, {"max_tokens": 128})
