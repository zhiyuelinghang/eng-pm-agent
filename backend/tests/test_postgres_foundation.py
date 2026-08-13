from unittest.mock import MagicMock

import pytest

from backend.app.postgres_foundation import (
    bootstrap_postgres_foundation,
    validate_identifier,
)


@pytest.mark.parametrize(
    "value",
    ["platform", "agentscope", "memory_2", "knowledge"],
)
def test_postgres_identifier_accepts_safe_names(value: str) -> None:
    assert validate_identifier(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "Platform", "memory-tools", "public; DROP SCHEMA public", "a" * 64],
)
def test_postgres_identifier_rejects_unsafe_names(value: str) -> None:
    with pytest.raises(ValueError):
        validate_identifier(value)


def test_postgres_foundation_rejects_non_postgres_engine() -> None:
    engine = MagicMock()
    engine.dialect.name = "sqlite"

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        bootstrap_postgres_foundation(engine)
