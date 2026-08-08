from __future__ import annotations

import pandas as pd

from shield_prediction_mcp.data import load_data
from shield_prediction_mcp.service import InteractiveDataModelingService, ShieldPredictionService


def _customer_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer_age": [22, 35, 47, 29, 61, 42],
            "monthly_spend": [120.0, 340.0, 560.0, 210.0, 720.0, 450.0],
            "customer_segment": ["new", "loyal", "loyal", "new", "premium", "premium"],
            "churned": ["yes", "no", "no", "yes", "no", "no"],
        }
    )


def test_json_and_parquet_are_supported(tmp_path) -> None:
    frame = _customer_frame()
    json_path = tmp_path / "customers.json"
    parquet_path = tmp_path / "customers.parquet"
    frame.to_json(json_path, orient="records", force_ascii=False)
    frame.to_parquet(parquet_path, index=False)

    pd.testing.assert_frame_equal(load_data(json_path), frame, check_dtype=False)
    pd.testing.assert_frame_equal(load_data(parquet_path), frame, check_dtype=False)


def test_generic_service_keeps_legacy_class_alias(tmp_path) -> None:
    assert ShieldPredictionService is InteractiveDataModelingService
    frame = _customer_frame()
    path = tmp_path / "customers.csv"
    frame.to_csv(path, index=False, encoding="utf-8-sig")

    service = InteractiveDataModelingService(tmp_path / "runtime")
    session_id = service.create_session(str(path))["session_id"]
    profile = service.profile_data(session_id)
    assert profile["profile"]["shape"] == {"rows": 6, "columns": 4}
    variables = service.confirm_variables(
        session_id,
        target="churned",
        features=["customer_age", "monthly_spend", "customer_segment"],
        task_type="auto",
    )
    assert variables["confirmed"]["task_type"] == "classification"
