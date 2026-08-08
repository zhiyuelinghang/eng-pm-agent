"""Tests for the narrow platform-owned initialization validator route."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from agentscope.app._auth import AgentScopePrincipal
from agentscope.app._router._mcp_registry import (
    ProjectInitializationValidationRequest,
    delete_project_initialization_validation_mcp_version,
    validate_project_initialization,
)
from agentscope.app.mcp_registry import MCPPackageManifest, MCPPackageRecord
from agentscope.app.mcp_registry import MCPPackageTool
from agentscope.app.storage import (
    PlatformMCPVersionBinding,
    PlatformSettingsData,
    PlatformSettingsRecord,
)
from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk


def _record() -> MCPPackageRecord:
    return MCPPackageRecord(
        id="custom-validation-rules",
        manifest=MCPPackageManifest(
            name="custom-validation-rules",
            display_name="项目初始化核验",
            version="2.1.0",
            command="server.exe",
            platform_capabilities=["project_initialization_validation"],
        ),
        relative_dir="packages/custom-validation-rules/2.1.0",
        tools=[MCPPackageTool(name="run_validation_rules")],
    )


def _storage() -> SimpleNamespace:
    return SimpleNamespace(
        get_platform_settings=AsyncMock(
            return_value=PlatformSettingsRecord(
                user_id="default",
                data=PlatformSettingsData(
                    project_initializer_validation_mcp=(
                        PlatformMCPVersionBinding(
                            package_id="custom-validation-rules",
                            version="2.1.0",
                        )
                    ),
                ),
            ),
        ),
    )


def test_management_principal_cannot_execute_platform_validator() -> None:
    async def scenario() -> None:
        with pytest.raises(HTTPException) as captured:
            await validate_project_initialization(
                ProjectInitializationValidationRequest(payload={}),
                principal=AgentScopePrincipal(kind="management", subject="admin"),
                user_id="default",
                storage=_storage(),
                manager=SimpleNamespace(),
            )
        assert captured.value.status_code == 403

    asyncio.run(scenario())


def test_missing_platform_validator_returns_service_unavailable() -> None:
    async def scenario() -> None:
        manager = SimpleNamespace(get_record=AsyncMock(return_value=None))
        with pytest.raises(HTTPException) as captured:
            await validate_project_initialization(
                ProjectInitializationValidationRequest(payload={}),
                principal=AgentScopePrincipal(kind="service", subject="platform"),
                user_id="default",
                storage=_storage(),
                manager=manager,
            )
        assert captured.value.status_code == 503

    asyncio.run(scenario())


def test_platform_validator_executes_the_selected_package_version_and_tool() -> None:
    async def scenario() -> None:
        result = {
            "ruleset_version": "2026.08.2",
            "status": "ready",
            "validation_issues": [],
        }
        tool = SimpleNamespace(
            call=AsyncMock(
                return_value=ToolChunk(
                    content=[TextBlock(text=json.dumps(result))],
                    state=ToolResultState.SUCCESS,
                ),
            ),
        )
        client = SimpleNamespace(get_tool=AsyncMock(return_value=tool))
        manager = SimpleNamespace(
            get_record=AsyncMock(return_value=_record()),
            get_platform_client=AsyncMock(return_value=client),
        )

        response = await validate_project_initialization(
            ProjectInitializationValidationRequest(payload={"project": {}}),
            principal=AgentScopePrincipal(kind="service", subject="platform"),
            user_id="default",
            storage=_storage(),
            manager=manager,
        )

        assert response["package_id"] == "custom-validation-rules"
        assert response["package_version"] == "2.1.0"
        assert response["tool_name"] == "run_validation_rules"
        assert response["result"] == result
        assert response["duration_ms"] >= 0
        manager.get_platform_client.assert_awaited_once_with(
            "custom-validation-rules",
            runtime_id="project-initialization-validation",
            version="2.1.0",
        )
        manager.get_record.assert_awaited_once_with(
            "custom-validation-rules",
            "2.1.0",
        )
        client.get_tool.assert_awaited_once_with("run_validation_rules")
        tool.call.assert_awaited_once_with(draft={"project": {}})

    asyncio.run(scenario())


def test_selected_validation_version_cannot_be_deleted() -> None:
    async def scenario() -> None:
        manager = SimpleNamespace(
            get_record=AsyncMock(return_value=_record()),
            delete_version=AsyncMock(return_value=True),
        )
        with pytest.raises(HTTPException) as captured:
            await delete_project_initialization_validation_mcp_version(
                "custom-validation-rules",
                "2.1.0",
                user_id="default",
                storage=_storage(),
                manager=manager,
            )

        assert captured.value.status_code == 409
        manager.delete_version.assert_not_awaited()

    asyncio.run(scenario())


def test_unselected_validation_version_can_be_deleted() -> None:
    async def scenario() -> None:
        candidate = _record().model_copy(deep=True)
        candidate.manifest.version = "2.0.0"
        manager = SimpleNamespace(
            get_record=AsyncMock(return_value=candidate),
            active_version_instances=AsyncMock(return_value=0),
            delete_version=AsyncMock(return_value=True),
        )

        await delete_project_initialization_validation_mcp_version(
            "custom-validation-rules",
            "2.0.0",
            user_id="default",
            storage=_storage(),
            manager=manager,
        )

        manager.delete_version.assert_awaited_once_with(
            "custom-validation-rules",
            "2.0.0",
        )

    asyncio.run(scenario())
