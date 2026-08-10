"""Tests for auto-hints background retrieval."""
import pytest
import asyncio
from unittest.mock import MagicMock, patch

from utils.auto_hints import AutoHinter, HINT_TEMPLATE


class TestAutoHinter:
    def test_default_attributes(self):
        """AutoHinter initializes with correct default values."""
        hinter = AutoHinter()
        assert hinter.threshold == 0.65
        assert hinter.max_hints == 2
        assert hinter.max_chars == 120
        assert hinter.timeout == 0.5

    def test_custom_attributes(self):
        """AutoHinter accepts custom constructor arguments."""
        hinter = AutoHinter(
            hint_threshold=0.8,
            max_hints=3,
            max_chars_per_hint=200,
            timeout=1.0,
        )
        assert hinter.threshold == 0.8
        assert hinter.max_hints == 3
        assert hinter.max_chars == 200
        assert hinter.timeout == 1.0

    @pytest.mark.asyncio
    async def test_returns_empty_on_timeout(self):
        """When retrieval exceeds timeout, returns empty string."""
        hinter = AutoHinter(hint_threshold=0.65, timeout=0.001)

        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = []

        mock_weknora = MagicMock()
        mock_weknora.hybrid_search.return_value = []

        # Mock asyncio.to_thread to simulate a slow operation
        async def slow_to_thread(fn, *args, **kwargs):
            await asyncio.sleep(0.1)  # longer than hinter.timeout of 0.001s
            return fn()

        with patch("utils.auto_hints.asyncio.to_thread", side_effect=slow_to_thread):
            result = await hinter.get_hints(
                "query", mock_mem0, mock_weknora, "kb1", "proj1"
            )

        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_hints_when_above_threshold(self):
        """Results with score >= threshold produce formatted hint text."""
        hinter = AutoHinter(hint_threshold=0.5)

        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = [
            {"memory": "上次讨论决定使用PostgreSQL", "score": 0.8},
        ]

        mock_weknora = MagicMock()
        mock_weknora.hybrid_search.return_value = [
            {"content": "GB50300-2025 验收标准", "score": 0.7},
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            return fn()

        with patch("utils.auto_hints.asyncio.to_thread", side_effect=fake_to_thread):
            result = await hinter.get_hints(
                "数据库方案", mock_mem0, mock_weknora, "kb1", "proj1"
            )

        assert "<auto-hint>" in result
        assert "PostgreSQL" in result
        assert "GB50300" in result
        assert "上次讨论" in result
        assert "验收标准" in result

    @pytest.mark.asyncio
    async def test_empty_when_no_results_above_threshold(self):
        """All results below threshold return empty string."""
        hinter = AutoHinter(hint_threshold=0.9)

        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = [
            {"memory": "some memory", "score": 0.3},
        ]

        mock_weknora = MagicMock()
        mock_weknora.hybrid_search.return_value = [
            {"content": "some kb content", "score": 0.2},
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            return fn()

        with patch("utils.auto_hints.asyncio.to_thread", side_effect=fake_to_thread):
            result = await hinter.get_hints(
                "query", mock_mem0, mock_weknora, "kb1", "p1"
            )

        assert result == ""

    @pytest.mark.asyncio
    async def test_truncates_long_content(self):
        """Content longer than max_chars is truncated."""
        hinter = AutoHinter(hint_threshold=0.5, max_chars_per_hint=10)

        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = [
            {"memory": "A" * 100, "score": 0.8},
        ]

        mock_weknora = MagicMock()
        mock_weknora.hybrid_search.return_value = []

        async def fake_to_thread(fn, *args, **kwargs):
            return fn()

        with patch("utils.auto_hints.asyncio.to_thread", side_effect=fake_to_thread):
            result = await hinter.get_hints(
                "query", mock_mem0, mock_weknora, "kb1", "p1"
            )

        assert "<auto-hint>" in result
        assert "[memory" in result
        # After truncation, the actual content part should be at most max_chars
        # Format: "  · [memory s=0.80] AAAAA..."
        # The content after "] " should be at most 10 chars
        assert "AAAAAAAAAA" in result  # 10 A's (truncated)
        assert "A" * 11 not in result   # should not have 11 consecutive A's

    @pytest.mark.asyncio
    async def test_limits_to_max_hints(self):
        """Only returns up to max_hints snippets."""
        hinter = AutoHinter(hint_threshold=0.5, max_hints=2)

        mock_mem0 = MagicMock()
        mock_mem0.search.return_value = [
            {"memory": "Memory A", "score": 0.9},
            {"memory": "Memory B", "score": 0.8},
        ]

        mock_weknora = MagicMock()
        mock_weknora.hybrid_search.return_value = [
            {"content": "KB Item 1", "score": 0.9},
            {"content": "KB Item 2", "score": 0.8},
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            return fn()

        with patch("utils.auto_hints.asyncio.to_thread", side_effect=fake_to_thread):
            result = await hinter.get_hints(
                "query", mock_mem0, mock_weknora, "kb1", "p1"
            )

        assert "<auto-hint>" in result
        # Count the "\u00b7" bullet points — should be at most max_hints (2)
        bullet_count = result.count("  \u00b7 ")
        assert bullet_count <= 2
        assert bullet_count > 0

    @pytest.mark.asyncio
    async def test_handles_exception_in_search(self):
        """When one search raises, the other still works (return_exceptions)."""
        hinter = AutoHinter(hint_threshold=0.5)

        mock_mem0 = MagicMock()
        mock_mem0.search.side_effect = RuntimeError("Mem0 is down")

        mock_weknora = MagicMock()
        mock_weknora.hybrid_search.return_value = [
            {"content": "KB still works", "score": 0.7},
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            # Let the exception propagate naturally — asyncio.gather
            # with return_exceptions=True will catch it
            return fn()

        with patch("utils.auto_hints.asyncio.to_thread", side_effect=fake_to_thread):
            result = await hinter.get_hints(
                "query", mock_mem0, mock_weknora, "kb1", "p1"
            )

        # KB results still appear even when mem0 fails
        assert "KB still works" in result
        assert "<auto-hint>" in result


class TestHintTemplate:
    def test_template_contains_required_parts(self):
        """HINT_TEMPLATE has the correct structure."""
        text = HINT_TEMPLATE.format(
            hints="  \u00b7 [memory] 上次讨论\n  \u00b7 [spec] GB50300"
        )
        assert "<auto-hint>" in text
        assert "search_memory" in text
        assert "search_knowledge_base" in text
        assert "上次讨论" in text
        assert "GB50300" in text

    def test_template_starts_with_opening_tag(self):
        """Format returns a proper hint block."""
        text = HINT_TEMPLATE.format(hints="  \u00b7 [memory] test")
        assert text.startswith("<auto-hint>")
        assert text.strip().endswith("</auto-hint>")
