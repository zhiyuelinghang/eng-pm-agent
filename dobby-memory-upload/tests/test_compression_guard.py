"""Tests for compression quality guard (death-spiral prevention)."""
import pytest
from utils.compression_guard import CompressionGuard, CompressionDecision


class TestCompressionGuard:
    def test_pass_on_normal(self):
        """正常情况 → compress"""
        g = CompressionGuard()
        state = {"last_compress_round": 0, "message_count": 10}
        d = g.decide([], state)
        assert d.action == "compress"

    def test_trim_only_on_low_quality(self):
        """质量分低于阈值 → trim_only"""
        g = CompressionGuard()
        g.record_quality(0.2)  # below 0.3 threshold
        g.record_quality(0.1)
        g.on_compress()  # count=1
        state = {"last_compress_round": 0, "message_count": 10}
        d = g.decide([], state)
        assert d.action == "trim_only"

    def test_reset_on_three_consecutive(self):
        """连续3次压缩 → reset"""
        g = CompressionGuard()
        g.on_compress()
        g.on_compress()
        g.on_compress()  # count=3
        state = {"last_compress_round": 0, "message_count": 100}
        d = g.decide([], state)
        assert d.action == "reset"

    def test_trim_only_on_insufficient_interval(self):
        """压缩间隔不足 → trim_only"""
        g = CompressionGuard()
        g.on_compress()  # count=1
        state = {"last_compress_round": 96, "message_count": 100}  # only 4 rounds since (< 5)
        d = g.decide([], state)
        assert d.action == "trim_only"

    def test_on_reset_clears_state(self):
        """reset 后计数器归零"""
        g = CompressionGuard()
        g.on_compress()
        g.on_compress()
        g.on_reset()
        assert g._compress_count == 0
        assert g._quality_scores == []

    def test_quality_score_cap(self):
        """质量分保留最近5个"""
        g = CompressionGuard()
        for i in range(10):
            g.record_quality(float(i) / 10)
        assert len(g._quality_scores) == 5
        assert g._quality_scores == [0.5, 0.6, 0.7, 0.8, 0.9]
