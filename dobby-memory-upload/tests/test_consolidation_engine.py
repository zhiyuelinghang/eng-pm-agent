"""Unit tests for ConsolidationEngine."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import numpy as np

from utils.consolidation_engine import (
    ConsolidationEngine,
    ConsolidationResult,
    MemoryItem,
    _cosine,
    _parse_emb,
    _make_slug,
)


class TestMemoryItem:
    def test_defaults(self):
        item = MemoryItem(id="1", bucket="procedure", content="test", importance=0.5, recall_count=0)
        assert item.recall_count == 0
        assert item.embedding is None

    def test_from_extract_row(self):
        item = MemoryItem(
            id="uuid-1", bucket="decision", content="用选项卡而非下拉框",
            importance=0.8, recall_count=0,
            raw={"reusable_knowledge": "用户偏好紧凑UI", "description": "用选项卡"},
        )
        assert item.raw["reusable_knowledge"] == "用户偏好紧凑UI"


class TestCosineAndEmbedding:
    def test_cosine_identical(self):
        a = [1.0, 0.0, 0.0]
        assert _cosine(a, a) == pytest.approx(1.0, rel=1e-4)

    def test_cosine_orthogonal(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine(a, b) == pytest.approx(0.0, abs=1e-4)

    def test_cosine_similar(self):
        a = [1.0, 1.0]
        b = [1.1, 0.9]
        sim = _cosine(a, b)
        assert sim > 0.95

    def test_parse_emb_list(self):
        assert _parse_emb([1, 2, 3]) == [1, 2, 3]

    def test_parse_emb_ndarray(self):
        arr = np.array([1.0, 2.0])
        assert _parse_emb(arr) == [1.0, 2.0]

    def test_parse_emb_none(self):
        assert _parse_emb(None) is None

    def test_parse_emb_json_string(self):
        import json
        emb_str = json.dumps([1.0, 2.0, 3.0])
        assert _parse_emb(emb_str) == [1.0, 2.0, 3.0]


class TestMakeSlug:
    def test_basic(self):
        slug = _make_slug("施工规范JGJ130需验证版本号")
        assert len(slug) <= 80
        assert " " not in slug

    def test_english(self):
        slug = _make_slug("Use tabs instead of dropdowns")
        assert "tabs" in slug.lower()


class TestConsolidationResult:
    def test_defaults(self):
        r = ConsolidationResult()
        assert r.skipped is False
        assert r.direct_merged == 0
        assert r.error == ""


class TestConsolidationEngineInit:
    def test_default_thresholds(self):
        engine = ConsolidationEngine()
        assert engine.direct_merge_threshold == 0.92
        assert engine.llm_judge_threshold == 0.75

    def test_custom_thresholds(self):
        engine = ConsolidationEngine(direct_merge_threshold=0.95, llm_judge_threshold=0.80)
        assert engine.direct_merge_threshold == 0.95
        assert engine.llm_judge_threshold == 0.80


class TestCoarseFilter:
    def test_empty(self):
        engine = ConsolidationEngine()
        assert engine._coarse_filter([]) == []

    def test_single_item(self):
        engine = ConsolidationEngine()
        items = [MemoryItem(id="1", bucket="p", content="x", importance=0.5,
                           recall_count=0, embedding=[1.0, 0.0])]
        assert engine._coarse_filter(items) == []

    def test_below_threshold(self):
        engine = ConsolidationEngine(llm_judge_threshold=0.75)
        items = [
            MemoryItem(id="a", bucket="p", content="x", importance=0.5,
                       recall_count=0, embedding=[1.0, 0.0]),
            MemoryItem(id="b", bucket="p", content="y", importance=0.5,
                       recall_count=0, embedding=[0.0, 1.0]),
        ]
        pairs = engine._coarse_filter(items)
        assert pairs == []  # cosine ≈ 0 < 0.75

    def test_above_threshold(self):
        engine = ConsolidationEngine(llm_judge_threshold=0.5)
        items = [
            MemoryItem(id="a", bucket="p", content="x", importance=0.5,
                       recall_count=0, embedding=[1.0, 0.0]),
            MemoryItem(id="b", bucket="p", content="y", importance=0.5,
                       recall_count=0, embedding=[0.9, 0.1]),
        ]
        pairs = engine._coarse_filter(items)
        assert len(pairs) == 1
        assert pairs[0][2] > 0.5

    def test_skips_missing_embedding(self):
        engine = ConsolidationEngine()
        items = [
            MemoryItem(id="a", bucket="p", content="x", importance=0.5,
                       recall_count=0, embedding=[1.0, 0.0]),
            MemoryItem(id="b", bucket="p", content="y", importance=0.5,
                       recall_count=0, embedding=None),
        ]
        pairs = engine._coarse_filter(items)
        assert pairs == []
