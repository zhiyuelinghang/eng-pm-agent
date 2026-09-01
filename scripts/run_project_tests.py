"""Run the repository's canonical frontend, Python and MCP verification.

Use the project embedded Python through ``test-all.bat``.  Individual suites
can be selected with ``--suite``; without selectors every suite is run.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT_ROOT / "python-3.13.14" / "python.exe"
PYTEST_ENTRY = PROJECT_ROOT / "scripts" / "pytest_entry.py"
DATA_MODELING_ROOT = (
    PROJECT_ROOT / "mcp-packages" / "interactive-data-modeling"
)
DATA_MODELING_DEPENDENCIES = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "build-cache"
    / "interactive-data-modeling-py313"
)


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    command: tuple[str, ...]
    cwd: Path


def _pytest_check(
    name: str,
    description: str,
    cwd: Path,
    test_path: str,
    *source_roots: Path,
) -> Check:
    command = [str(PYTHON), str(PYTEST_ENTRY)]
    for source_root in source_roots:
        command.extend(("--prepend", str(source_root)))
    command.extend(("--", test_path, "-q"))
    return Check(name, description, tuple(command), cwd)


def _checks() -> list[Check]:
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    task_engine_root = PROJECT_ROOT / "mcp-packages" / "task-engine"
    wecom_root = PROJECT_ROOT / "mcp-packages" / "wecom-notify"
    smoke_scripts = (
        (
            "data-modeling-smoke",
            "数据建模发布包完整闭环",
            "smoke_test_data_analysis_mcp_package.py",
        ),
        (
            "attachment-parser-smoke",
            "附件解析发布包主路径与降级路径",
            "smoke_test_attachment_parser_mcp_package.py",
        ),
        (
            "initialization-validator-smoke",
            "项目初始化核验发布包",
            "smoke_test_project_initialization_validator_mcp_package.py",
        ),
        (
            "task-engine-smoke",
            "任务引擎发布包与 PostgreSQL 模式",
            "smoke_test_task_engine_mcp_package.py",
        ),
        (
            "wecom-notify-smoke",
            "企业微信发布包与无外发探测",
            "smoke_test_wecom_notify_mcp_package.py",
        ),
    )
    checks = [
        Check(
            "structure",
            "源码规模与已拆分模块边界",
            (
                str(PYTHON),
                str(PROJECT_ROOT / "scripts" / "check_code_structure.py"),
            ),
            PROJECT_ROOT,
        ),
        _pytest_check(
            "backend",
            "平台后端测试",
            PROJECT_ROOT,
            "backend/tests",
            PROJECT_ROOT,
        ),
        _pytest_check(
            "agentscope",
            "AgentScope 集成测试",
            PROJECT_ROOT,
            "AgentScope/tests",
            PROJECT_ROOT,
            PROJECT_ROOT / "AgentScope",
        ),
        _pytest_check(
            "task-engine",
            "任务引擎源码测试",
            task_engine_root,
            "tests",
            task_engine_root / "src",
        ),
        _pytest_check(
            "wecom-notify",
            "企业微信 MCP 源码测试",
            wecom_root,
            "tests",
            wecom_root / "src",
        ),
        _pytest_check(
            "interactive-data-modeling",
            "交互式数据建模 MCP 源码测试",
            DATA_MODELING_ROOT,
            "tests",
            DATA_MODELING_ROOT / "src",
            DATA_MODELING_DEPENDENCIES,
        ),
        Check(
            "frontend",
            "Vue/TypeScript 生产构建",
            (npm, "run", "check"),
            PROJECT_ROOT / "frontend",
        ),
    ]
    checks.extend(
        Check(
            name,
            description,
            (str(PYTHON), str(PROJECT_ROOT / "scripts" / script_name)),
            PROJECT_ROOT,
        )
        for name, description, script_name in smoke_scripts
    )
    return checks


def _validate_runtime(selected: list[Check]) -> None:
    if not PYTHON.is_file():
        raise SystemExit(f"缺少项目便携 Python：{PYTHON}")
    if any(check.name == "interactive-data-modeling" for check in selected):
        if not DATA_MODELING_DEPENDENCIES.is_dir():
            raise SystemExit(
                "缺少数据建模测试依赖缓存。请先执行：\n"
                "  .\\python-3.13.14\\python.exe "
                ".\\scripts\\build_data_analysis_mcp_package.py "
                "--refresh-dependencies",
            )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")

    available = _checks()
    by_name = {check.name: check for check in available}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        action="append",
        choices=tuple(by_name),
        help="Only run this suite; repeatable.",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue after a failed suite and report every failure.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List canonical suite names and exit.",
    )
    arguments = parser.parse_args()

    if arguments.list:
        for check in available:
            print(f"{check.name:32} {check.description}")
        return 0

    selected_names = set(arguments.suite or ())
    selected = [
        check for check in available
        if not selected_names or check.name in selected_names
    ]
    _validate_runtime(selected)

    failures: list[str] = []
    started = time.monotonic()
    for index, check in enumerate(selected, start=1):
        print("\n" + "=" * 72, flush=True)
        print(
            f"[{index}/{len(selected)}] {check.name}：{check.description}",
            flush=True,
        )
        child_environment = os.environ.copy()
        child_environment["PYTHONUTF8"] = "1"
        child_environment["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            check.command,
            cwd=check.cwd,
            check=False,
            env=child_environment,
        )
        if completed.returncode == 0:
            print(f"[通过] {check.name}", flush=True)
            continue
        failures.append(check.name)
        print(
            f"[失败] {check.name}（退出码 {completed.returncode}）",
            flush=True,
        )
        if not arguments.keep_going:
            break

    duration = time.monotonic() - started
    print("\n" + "=" * 72, flush=True)
    if failures:
        print(
            f"项目验证失败：{', '.join(failures)}；耗时 {duration:.1f} 秒",
            flush=True,
        )
        return 1
    print(
        f"项目验证全部通过：{len(selected)} 个检查；耗时 {duration:.1f} 秒",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
