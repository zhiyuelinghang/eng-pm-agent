# -*- coding: utf-8 -*-
"""Language instruction for provider-exposed thinking in platform sessions."""

from typing import TYPE_CHECKING

from ...middleware import MiddlewareBase

if TYPE_CHECKING:
    from ...agent import Agent


THINKING_LANGUAGE_INSTRUCTION = """【平台思考语言要求】
模型原本提供的可见思考内容（thinking / reasoning）必须使用简体中文。
即使系统中的工具说明、历史思考、检索资料或用户输入包含英文，思考中的自然语言说明仍使用简体中文。
工具名称、代码、路径、字段名、标识符及必须原样引用的内容保持原文，不翻译协议字段，不改变工具参数。
这项要求仅约束可见思考的语言，不要求额外生成思考内容，也不要把思考过程复制到最终答复中。
最终答复的语言继续遵循用户需求和原有业务要求。"""


class ThinkingLanguageMiddleware(MiddlewareBase):
    """Use AgentScope's prompt hook without altering reasoning or its output.

    This is a model instruction, not a provider-level language guarantee.
    Keeping the original response intact also preserves reasoning replay.
    """

    async def on_system_prompt(
        self,
        agent: "Agent",
        current_prompt: str,
    ) -> str:
        if THINKING_LANGUAGE_INSTRUCTION in current_prompt:
            return current_prompt
        return f"{current_prompt}\n\n{THINKING_LANGUAGE_INSTRUCTION}"
