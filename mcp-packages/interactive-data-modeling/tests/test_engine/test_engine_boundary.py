from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd

from shield_prediction_mcp.engine.data import load_data, preprocess_dataframe, profile_dataframe
from shield_prediction_mcp.engine.errors import DomainError
from shield_prediction_mcp.engine.evaluation import evaluate_training_results
from shield_prediction_mcp.engine.exporting import export_bundle
from shield_prediction_mcp.engine.modeling import train_selected_models
from shield_prediction_mcp.engine.utils import safe_name


ROOT = Path(__file__).resolve().parents[2]


def test_engine_has_no_dependency_on_upper_layers() -> None:
    forbidden = {"tools", "session", "validation", "schemas", "runtime", "server"}
    engine_root = ROOT / "src" / "shield_prediction_mcp" / "engine"
    for path in engine_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level < 2:
                continue
            first = (node.module or "").split(".", 1)[0]
            assert first not in forbidden, f"{path.name} imports upper layer {first}"


def test_engine_load_preprocess_train_evaluate_and_export(tmp_path: Path) -> None:
    rng = np.random.default_rng(17)
    x = rng.normal(size=100)
    frame = pd.DataFrame({"x": x, "target": (x > 0).astype(int)})
    source = tmp_path / "engine.csv"
    frame.to_csv(source, index=False)

    loaded = load_data(source)
    assert profile_dataframe(loaded)["shape"] == {"rows": 100, "columns": 2}
    preprocessing = {
        "missing_default": "median",
        "missing_per_column": {},
        "encoding": {},
        "denoise": None,
        "causal": False,
    }
    preview, artifact = preprocess_dataframe(
        loaded,
        ["x"],
        "target",
        "median",
        {},
        {},
        None,
        tmp_path / "preview",
    )
    assert list(preview.columns) == ["x", "target"]
    assert Path(artifact["artifact_path"]).is_file()

    trained = train_selected_models(
        loaded,
        ["x"],
        "target",
        "classification",
        ["linear"],
        {
            "split_method": "random",
            "tuning": "default",
            "train_ratio": 0.7,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
            "n_trials": 1,
            "model_params": {},
        },
        tmp_path / "training",
        preprocessing_config=preprocessing,
    )
    assert trained["preprocessor_fit_scope"] == "training_partition_only"
    evaluated = evaluate_training_results(trained, tmp_path / "evaluation")
    assert evaluated["models"][0]["metrics"]["Accuracy"] >= 0.8
    exported = export_bundle(
        trained,
        evaluated,
        "linear",
        trained["preprocessor_path"],
        tmp_path / "exports",
        version=1,
    )
    assert Path(exported["archive_path"]).is_file()
    assert Path(exported["export_dir"]).name == "v1"


def test_engine_utilities_are_session_independent() -> None:
    assert safe_name("a/b") == "a_b"
    error = DomainError("invalid", code="INVALID_INPUT")
    assert error.code == "INVALID_INPUT"
