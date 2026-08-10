"""Integration tests for event-driven consolidation trigger."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from utils.consolidation_engine import (
    _maybe_fire_consolidation,
    _count_pending_extracts,
    _cooldown_active,
    _touch_cooldown,
    _last_fire,
    ConsolidationEngine,
)


class TestCountPendingExtracts:
    @patch("utils.consolidation_engine._get_db_conn")
    def test_returns_count(self, mock_conn):
        mock_conn.return_value.execute.return_value.fetchone.return_value = (7,)
        count = asyncio.run(_count_pending_extracts("proj1", "procedure"))
        assert count == 7

    @patch("utils.consolidation_engine._get_db_conn")
    def test_returns_zero_when_none(self, mock_conn):
        mock_conn.return_value.execute.return_value.fetchone.return_value = (0,)
        count = asyncio.run(_count_pending_extracts("proj1", "procedure"))
        assert count == 0


class TestCooldown:
    def test_first_call_not_active(self):
        _last_fire.clear()
        assert _cooldown_active("proj1", "procedure") is False

    def test_within_cooldown(self):
        _last_fire.clear()
        _touch_cooldown("proj1", "procedure")
        assert _cooldown_active("proj1", "procedure", minutes=30) is True

    def test_different_bucket_not_affected(self):
        _last_fire.clear()
        _touch_cooldown("proj1", "procedure")
        assert _cooldown_active("proj1", "decision", minutes=30) is False

    def test_different_project_not_affected(self):
        _last_fire.clear()
        _touch_cooldown("proj1", "procedure")
        assert _cooldown_active("proj2", "procedure", minutes=30) is False


class TestMaybeFireConsolidation:
    @patch("utils.consolidation_engine._count_pending_extracts")
    def test_below_threshold_skips(self, mock_count):
        _last_fire.clear()
        mock_count.return_value = 3  # < MIN_CLUSTER_SIZE (5)
        with patch("utils.consolidation_engine.ConsolidationEngine") as mock_engine:
            asyncio.run(_maybe_fire_consolidation("proj1", "procedure"))
        mock_engine.assert_not_called()

    @patch("utils.consolidation_engine._count_pending_extracts")
    def test_above_threshold_triggers(self, mock_count):
        _last_fire.clear()
        mock_count.return_value = 6  # >= MIN_CLUSTER_SIZE (5)
        with patch("utils.consolidation_engine.ConsolidationEngine") as mock_engine:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock()
            mock_engine.return_value = mock_instance

            asyncio.run(_maybe_fire_consolidation("proj1", "procedure"))

        mock_engine.assert_called_once()

    @patch("utils.consolidation_engine._count_pending_extracts")
    def test_cooldown_blocks(self, mock_count):
        _last_fire.clear()
        _touch_cooldown("proj1", "procedure")  # mark as just fired
        mock_count.return_value = 10
        with patch("utils.consolidation_engine.ConsolidationEngine") as mock_engine:
            asyncio.run(_maybe_fire_consolidation("proj1", "procedure"))
        mock_engine.assert_not_called()
