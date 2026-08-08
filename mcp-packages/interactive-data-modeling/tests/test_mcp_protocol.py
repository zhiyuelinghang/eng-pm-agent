from __future__ import annotations

import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_server_lists_and_calls_tools(tmp_path) -> None:
    environment = os.environ.copy()
    environment["SHIELD_MCP_WORKDIR"] = str(tmp_path / "runtime")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "shield_prediction_mcp.server"],
        env=environment,
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            by_name = {tool.name: tool for tool in tools.tools}
            assert {
                "predict_check_health",
                "predict_import_data",
                "predict_create_session",
                "predict_profile_data",
                "predict_confirm_variables",
                "predict_propose_pipeline_plan",
                "predict_confirm_pipeline_plan",
                "predict_evaluate_models",
                "predict_export_model",
                "predict_rewind_session",
                "predict_get_status",
                "predict_list_sessions",
                "predict_get_job_status",
            }.issubset(names)
            assert {
                "health_check",
                "create_session",
                "profile_data",
                "confirm_variables",
                "propose_pipeline_plan",
                "confirm_pipeline_plan",
                "evaluate_models",
                "export_model",
                "rewind_session",
                "get_session_state",
                "list_sessions",
                "inspect_preprocessing",
                "apply_preprocessing",
                "propose_training_plan",
                "configure_training_plan",
                "train_models",
                "recommend_models",
                "select_models",
                "configure_training",
            }.isdisjoint(names)
            assert all(name.startswith("predict_") for name in names)
            assert len(names) == 13
            assert all(tool.title for tool in tools.tools)
            assert by_name["predict_import_data"].title == "导入数据文件"
            assert by_name["predict_get_status"].annotations.readOnlyHint is True
            assert by_name["predict_create_session"].annotations.readOnlyHint is False
            assert by_name["predict_rewind_session"].annotations.destructiveHint is True
            result = await session.call_tool("predict_check_health", {})
            assert not result.isError
            assert "interactive-data-modeling" in str(result.content)

            resources = await session.list_resources()
            uris = {str(resource.uri) for resource in resources.resources}
            assert "predict://workflow" in uris

            prompts = await session.list_prompts()
            prompt_names = {prompt.name for prompt in prompts.prompts}
            assert "predict.build_model" in prompt_names
