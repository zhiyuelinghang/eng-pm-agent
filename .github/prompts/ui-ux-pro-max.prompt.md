---
agent: "agent"
description: UI/UX Pro Max - searchable design workflow for building, reviewing, and improving frontend interfaces with local style, color, typography, UX, chart, and stack guidance.
---

# UI/UX Pro Max Workflow Entry

Use this prompt when the user invokes `/ui-ux-pro-max` for UI/UX work such as designing, building, reviewing, fixing, or improving a frontend interface.

First read the workflow definition file, then follow its steps:

[.github/prompts/ui-ux-pro-max/PROMPT.md](./ui-ux-pro-max/PROMPT.md)

The workflow uses a local searchable design knowledge base:

- CSV data: `.github/prompts/ui-ux-pro-max/data/`
- Search scripts: `.github/prompts/ui-ux-pro-max/scripts/`
- Python 3 is required for running the search scripts.

User request: ${input:request}
