#!/usr/bin/env python3
"""Interactive MCP client for domain-independent data analysis and modeling."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


if sys.platform == "win32":
    # MCP deployment paths and prompts contain Chinese text. Force UTF-8 so
    # modern Windows terminals and redirected output do not produce mojibake.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


PROJECT_ROOT = Path(__file__).resolve().parent


class MCPClientError(RuntimeError):
    """Raised when the MCP server rejects a tool call or returns invalid data."""


def error_text(exc: BaseException) -> str:
    nested = getattr(exc, "exceptions", None)
    if nested and exc.__class__.__name__.endswith("ExceptionGroup"):
        messages = [error_text(item) for item in nested]
        return "; ".join(message for message in messages if message)
    return str(exc)


class MCPServiceProxy:
    """Small typed facade over the server's MCP tools."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session

    @staticmethod
    def _unwrap(value: Any) -> Any:
        while isinstance(value, dict) and set(value) == {"result"}:
            value = value["result"]
        return value

    async def call(self, tool: str, **arguments: Any) -> Any:
        result = await self.session.call_tool(tool, arguments)
        text_parts = [item.text for item in result.content if hasattr(item, "text")]
        if result.isError:
            raise MCPClientError("\n".join(text_parts) or f"MCP 工具调用失败: {tool}")
        if text_parts:
            try:
                value = json.loads(text_parts[0])
                value = self._unwrap(value)
                if isinstance(value, dict) and value.get("status") == "error":
                    details = value.get("error") or {}
                    raise MCPClientError(details.get("message") or value.get("message") or tool)
                return value
            except json.JSONDecodeError as exc:
                raise MCPClientError(f"MCP 工具 {tool} 返回了无效 JSON: {exc}") from exc
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return self._unwrap(structured)
        raise MCPClientError(f"MCP 工具 {tool} 没有返回结果")

    async def health_check(self) -> dict[str, Any]:
        envelope = await self.call("predict_check_health")
        return {"status": envelope["status"], **envelope["data"]}

    async def create_session(self, data_path: str, output_dir: str | None = None) -> dict[str, Any]:
        envelope = await self.call("predict_create_session", data_path=data_path, output_dir=output_dir)
        return {"session_id": envelope["session_id"], "stage": envelope["state"].lower(), **envelope["data"]}

    async def profile_data(self, session_id: str) -> dict[str, Any]:
        envelope = await self.call("predict_profile_data", session_id=session_id)
        return {"session_id": session_id, "stage": envelope["state"].lower(), **envelope["data"]}

    async def get_session_state(self, session_id: str) -> dict[str, Any]:
        envelope = await self.call("predict_get_status", session_id=session_id)
        state = dict(envelope["data"].get("session", {}))
        state["stage"] = envelope["state"].lower()
        return state

    async def confirm_variables(self, session_id: str, **arguments: Any) -> dict[str, Any]:
        envelope = await self.call("predict_confirm_variables", session_id=session_id, **arguments)
        return {"session_id": session_id, "stage": envelope["state"].lower(), **envelope["data"]}

    async def propose_pipeline_plan(self, session_id: str, **arguments: Any) -> dict[str, Any]:
        envelope = await self.call("predict_propose_pipeline_plan", session_id=session_id, **arguments)
        return {
            "session_id": session_id,
            "stage": envelope["state"].lower(),
            **envelope["data"],
            "options": envelope["options"],
        }

    async def confirm_pipeline_plan(self, session_id: str, **arguments: Any) -> dict[str, Any]:
        envelope = await self.call("predict_confirm_pipeline_plan", session_id=session_id, **arguments)
        return await self._wait_job(session_id, envelope)

    async def evaluate_models(self, session_id: str, confirm: bool) -> dict[str, Any]:
        envelope = await self.call("predict_evaluate_models", session_id=session_id, confirm=confirm)
        return await self._wait_job(session_id, envelope)

    async def export_model(self, session_id: str, model_type: str, confirm: bool) -> dict[str, Any]:
        return await self.call(
            "predict_export_model",
            session_id=session_id,
            model_type=model_type,
            confirm=confirm,
        ) if not confirm else await self._wait_job(
            session_id,
            await self.call(
                "predict_export_model",
                session_id=session_id,
                model_type=model_type,
                confirm=confirm,
            ),
        )

    async def rewind_session(self, session_id: str, target_stage: str, reason: str) -> dict[str, Any]:
        envelope = await self.call(
            "predict_rewind_session",
            session_id=session_id,
            target_state=target_stage,
            reason=reason,
        )
        return {"session_id": session_id, "stage": envelope["state"].lower(), **envelope["data"]}

    async def list_sessions(self) -> list[dict[str, Any]]:
        envelope = await self.call("predict_list_sessions")
        return envelope["data"]["sessions"]

    async def _wait_job(self, session_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
        if envelope["status"] != "running":
            return envelope.get("data", {})
        job_id = envelope["data"]["job_id"]
        while True:
            await asyncio.sleep(0.2)
            status = await self.call(
                "predict_get_job_status",
                job_id=job_id,
            )
            if status["status"] == "running":
                continue
            if status["status"] == "needs_input":
                details = status.get("error") or {}
                raise MCPClientError(details.get("message") or status.get("message") or "任务需要修正")
            if status["status"] == "error":
                details = status.get("error") or {}
                raise MCPClientError(details.get("message") or status.get("message") or "异步任务失败")
            return status["data"]["result"]


def show(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else (default or "")


def confirm(prompt: str) -> bool:
    return ask(f"{prompt} (y/n)", "n").lower() in {"y", "yes", "是", "确认"}


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


def parse_json(value: str, fallback: Any) -> Any:
    if not value.strip():
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise MCPClientError(f"JSON 输入无效: {exc}") from exc


def print_profile(result: dict[str, Any]) -> None:
    profile = result["profile"]
    print(f"\n数据规模：{profile['shape']['rows']} 行 × {profile['shape']['columns']} 列")
    print("\n字段：")
    for column in profile["columns"]:
        print(
            f"- {column['name']} | {column['dtype']} | "
            f"缺失 {column['null_count']} | 唯一值 {column['unique_count']}"
        )
    if profile["time_columns"]:
        print(f"\n时间字段候选：{', '.join(profile['time_columns'])}")
    if profile.get("missing_plot"):
        print(f"缺失值图：{profile['missing_plot']}")


async def configure_variables(service: MCPServiceProxy, session_id: str) -> None:
    state = await service.get_session_state(session_id)
    columns = [column["name"] for column in state["profile"]["columns"]]
    print(f"\n可用字段：{', '.join(columns)}")
    target = ask("输出变量 Y")
    feature_text = ask("输入变量 X（逗号分隔；输入 * 使用除目标外所有数值字段）")
    task_type = ask("任务类型 auto/regression/classification/timeseries", "auto")
    time_column = ask("时间或顺序字段（没有则留空）", "") or None
    if feature_text == "*":
        result = await service.confirm_variables(
            session_id,
            target=target,
            feature_mode="all_numeric",
            task_type=task_type,
            time_column=time_column,
        )
    else:
        result = await service.confirm_variables(
            session_id,
            target=target,
            features=parse_list(feature_text),
            feature_mode="manual",
            task_type=task_type,
            time_column=time_column,
        )
    show(result["confirmed"])


def print_pipeline_plan(proposal: dict[str, Any]) -> None:
    print("\n推荐的完整流水线：")
    show(proposal["recommended_plan"])
    print("\n全部可选项：")
    show(proposal["available_options"])


async def confirm_pipeline_plan(service: MCPServiceProxy, session_id: str) -> None:
    state = await service.get_session_state(session_id)
    if not state.get("pipeline_plan_proposal"):
        await service.propose_pipeline_plan(session_id)
        state = await service.get_session_state(session_id)
    proposal = state["pipeline_plan_proposal"]
    print_pipeline_plan(proposal)
    arguments: dict[str, Any] = {
        "proposal_id": proposal["proposal_id"],
        "confirm": True,
    }
    if confirm("接受完整推荐方案并立即开始训练"):
        arguments["user_adjustment_note"] = "独立客户端：接受完整推荐方案并开始训练"
    else:
        recommended = proposal["recommended_plan"]
        if not confirm("修改完整方案后开始训练"):
            raise MCPClientError("用户暂不训练")
        preprocessing = recommended["preprocessing"]
        arguments["missing_default"] = ask(
            "默认缺失值策略 mean/median/interpolate/drop/knn/ffill/mode",
            preprocessing["missing_default"],
        )
        print("逐字段缺失策略输入 JSON；只需填写要修改的字段。")
        arguments["missing_per_column"] = parse_json(ask("逐字段缺失策略", ""), {})
        print("编码策略输入 JSON；只需填写要修改的字段。")
        arguments["encoding"] = parse_json(ask("编码策略", ""), {})
        print('降噪配置输入 JSON，例如 {"method":"moving_average","columns":["signal"],"window":5}。')
        arguments["denoise"] = parse_json(
            ask("降噪配置", json.dumps(preprocessing["denoise"], ensure_ascii=False)),
            preprocessing["denoise"],
        )
        models = parse_list(
            ask("模型（逗号分隔）", ",".join(recommended["models"]))
        )
        training = recommended["training"]
        split_method = ask(
            "划分方式 random/sequential/kfold",
            training["split_method"],
        )
        tuning = ask(
            "调参方式 default/grid/random/bayesian",
            training["tuning"],
        )
        train_ratio = float(ask("训练集比例", str(training["train_ratio"])))
        val_ratio = float(ask("验证集比例", str(training["val_ratio"])))
        test_ratio = float(ask("测试集比例", str(training["test_ratio"])))
        n_trials = int(ask("搜索轮数", str(training["n_trials"])))
        print('可选手动参数 JSON，例如 {"random_forest":{"n_estimators":200}}；不需要则回车。')
        model_params = parse_json(ask("模型参数", ""), {})
        arguments.update(
            {
                "models": models,
                "split_method": split_method,
                "tuning": tuning,
                "train_ratio": train_ratio,
                "val_ratio": val_ratio,
                "test_ratio": test_ratio,
                "n_trials": n_trials,
                "model_params": model_params,
                "user_adjustment_note": "独立客户端：用户修改推荐方案",
            }
        )
    result = await service.confirm_pipeline_plan(session_id, **arguments)
    print("\n已执行的最终完整方案：")
    show(result["final_plan"])
    print("\n训练结果：")
    show({"models": result["models"], "split_info": result["split_info"]})


def print_evaluation(result: dict[str, Any]) -> None:
    print("\n测试集评估：")
    for item in result["evaluation"]["models"]:
        print(f"\n{item['model_name']}")
        show(item["metrics"])
        print("图表：")
        for plot in item["plots"]:
            print(f"- {plot}")


async def run_workflow(service: MCPServiceProxy, session_id: str) -> None:
    while True:
        state = await service.get_session_state(session_id)
        stage = state["stage"]
        print(f"\n=== 会话 {session_id} | 当前阶段：{stage} ===")

        if stage == "created":
            print_profile(await service.profile_data(session_id))
        elif stage == "profiled":
            await configure_variables(service, session_id)
        elif stage == "variables_confirmed":
            await service.propose_pipeline_plan(session_id)
        elif stage == "pipeline_proposed":
            await confirm_pipeline_plan(service, session_id)
        elif stage in {
            "preprocessing_reviewed",
            "preprocessed",
            "models_recommended",
            "models_selected",
            "training_configured",
        }:
            print(f"检测到旧版 {stage} 会话，自动回退并迁移到一体化方案流程。")
            await service.rewind_session(session_id, "variables_confirmed", "migrate_unified_pipeline")
            await service.propose_pipeline_plan(session_id)
        elif stage == "trained":
            if not confirm("训练完成，进入测试集评估"):
                target = ask("回退到 variables_confirmed/pipeline_proposed", "pipeline_proposed")
                await service.rewind_session(session_id, target, "standalone_cli_revision")
            else:
                print_evaluation(await service.evaluate_models(session_id, confirm=True))
        elif stage == "evaluated":
            if not confirm("对模型效果满意并导出"):
                target = ask(
                    "回退到 variables_confirmed/pipeline_proposed/trained",
                    "pipeline_proposed",
                )
                await service.rewind_session(session_id, target, "standalone_cli_revision")
                continue
            available = list(state.get("selected_models", []))
            model_type = ask(f"导出哪个模型 {available}", available[0])
            show(await service.export_model(session_id, model_type, confirm=True))
        elif stage == "exported":
            print("\n模型已导出：")
            show(state.get("artifacts", {}))
            if confirm("继续导出另一个已评估模型"):
                available = list(state.get("selected_models", []))
                model_type = ask(f"选择模型 {available}", available[0])
                show(await service.export_model(session_id, model_type, confirm=True))
            return
        else:
            raise MCPClientError(f"未知阶段: {stage}")


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="通用数据分析与预测模型独立 MCP 客户端（不需要 Agent）")
    parser.add_argument("--data", help="新建会话使用的 CSV/TSV/Excel/JSON/Parquet 绝对路径")
    parser.add_argument("--output-dir", help="模型和图表输出目录")
    parser.add_argument("--session-id", help="恢复已有会话")
    parser.add_argument("--workdir", help="会话持久化目录，默认使用项目 runtime")
    parser.add_argument("--list-sessions", action="store_true", help="列出已有会话后退出")
    parser.add_argument("--health-check", action="store_true", help="通过 MCP 协议检查服务器后退出")
    arguments = parser.parse_args()
    if not any((arguments.health_check, arguments.list_sessions, arguments.session_id, arguments.data)):
        parser.error("请提供 --data 新建会话，或提供 --session-id 恢复会话")
        return 2

    workdir = Path(arguments.workdir).expanduser().resolve() if arguments.workdir else PROJECT_ROOT / "runtime"
    server_environment = os.environ.copy()
    server_environment.update(
        {
            "DATA_MODELING_MCP_WORKDIR": str(workdir),
            "DATA_MODELING_MCP_LOG_LEVEL": os.environ.get("DATA_MODELING_MCP_LOG_LEVEL", "WARNING"),
            "PYTHONUTF8": "1",
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "shield_prediction_mcp.server"],
        env=server_environment,
        cwd=str(PROJECT_ROOT),
        encoding="utf-8",
        encoding_error_handler="replace",
    )
    session_id: str | None = arguments.session_id
    try:
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()
                service = MCPServiceProxy(mcp_session)
                health = await service.health_check()
                if arguments.health_check:
                    show(health)
                    return 0
                if arguments.list_sessions:
                    show(await service.list_sessions())
                    return 0
                if session_id is None and arguments.data:
                    created = await service.create_session(arguments.data, arguments.output_dir)
                    session_id = created["session_id"]
                    print(f"创建会话：{session_id}")
                if session_id is None:
                    raise MCPClientError("未获得 session_id")
                print(
                    f"已通过 MCP 协议连接：{health['server']} v{health['version']} | "
                    f"契约版本：{health['contract_version']}"
                )
                await run_workflow(service, session_id)
    except Exception as exc:
        print(f"\n操作停止：{error_text(exc)}", file=sys.stderr)
        if session_id:
            print(f"可使用 --session-id {session_id} 从当前阶段继续。", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n用户中止。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nMCP 客户端启动失败：{error_text(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
