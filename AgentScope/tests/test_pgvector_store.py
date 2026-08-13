from __future__ import annotations

import math
import re
from unittest import TestCase

from agentscope.rag import PGVectorStore


class PGVectorStoreValidationTest(TestCase):
    def setUp(self) -> None:
        self.store = PGVectorStore(
            "postgresql://user:password@localhost/projectcopilot",
            min_pool_size=0,
            max_pool_size=1,
        )

    def test_collection_table_name_is_safe_and_deterministic(self) -> None:
        first = self.store._table_name_for_collection("kb_项目一")
        second = self.store._table_name_for_collection("kb_项目一")

        self.assertEqual(first, second)
        self.assertRegex(first, re.compile(r"^kbv_[0-9a-f]{32}$"))

    def test_vector_literal_validates_dimension_and_values(self) -> None:
        self.assertEqual(
            self.store._vector_literal([1.0, -0.5, 0.25], 3),
            "[1,-0.5,0.25]",
        )
        with self.assertRaises(ValueError):
            self.store._vector_literal([1.0], 2)
        with self.assertRaises(ValueError):
            self.store._vector_literal([math.inf], 1)
        with self.assertRaises(ValueError):
            self.store._vector_literal([0.0, 0.0], 2, require_non_zero=True)

    def test_rejects_non_postgresql_url_and_unsafe_schema(self) -> None:
        with self.assertRaises(ValueError):
            PGVectorStore("sqlite:///legacy.db")
        with self.assertRaises(ValueError):
            PGVectorStore(
                "postgresql://user:password@localhost/projectcopilot",
                schema="knowledge;drop schema public",
            )

    def test_distance_strategy_preserves_large_dimensions(self) -> None:
        self.assertEqual(
            self.store._distance_expression(1536),
            "embedding <=> $1::public.vector",
        )
        self.assertIn("halfvec(3072)", self.store._distance_expression(3072))
        self.assertEqual(
            self.store._distance_expression(8192),
            "embedding <=> $1::public.vector",
        )
