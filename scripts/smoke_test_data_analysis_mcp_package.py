"""Exercise platform upload, isolation and a complete baseline workflow."""
from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import os
import sys
import tempfile
import time
import zipfile
from io import StringIO
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENTSCOPE_ROOT = PROJECT_ROOT / "AgentScope"
DEFAULT_ARCHIVE = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "interactive-data-modeling-mcp-windows.zip"
)
EXPECTED_TITLES = {
    "检查数据分析服务",
    "导入数据文件",
    "创建建模会话",
    "分析数据画像",
    "确认目标与特征",
    "生成建模方案",
    "确认方案并开始训练",
    "评估模型",
    "导出模型",
    "回退建模会话",
    "查看建模状态",
    "查看建模会话",
    "查看后台任务进度",
}


def _fixture_csv() -> bytes:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["x1", "x2", "target"])
    for index in range(1, 121):
        writer.writerow([index, index % 7, 1 if index % 3 == 0 else 0])
    return output.getvalue().encode("utf-8-sig")


def _parameters(package_root: Path, state_root: Path) -> StdioServerParameters:
    environment = os.environ.copy()
    environment.update(
        {
            "AGENTSCOPE_USER_ID": "smoke-user",
            "AGENTSCOPE_AGENT_ID": "smoke-agent",
            "AGENTSCOPE_SESSION_ID": state_root.name,
            "AGENTSCOPE_MCP_STATE_DIR": str(state_root),
            "PREDICT_MCP_LOG_LEVEL": "WARNING",
            "MPLBACKEND": "Agg",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        },
    )
    return StdioServerParameters(
        command=str(package_root / "runtime" / "python.exe"),
        args=[str(package_root / "server.py")],
        cwd=str(package_root),
        env=environment,
    )


def _tool_payload(result: Any) -> dict[str, Any]:
    texts = [
        block.text
        for block in result.content
        if getattr(block, "type", None) == "text"
        and isinstance(getattr(block, "text", None), str)
    ]
    raw = "\n".join(texts)
    if result.isError:
        raise RuntimeError(raw or "MCP 工具调用失败")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("MCP 工具没有返回 JSON 对象")
    return payload


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _tool_payload(await session.call_tool(name, arguments or {}))


async def _poll(
    session: ClientSession,
    job_id: str,
    *,
    timeout: float = 180,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await _call(
            session,
            "predict_get_job_status",
            {"job_id": job_id},
        )
        if result["status"] != "running":
            return result
        await asyncio.sleep(0.2)
    raise TimeoutError(f"后台任务超时：{job_id}")


async def _verify_registry_upload(archive: Path, registry_root: Path) -> None:
    sys.path.insert(0, str(AGENTSCOPE_ROOT))
    try:
        from agentscope.app.mcp_registry import MCPRegistryManager
    finally:
        sys.path.remove(str(AGENTSCOPE_ROOT))

    async with MCPRegistryManager(registry_root) as manager:
        with archive.open("rb") as source:
            record = await manager.install_archive(source)
        assert record.manifest.name == "interactive-data-modeling"
        assert record.manifest.version == "2.1.4-platform.1"
        assert len(record.tools) == 13
        assert {tool.display_name for tool in record.tools} == EXPECTED_TITLES


async def _verify_workflow(package_root: Path, temp_root: Path) -> None:
    parameters = _parameters(package_root, temp_root / "state-a")
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert len(listed.tools) == 13
            assert {tool.title for tool in listed.tools} == EXPECTED_TITLES

            health = await _call(session, "predict_check_health")
            assert health["status"] == "ok"
            assert health["data"]["model_availability"]["linear"]["available"] is True

            imported = await _call(
                session,
                "predict_import_data",
                {
                    "file_name": "建模样本.csv",
                    "content_base64": base64.b64encode(_fixture_csv()).decode(),
                    "media_type": "text/csv",
                },
            )
            assert imported["status"] == "ok"
            data_ref = imported["data"]["data_ref"]
            assert data_ref.startswith("predict-data://")
            assert "path" not in json.dumps(imported, ensure_ascii=False).lower()

            created = await _call(
                session,
                "predict_create_session",
                {"data_ref": data_ref},
            )
            session_id = created["session_id"]
            assert created["state"] == "CREATED"

            profiled = await _call(
                session,
                "predict_profile_data",
                {"session_id": session_id},
            )
            assert profiled["status"] == "needs_input"
            assert profiled["data"]["profile"]["shape"] == {
                "rows": 120,
                "columns": 3,
            }

            variables = await _call(
                session,
                "predict_confirm_variables",
                {
                    "session_id": session_id,
                    "target": "target",
                    "features": ["x1", "x2"],
                    "task_type": "classification",
                },
            )
            assert variables["status"] == "ok"

            proposal = await _call(
                session,
                "predict_propose_pipeline_plan",
                {
                    "session_id": session_id,
                    "objective": "speed",
                    "search_intensity": "fast",
                    "max_models": 1,
                },
            )
            assert proposal["status"] == "needs_input"

            training = await _call(
                session,
                "predict_confirm_pipeline_plan",
                {
                    "session_id": session_id,
                    "proposal_id": proposal["data"]["proposal_id"],
                    "models": ["linear"],
                    "confirm": True,
                },
            )
            assert training["status"] == "running"
            trained = await _poll(session, training["data"]["job_id"])
            assert trained["status"] == "ok", trained
            assert trained["state"] == "TRAINED"

            evaluation = await _call(
                session,
                "predict_evaluate_models",
                {"session_id": session_id, "confirm": True},
            )
            assert evaluation["status"] == "running"
            evaluated = await _poll(session, evaluation["data"]["job_id"])
            assert evaluated["status"] == "ok", evaluated
            assert evaluated["state"] == "EVALUATED"

            export = await _call(
                session,
                "predict_export_model",
                {
                    "session_id": session_id,
                    "model_type": "linear",
                    "confirm": True,
                },
            )
            assert export["status"] == "running"
            exported = await _poll(session, export["data"]["job_id"])
            assert exported["status"] == "ok", exported
            assert exported["state"] == "EXPORTED"

    isolated_parameters = _parameters(package_root, temp_root / "state-b")
    async with stdio_client(isolated_parameters) as (read, write):
        async with ClientSession(read, write) as isolated:
            await isolated.initialize()
            sessions = await _call(isolated, "predict_list_sessions")
            assert sessions["data"]["sessions"] == []


async def _run(archive: Path) -> None:
    archive = archive.resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"MCP ZIP 不存在：{archive}")
    with tempfile.TemporaryDirectory(prefix="data-analysis-mcp-smoke-") as raw:
        temp_root = Path(raw)
        await _verify_registry_upload(archive, temp_root / "registry")
        with zipfile.ZipFile(archive) as package:
            package.extractall(temp_root / "package")
        manifests = list((temp_root / "package").rglob("mcp.json"))
        if len(manifests) != 1:
            raise RuntimeError("上传包内必须且只能包含一个 mcp.json")
        await _verify_workflow(manifests[0].parent, temp_root)
    print("MCP 平台上传探测：通过")
    print("附件 data_ref 与会话隔离：通过")
    print("画像、训练、评估和导出闭环：通过")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    asyncio.run(_run(args.archive))


if __name__ == "__main__":
    main()
