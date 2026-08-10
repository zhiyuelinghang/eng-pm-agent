"""
Silent background retrieval with fragment injection for minimal context mode.

Magic Context reference: "Auto search hints" — postprocess phase runs ctx_search,
appends compact fragments when relevance exceeds threshold.

Only called in minimal mode. standard/full modes already have full retrieval.
500ms hard timeout — never blocks the main flow.

Usage:
    hinter = AutoHinter()
    hints = await hinter.get_hints(query, mem0_client, weknora_client, kb_id, pid)
    if hints:
        msgs.insert(1, _make_system(hints))
"""

from __future__ import annotations

import asyncio
from typing import Any


HINT_TEMPLATE = (
    "<auto-hint>\n"
    "The following memories/knowledge fragments may be relevant to the current question. "
    "Use search_memory or search_knowledge_base tools for full content:\n"
    "{hints}\n"
    "</auto-hint>\n"
)


class AutoHinter:
    """Background semantic search -> compact fragment injection.

    Args:
        hint_threshold: minimum relevance score to include (0-1)
        max_hints: maximum number of hint fragments
        max_chars_per_hint: maximum characters per fragment
        timeout: hard timeout in seconds for the entire retrieval
    """

    def __init__(
        self,
        hint_threshold: float = 0.65,
        max_hints: int = 2,
        max_chars_per_hint: int = 120,
        timeout: float = 0.5,
    ):
        self.threshold = hint_threshold
        self.max_hints = max_hints
        self.max_chars = max_chars_per_hint
        self.timeout = timeout

    async def get_hints(
        self,
        query: str,
        mem0_client: Any,
        weknora_client: Any,
        kb_id: str,
        project_id: str,
    ) -> str:
        """Run background search, return formatted hint text or empty string.

        Does NOT block the main flow — hard timeout via asyncio.wait_for.
        Returns "" on timeout, error, or no relevant results.

        Args:
            query: user query text
            mem0_client: Mem0 instance (has .search method)
            weknora_client: WeKnoraClient instance (has .hybrid_search method)
            kb_id: WeKnora knowledge base ID
            project_id: project identifier for Mem0 scoping

        Returns:
            Formatted <auto-hint> string, or "" if no relevant hits
        """
        try:
            mem0_task = asyncio.to_thread(
                lambda: mem0_client.search(
                    query,
                    filters={"user_id": project_id},
                    top_k=2,
                    threshold=self.threshold,
                )
            )
            kb_task = asyncio.to_thread(
                lambda: weknora_client.hybrid_search(
                    kb_id=kb_id,
                    query=query,
                    vector_threshold=self.threshold,
                    keyword_threshold=self.threshold * 0.8,
                    match_count=2,
                )
            )

            mem0_results, kb_results = await asyncio.wait_for(
                asyncio.gather(mem0_task, kb_task, return_exceptions=True),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            return ""

        # Collect snippets above threshold
        snippets: list[str] = []

        for r in (mem0_results if isinstance(mem0_results, list) else []):
            text = r.get("memory", str(r)) if isinstance(r, dict) else str(r)
            score = r.get("score", 0) if isinstance(r, dict) else 0
            if score >= self.threshold:
                snippets.append(
                    f"[memory s={score:.2f}] {text[:self.max_chars]}"
                )

        for r in (kb_results if isinstance(kb_results, list) else []):
            content = r.get("content", str(r)) if isinstance(r, dict) else str(r)
            score = r.get("score", 0) if isinstance(r, dict) else 0
            if score >= self.threshold:
                snippets.append(
                    f"[spec s={score:.2f}] {content[:self.max_chars]}"
                )

        if not snippets:
            return ""

        return HINT_TEMPLATE.format(
            hints="\n".join(f"  \u00b7 {s}" for s in snippets[:self.max_hints])
        )
