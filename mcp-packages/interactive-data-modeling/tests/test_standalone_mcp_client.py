from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


def test_standalone_cli_health_check_uses_mcp(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["DATA_MODELING_MCP_WORKDIR"] = str(tmp_path / "runtime")
    completed = subprocess.run(
        [sys.executable, str(project_root / "standalone_cli.py"), "--health-check"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "ok"
    assert result["server"] == "interactive-data-modeling"
    assert result["version"] == "2.1.4"
    assert result["workflow_version"] == 6
    assert result["contract_version"] == 2


def test_standalone_cli_creates_profiled_persistent_session_through_mcp(tmp_path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    data_path = tmp_path / "customers.csv"
    output_dir = tmp_path / "outputs"
    runtime_dir = tmp_path / "runtime"
    pd.DataFrame(
        {
            "age": [22, 35, 47, 29, 61, 42, 33, 55],
            "spend": [120, 340, 560, 210, 720, 450, 280, 630],
            "segment": ["new", "loyal", "loyal", "new", "premium", "premium", "new", "loyal"],
            "churned": ["yes", "no", "no", "yes", "no", "no", "yes", "no"],
        }
    ).to_csv(data_path, index=False, encoding="utf-8-sig")
    answers = "churned\nage,spend,segment\nauto\n\nn\nn\n"
    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "standalone_cli.py"),
            "--data",
            str(data_path),
            "--output-dir",
            str(output_dir),
            "--workdir",
            str(runtime_dir),
        ],
        cwd=project_root,
        env=os.environ.copy(),
        input=answers,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 1
    assert "已通过 MCP 协议连接" in completed.stdout
    assert "数据规模：8 行 × 4 列" in completed.stdout
    assert "用户暂不训练" in completed.stderr
    state_files = list(runtime_dir.glob("*/session.json"))
    assert len(state_files) == 1
    state = json.loads(state_files[0].read_text(encoding="utf-8"))
    assert state["stage"] == "pipeline_proposed"
    assert state["variables"]["target"] == "churned"
