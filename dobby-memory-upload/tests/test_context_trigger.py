"""Tests for zero-latency context mode classifier."""
import pytest
from utils.context_trigger import classify


class TestClassify:
    def test_full_trigger_spec_keywords(self):
        """含规范关键词 → full"""
        assert classify("GB50300验收规范要求是什么") == "full"
        assert classify("这个整改需要什么标准") == "full"
        assert classify("风险评估和安全规程") == "full"

    def test_standard_trigger_task_keywords(self):
        """含进度/任务关键词 → standard"""
        assert classify("项目进度怎么样了") == "standard"
        assert classify("上周的周报发一下") == "standard"
        assert classify("巡检记录汇总") == "standard"

    def test_minimal_greeting(self):
        """简单问候 → minimal"""
        assert classify("你好") == "minimal"
        assert classify("谢谢") == "minimal"
        assert classify("好的") == "minimal"

    def test_minimal_empty(self):
        assert classify("") == "minimal"

    def test_user_explicit_search_force_full(self):
        """用户显式要求搜索 → full"""
        assert classify("帮我查一下上次讨论的结论") == "full"
        assert classify("搜索一下关于基坑的记忆") == "full"
        assert classify("回忆之前那个整改方案") == "full"

    def test_consecutive_minimal_limit(self):
        """连续5轮minimal → 第6轮强制standard"""
        from utils.context_trigger import _STATE_KEY
        state = {_STATE_KEY: 5}  # already at limit
        assert classify("好", state=state) == "standard"
        # After forced standard, counter should reset
        assert state[_STATE_KEY] == 0

    def test_consecutive_counter_increments(self):
        """追踪计数器正确递增"""
        from utils.context_trigger import _STATE_KEY
        state = {_STATE_KEY: 0}
        assert classify("好", state=state) == "minimal"
        assert state[_STATE_KEY] == 1
        assert classify("嗯", state=state) == "minimal"
        assert state[_STATE_KEY] == 2

    def test_full_resets_counter(self):
        """非minimal模式重置计数器"""
        from utils.context_trigger import _STATE_KEY
        state = {_STATE_KEY: 3}
        assert classify("规范查询", state=state) == "full"
        assert state[_STATE_KEY] == 0
