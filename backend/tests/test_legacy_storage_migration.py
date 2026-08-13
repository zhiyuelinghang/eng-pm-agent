from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import Boolean, DateTime, JSON
from scripts import migrate_legacy_storage

from scripts.migrate_legacy_storage import (
    _convert_value,
    _qdrant_vector,
    _validate_database,
)


def test_legacy_value_conversion_preserves_json_boolean_and_datetime() -> None:
    assert _convert_value('{"project_id": 7}', JSON()) == {"project_id": 7}
    assert _convert_value("true", Boolean()) is True
    assert _convert_value(0, Boolean()) is False
    assert _convert_value(
        "2026-08-13T12:30:00+08:00",
        DateTime(timezone=True),
    ) == datetime.fromisoformat("2026-08-13T12:30:00+08:00")


def test_qdrant_vector_validation_accepts_single_named_vector() -> None:
    assert _qdrant_vector([1, 0.5]) == [1.0, 0.5]
    assert _qdrant_vector({"dense": [1, 0.5]}) == [1.0, 0.5]
    with pytest.raises(RuntimeError):
        _qdrant_vector({"first": [1.0], "second": [2.0]})


def test_migration_database_guard_rejects_wrong_database() -> None:
    _validate_database(
        "postgresql://user:password@localhost/projectcopilot",
        "projectcopilot",
    )
    with pytest.raises(RuntimeError):
        _validate_database(
            "postgresql://user:password@localhost/production",
            "projectcopilot",
        )
    with pytest.raises(RuntimeError):
        _validate_database("sqlite:///legacy.db", "projectcopilot")


def test_project_env_loader_preserves_explicit_environment(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(migrate_legacy_storage, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        'MIGRATION_TEST_VALUE="from-file"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("MIGRATION_TEST_VALUE", raising=False)
    migrate_legacy_storage._load_project_env()
    assert migrate_legacy_storage.os.environ["MIGRATION_TEST_VALUE"] == "from-file"

    monkeypatch.setenv("MIGRATION_TEST_VALUE", "explicit")
    migrate_legacy_storage._load_project_env()
    assert migrate_legacy_storage.os.environ["MIGRATION_TEST_VALUE"] == "explicit"
