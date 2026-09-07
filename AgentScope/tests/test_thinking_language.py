"""Platform thinking-language instructions through native AgentScope hooks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentscope.agent import Agent
from agentscope.app.middleware import ThinkingLanguageMiddleware
from agentscope.app.middleware._thinking_language_middleware import (
    THINKING_LANGUAGE_INSTRUCTION,
)
from agentscope.middleware import MiddlewareBase
from agentscope.tool import Toolkit


class ExtraPromptMiddleware(MiddlewareBase):
    async def on_system_prompt(self, agent, current_prompt):
        return current_prompt + "\nRead is a file tool; retain its schema."


@pytest.mark.asyncio
async def test_language_rule_reaches_native_agent_prompt_after_other_instructions():
    model = SimpleNamespace(count_tokens=AsyncMock(return_value=1))
    agent = Agent(
        name="Dobby", system_prompt="项目资料助手，只读取用户授权资料。",
        model=model, toolkit=Toolkit(),
        middlewares=[ExtraPromptMiddleware(), ThinkingLanguageMiddleware()],
    )
    prompt = await agent._get_system_prompt()
    assert prompt.startswith("项目资料助手，只读取用户授权资料。")
    assert "Read is a file tool" in prompt
    assert prompt.endswith(THINKING_LANGUAGE_INSTRUCTION)
    assert "必须使用简体中文" in prompt
    assert "标识符" in prompt
    assert "最终答复的语言继续遵循用户需求" in prompt
    assert await agent._get_system_prompt() == prompt
    assert agent._system_prompt == "项目资料助手，只读取用户授权资料。"


@pytest.mark.asyncio
async def test_repeated_prompt_hook_does_not_duplicate_language_instruction():
    middleware = ThinkingLanguageMiddleware()
    prompt = await middleware.on_system_prompt(None, "原始业务要求")
    assert await middleware.on_system_prompt(None, prompt) == prompt


@pytest.mark.asyncio
async def test_native_sessions_without_platform_middleware_keep_their_language():
    agent = Agent(
        name="standalone", system_prompt="Respond in English.",
        model=SimpleNamespace(count_tokens=AsyncMock(return_value=1)), toolkit=Toolkit(),
    )
    assert await agent._get_system_prompt() == "Respond in English."
