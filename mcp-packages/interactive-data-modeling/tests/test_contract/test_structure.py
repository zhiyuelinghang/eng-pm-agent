from __future__ import annotations

import ast
import json
from pathlib import Path

from shield_prediction_mcp.session.state_machine import ALLOWED_TRANSITIONS, WorkflowState
from shield_prediction_mcp.tools import PUBLIC_TOOLS


ROOT = Path(__file__).resolve().parents[2]


def test_manifest_and_standard_directories_exist() -> None:
    manifest = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "interactive-data-modeling"
    assert manifest["display_name"] == "数据分析与预测建模"
    assert manifest["version"] == "2.1.4-platform.1"
    assert manifest["transport"] == "stdio"
    assert manifest["command"] == "runtime/python.exe"
    for relative in (
        "src/shield_prediction_mcp/tools",
        "src/shield_prediction_mcp/session",
        "src/shield_prediction_mcp/validation",
        "src/shield_prediction_mcp/engine",
        "src/shield_prediction_mcp/schemas",
        "prompts",
        "tests/test_engine",
        "tests/test_contract",
    ):
        assert (ROOT / relative).is_dir(), relative


def test_public_tool_names_and_descriptions_follow_contract() -> None:
    decision_tools = {
        "predict_create_session",
        "predict_profile_data",
        "predict_confirm_variables",
        "predict_propose_pipeline_plan",
        "predict_confirm_pipeline_plan",
        "predict_evaluate_models",
        "predict_export_model",
        "predict_rewind_session",
        "predict_get_status",
        "predict_get_job_status",
    }
    for tool in PUBLIC_TOOLS:
        assert tool.__name__.startswith("predict_")
        assert tool.__doc__
        first = tool.__doc__.split("：", 1)[0]
        assert first in {"阶段工具", "只读探查工具"}
        if tool.__name__ in decision_tools:
            assert "needs_user_decision" in tool.__doc__
            assert "不得替用户决定、不得跳过" in tool.__doc__


def test_state_machine_has_explicit_transition_table() -> None:
    assert ALLOWED_TRANSITIONS
    assert all(isinstance(state, WorkflowState) for state in ALLOWED_TRANSITIONS)
    assert WorkflowState.PROFILED in ALLOWED_TRANSITIONS[WorkflowState.CREATED]
    assert WorkflowState.TRAINED in ALLOWED_TRANSITIONS[WorkflowState.PIPELINE_PROPOSED]
    assert WorkflowState.PIPELINE_PROPOSED in ALLOWED_TRANSITIONS[WorkflowState.EXPORTED]


def test_real_implementations_live_in_standard_layers() -> None:
    package = ROOT / "src" / "shield_prediction_mcp"
    forbidden_engine_dependencies = {"tools", "session", "validation", "schemas", "runtime", "server"}
    for name in ("data.py", "modeling.py", "planning.py", "evaluation.py", "exporting.py"):
        path = package / "engine" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level >= 2:
                first = (node.module or "").split(".", 1)[0]
                assert first not in forbidden_engine_dependencies, (name, first)
        compatibility = (package / name).read_text(encoding="utf-8")
        assert f"from .engine.{path.stem} import" in compatibility
    assert (package / "tools" / "orchestrator.py").stat().st_size > 10_000
    assert (package / "session" / "store.py").stat().st_size > 10_000
    assert "from .tools.orchestrator import" in (package / "service.py").read_text(encoding="utf-8")
    assert "from .session.store import" in (package / "storage.py").read_text(encoding="utf-8")
