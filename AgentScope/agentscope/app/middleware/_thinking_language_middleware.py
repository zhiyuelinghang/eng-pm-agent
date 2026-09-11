# -*- coding: utf-8 -*-
"""Language instruction for provider-exposed thinking in platform sessions."""

from typing import TYPE_CHECKING

from ...middleware import MiddlewareBase

if TYPE_CHECKING:
    from ...agent import Agent


THINKING_LANGUAGE_INSTRUCTION = """【平台输出语言要求】
面向用户的自然语言默认全部使用简体中文，从本轮第一句话开始执行。
读取技能之前的开场说明、工具调用前后的进度说明、协同反馈和最终答复默认必须使用简体中文。
不得先用英文说明即将读取技能或制定流程再切回中文。例如应说“我先读取初始化流程，再核对附件资料。”
模型原本提供的可见思考内容（thinking / reasoning）必须使用简体中文。
即使系统中的工具说明、历史思考、检索资料或用户输入包含英文，思考中的自然语言说明仍使用简体中文。
工具名称、代码、路径、字段名、标识符及必须原样引用的内容保持原文，不翻译协议字段，不改变工具参数。
关于思考的要求只约束模型原本提供的可见思考，不要求额外生成思考，也不要把思考过程复制到最终答复中。
用户明确要求其他语言时，正文与最终答复遵循用户要求；不能因英文工具说明或历史英文进度而切换语言。"""


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
