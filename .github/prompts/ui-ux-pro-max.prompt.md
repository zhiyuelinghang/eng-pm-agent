---
mode: agent
description: UI/UX Pro Max —— 含 67 种风格、161 行业规则、配色/字体/交互建议的设计判断层，用于构建或改进 React/Vue/Next.js/Tailwind/shadcn 等前端界面。
---

# UI/UX Pro Max 工作流入口

用户用 `/ui-ux-pro-max` 触发本命令来做 UI/UX 工作（构建、设计、实现、审查、修复、改进界面）。

请先完整阅读工作流定义文件，然后严格按其中的步骤执行：

[.github/prompts/ui-ux-pro-max/PROMPT.md](./ui-ux-pro-max/PROMPT.md)

该文件描述了一个基于本地知识库的检索式设计流程：

- 数据库（CSV）位于 `.github/prompts/ui-ux-pro-max/data/`
- 检索脚本位于 `.github/prompts/ui-ux-pro-max/scripts/search.py`（需 Python 3）
- 按「分析需求 → 检索风格/配色/字体/行业规则 → 生成设计系统 → 实现代码 → 交付前检查」的顺序工作

执行约定：

- 如需使用该工作流，先以用户给出的新产品方向和当前代码实际结构为准。
- 文件读写、远程路径和端口转发规则以 [.github/copilot-instructions.md](../copilot-instructions.md) 为准。

用户的具体需求：${input:需求描述}
