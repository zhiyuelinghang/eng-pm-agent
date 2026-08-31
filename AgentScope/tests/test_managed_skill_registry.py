# -*- coding: utf-8 -*-
"""Tests for the platform-managed skill package registry."""
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from agentscope.app import create_app
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.skill_registry import SkillRegistryManager
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager


@pytest.mark.asyncio
async def test_create_update_assign_and_retain_versions(tmp_path) -> None:
    manager = SkillRegistryManager(tmp_path / "skills")
    async with manager:
        created = await manager.create_skill(
            name="工程风险复核",
            description="复核风险结论与证据。",
            markdown="# 执行步骤\n\n1. 核对证据。",
        )
        assert created.version == 1
        assert (await manager.list_views({created.id}))[0].assigned is True

        updated = await manager.update_skill(
            created.id,
            name="工程风险复核",
            description="复核风险结论、证据与措施。",
            markdown="# 执行步骤\n\n1. 核对证据。\n2. 检查措施。",
        )
        assert updated.version == 2
        assert [
            item.version
            for item in await manager.list_version_records(created.id)
        ] == [2, 1]

        skills = await manager.get_assigned_skills([created.id])
        assert len(skills) == 1
        assert skills[0].name == "工程风险复核"
        assert "检查措施" in skills[0].markdown


def test_http_create_assign_version_and_download(tmp_path) -> None:
    """The real app exposes skill maintenance and persists assignments."""
    storage = AsyncSQLAlchemyStorage(
        f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        create_tables=True,
    )
    manager = SkillRegistryManager(tmp_path / "skills")
    app = create_app(
        storage=storage,
        message_bus=InMemoryMessageBus(),
        workspace_manager=LocalWorkspaceManager(
            basedir=str(Path(tmp_path) / "workspaces"),
        ),
        skill_registry_manager=manager,
    )
    headers = {"X-User-ID": "skill-registry-test"}

    with TestClient(app) as client:
        agent_response = client.post(
            "/agent/",
            headers=headers,
            json={"name": "技能联调智能体"},
        )
        assert agent_response.status_code == 201
        agent_id = agent_response.json()["agent_id"]

        created_response = client.post(
            "/skill-registry/",
            headers=headers,
            json={
                "name": "任务梳理",
                "description": "从上下文中梳理任务。",
                "markdown": "# 步骤\n\n1. 排除干扰项目。",
            },
        )
        assert created_response.status_code == 201
        package_id = created_response.json()["id"]

        assignment_response = client.patch(
            f"/agent/{agent_id}",
            headers=headers,
            json={"skill_config": {"allowed_skill_ids": [package_id]}},
        )
        assert assignment_response.status_code == 200
        assert assignment_response.json()["data"]["skill_config"] == {
            "allowed_skill_ids": [package_id],
        }

        catalogue_response = client.get(
            "/skill-registry/",
            headers=headers,
            params={"agent_id": agent_id},
        )
        assert catalogue_response.status_code == 200
        assert catalogue_response.json()[0]["assigned"] is True

        updated_response = client.put(
            f"/skill-registry/{package_id}",
            headers=headers,
            json={
                "name": "任务梳理",
                "description": "从上下文中梳理并校验任务。",
                "markdown": "# 步骤\n\n1. 排除干扰项目。\n2. 校验任务。",
            },
        )
        assert updated_response.status_code == 200
        assert updated_response.json()["version"] == 2

        versions_response = client.get(
            f"/skill-registry/{package_id}/versions",
            headers=headers,
        )
        assert versions_response.status_code == 200
        assert [item["version"] for item in versions_response.json()] == [2, 1]

        download_response = client.get(
            f"/skill-registry/{package_id}/versions/1/download",
            headers=headers,
        )
        assert download_response.status_code == 200
        assert download_response.headers["content-type"] == "application/zip"

        delete_response = client.delete(
            f"/skill-registry/{package_id}",
            headers=headers,
        )
        assert delete_response.status_code == 409
