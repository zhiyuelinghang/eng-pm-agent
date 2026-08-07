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
    validate_project_initialization,
)
from agentscope.app.mcp_registry import MCPPackageManifest, MCPPackageRecord
from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk


def _record() -> MCPPackageRecord:
    return MCPPackageRecord(
        id="project-initialization-validator",
        manifest=MCPPackageManifest(
            name="project-initialization-validator",
            display_name="项目初始化核验",
            version="2.1.0",
            command="server.exe",
            platform_capabilities=["project_initialization_validation"],
        ),
        relative_dir="packages/project-initialization-validator/2.1.0",
    )


def test_management_principal_cannot_execute_platform_validator() -> None:
    async def scenario() -> None:
        with pytest.raises(HTTPException) as captured:
            await validate_project_initialization(
                ProjectInitializationValidationRequest(payload={}),
                principal=AgentScopePrincipal(kind="management", subject="admin"),
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
                manager=manager,
            )
        assert captured.value.status_code == 503

    asyncio.run(scenario())


def test_platform_validator_executes_the_fixed_package_and_tool() -> None:
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
            manager=manager,
        )

        assert response["package_id"] == "project-initialization-validator"
        assert response["package_version"] == "2.1.0"
        assert response["result"] == result
        assert response["duration_ms"] >= 0
        manager.get_platform_client.assert_awaited_once_with(
            "project-initialization-validator",
            runtime_id="project-initialization-validation",
        )
        client.get_tool.assert_awaited_once_with("validate_project_initialization")
        tool.call.assert_awaited_once_with(draft={"project": {}})

    asyncio.run(scenario())
