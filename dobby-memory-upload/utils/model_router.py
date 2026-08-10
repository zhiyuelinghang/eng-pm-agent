"""
ModelRouter — 按调用意图自动选择 deepseek-v4-flash 或 deepseek-v4-pro。

参考：agentica AuxiliaryModelRouter（三级优先级） +
      LightRAG 角色级模型配置（继承模式）

Usage:
    router = ModelRouter()
    router.resolve("routing")    # → "deepseek-v4-flash"
    router.resolve("synthesize") # → "deepseek-v4-pro"
    router.resolve(None)         # → "deepseek-v4-flash" (向后兼容)
"""

from __future__ import annotations

from . import config as _cfg


class ModelRouter:
    """根据调用意图自动选择模型。

    核心原则：用户可见 → pro；系统内部后台 → flash。
    """

    # 使用 pro 的任务（用户直接看到的回答）
    _PRO_TASKS: frozenset[str] = frozenset({
        "respond",       # 角色节点回答（inject 或 tool 模式）
        "synthesize",    # 多角色结果合成最终回答
    })

    def __init__(
        self,
        flash_model: str = "",
        pro_model: str = "",
    ):
        self.flash_model = flash_model or _cfg.LLM_FLASH_MODEL
        self.pro_model = pro_model or _cfg.LLM_PRO_MODEL

    def resolve(self, intent: str | None = None) -> str:
        """返回模型名。

        Args:
            intent: 调用意图标识。None → flash（向后兼容）。

        Returns:
            "deepseek-v4-flash" 或 "deepseek-v4-pro"
        """
        if intent is None:
            return self.flash_model
        if intent in self._PRO_TASKS:
            return self.pro_model
        return self.flash_model
