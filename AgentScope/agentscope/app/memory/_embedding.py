# -*- coding: utf-8 -*-
"""Dependency-free local embedding fallback for context-control memory."""

from __future__ import annotations

from collections import Counter
import hashlib
import math
import os
from pathlib import Path
import re
from typing import Literal


os.environ.setdefault(
    "MEM0_DIR",
    str(Path(os.getenv("AGENTSCOPE_RUNTIME_HOME", "data/agentscope")) / "mem0"),
)
os.environ.setdefault("MEM0_TELEMETRY", "false")

from mem0.configs.embeddings.base import BaseEmbedderConfig  # noqa: E402
from mem0.embeddings.base import EmbeddingBase  # noqa: E402


_ASCII_WORD = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")


class HashEmbedding(EmbeddingBase):
    """Stable lexical hashing embedding used when no API model is configured.

    It keeps the runtime lightweight and deterministic.  Production can switch
    to an OpenAI-compatible embedding endpoint through environment variables
    without changing stored-table or middleware code.
    """

    def __init__(self, config: BaseEmbedderConfig | None = None) -> None:
        super().__init__(config)
        self._dimensions = int(self.config.embedding_dims or 1024)

    @staticmethod
    def _tokens(text: str) -> list[str]:
        normalized = text.lower()
        tokens = _ASCII_WORD.findall(normalized)
        for run in _CJK_RUN.findall(normalized):
            tokens.extend(run)
            tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
        return tokens

    def embed(
        self,
        text: str,
        memory_action: Literal["add", "search", "update"] | None = None,
    ) -> list[float]:
        del memory_action
        vector = [0.0] * self._dimensions
        for token, count in Counter(self._tokens(text)).items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "big")
            index = raw % self._dimensions
            sign = 1.0 if raw & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]
