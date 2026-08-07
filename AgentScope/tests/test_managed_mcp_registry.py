"""Tests for uploaded MCP packages and per-session runtime isolation."""
from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from unittest.mock import AsyncMock

import pytest

from agentscope.app.mcp_registry import (
    MCPPackageConflictError,
    MCPPackageError,
    MCPPackageManifest,
    MCPPackageRecord,
    MCPPackageTool,
    MCPRegistryManager,
    MCPRuntimeCapacityError,
)
from agentscope.app.storage import AgentMCPConfig


def _archive(
    *,
    name: str = "project-data",
    version: str = "1.0.0",
    extra_members: dict[str, bytes] | None = None,
) -> io.BytesIO:
    payload = io.BytesIO()
    manifest = {
        "schema_version": 1,
        "name": name,
        "display_name": "项目数据",
        "version": version,
        "description": "查询项目数据",
        "transport": "stdio",
        "command": "server.exe",
        "args": [],
    }
    with zipfile.ZipFile(payload, "w") as bundle:
        bundle.writestr("project-mcp/mcp.json", json.dumps(manifest))
        bundle.writestr("project-mcp/server.exe", b"complete-package")
        for path, content in (extra_members or {}).items():
            bundle.writestr(path, content)
    payload.seek(0)
    return payload


def _live_archive() -> io.BytesIO:
    """Build a tiny real MCP server package for the protocol smoke test."""
    payload = io.BytesIO()
    manifest = {
        "schema_version": 1,
        "name": "echo-server",
        "display_name": "回声测试",
        "version": "1.0.0",
        "description": "真实 STDIO MCP 启动测试",
        "transport": "stdio",
        "command": "python",
        "args": ["server.py"],
    }
    server = """from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo-server")

@mcp.tool(title="回声")
def echo(value: str) -> str:
    \"\"\"Return the supplied value.\"\"\"
    return value

if __name__ == "__main__":
    mcp.run(transport="stdio")
"""
    with zipfile.ZipFile(payload, "w") as bundle:
        bundle.writestr("echo-mcp/mcp.json", json.dumps(manifest))
        bundle.writestr("echo-mcp/server.py", server)
    payload.seek(0)
    return payload


class _FakeClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.is_connected = False
        self.connect_count = 0
        self.close_count = 0

    async def connect(self) -> None:
        self.connect_count += 1
        self.is_connected = True

    async def close(self) -> None:
        self.close_count += 1
        self.is_connected = False


def test_upload_publishes_verified_package_and_persists_index(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        manager = MCPRegistryManager(tmp_path)
        async with manager:
            probe = AsyncMock(
                return_value=[
                    MCPPackageTool(
                        name="list_projects",
                        display_name="列出项目",
                        description="列出项目",
                        input_schema={"type": "object"},
                        read_only=True,
                    ),
                ],
            )
            monkeypatch.setattr(manager, "_probe_package", probe)

            record = await manager.install_archive(_archive())

            assert record.id == "project-data"
            assert record.manifest.version == "1.0.0"
            assert record.tools[0].name == "list_projects"
            assert record.tools[0].display_name == "列出项目"
            assert (tmp_path / record.relative_dir / "server.exe").is_file()
            index = json.loads((tmp_path / "index.json").read_text("utf-8"))
            assert index["packages"][0]["id"] == "project-data"
            probe.assert_awaited_once()

        reloaded = MCPRegistryManager(tmp_path)
        async with reloaded:
            persisted = await reloaded.get_record("project-data")
            assert persisted is not None
            assert persisted.manifest.version == "1.0.0"
            assert persisted.tools[0].display_name == "列出项目"

    asyncio.run(scenario())


def test_upload_rejects_duplicate_immutable_version(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        manager = MCPRegistryManager(tmp_path)
        async with manager:
            monkeypatch.setattr(manager, "_probe_package", AsyncMock(return_value=[]))
            await manager.install_archive(_archive())
            with pytest.raises(MCPPackageConflictError):
                await manager.install_archive(_archive())

    asyncio.run(scenario())


def test_agent_management_cannot_replace_a_fixed_system_tool(
    tmp_path,
) -> None:
    async def scenario() -> None:
        manager = MCPRegistryManager(
            tmp_path,
            system_tool_package_ids={"attachment-parser"},
        )
        async with manager:
            with pytest.raises(MCPPackageError, match="固定系统工具"):
                await manager.install_archive(
                    _archive(name="attachment-parser"),
                )

    asyncio.run(scenario())


def test_upload_rolls_back_when_index_cannot_be_persisted(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        manager = MCPRegistryManager(tmp_path)
        async with manager:
            monkeypatch.setattr(manager, "_probe_package", AsyncMock(return_value=[]))
            monkeypatch.setattr(
                manager,
                "_save_index",
                AsyncMock(side_effect=OSError("disk full")),
            )
            with pytest.raises(OSError, match="disk full"):
                await manager.install_archive(_archive())

            assert await manager.get_record("project-data") is None
            assert not (tmp_path / "packages" / "project-data" / "1.0.0").exists()

    asyncio.run(scenario())


def test_upload_rejects_path_traversal(tmp_path) -> None:
    async def scenario() -> None:
        manager = MCPRegistryManager(tmp_path)
        payload = _archive(extra_members={"../escape.txt": b"no"})
        async with manager:
            with pytest.raises(MCPPackageError, match="Unsafe path"):
                await manager.install_archive(payload)

    asyncio.run(scenario())
    assert not (tmp_path.parent / "escape.txt").exists()


def test_upload_does_not_reject_dependency_complete_package_by_file_count(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        manager = MCPRegistryManager(tmp_path)
        members = {
            f"project-mcp/packages/module_{index}.py": b""
            for index in range(2100)
        }
        async with manager:
            monkeypatch.setattr(manager, "_probe_package", AsyncMock(return_value=[]))
            record = await manager.install_archive(
                _archive(extra_members=members),
            )
        package_dir = tmp_path / record.relative_dir
        assert len(list((package_dir / "packages").glob("*.py"))) == 2100

    asyncio.run(scenario())


def test_real_stdio_package_can_be_probed_reused_and_called(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        manager = MCPRegistryManager(tmp_path)
        # Production packages ship their own executable. The smoke fixture
        # deliberately reuses the project's embedded interpreter to avoid
        # copying an entire runtime into the test archive.
        monkeypatch.setattr(
            manager,
            "_resolve_command",
            lambda _package_dir, _command: sys.executable,
        )
        async with manager:
            record = await manager.install_archive(_live_archive())
            assert [tool.name for tool in record.tools] == ["echo"]
            assert [tool.display_name for tool in record.tools] == ["回声"]

            clients = await manager.get_session_clients(
                user_id="user",
                agent_id="agent",
                session_id="session-live",
                package_ids=["echo-server"],
            )
            repeated = await manager.get_session_clients(
                user_id="user",
                agent_id="agent",
                session_id="session-live",
                package_ids=["echo-server"],
            )
            assert clients[0] is repeated[0]

            tool = await clients[0].get_tool("echo")
            result = await tool.call(value="MCP ready")
            assert result.content[0].text == "MCP ready"

    asyncio.run(scenario())


def test_platform_gateway_context_is_injected_only_when_requested(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "DOBBY_AGENT_TOOL_BASE_URL",
        "http://gateway.test/api/internal/agent-tools",
    )
    monkeypatch.setenv("DOBBY_AGENT_TOOL_TOKEN", "host-gateway-token")
    monkeypatch.setenv("DOBBY_DATABASE_PATH", str(tmp_path / "platform.db"))
    monkeypatch.setenv("AGENTSCOPE_SERVICE_TOKEN", "broader-service-token")
    monkeypatch.setenv("MINERU_FILE_PARSE_URL", "http://mineru.test/file_parse")
    monkeypatch.setenv("MINERU_BACKEND", "hybrid-engine")
    manager = MCPRegistryManager(tmp_path)

    plain_env = manager._runtime_environment(
        MCPPackageManifest(
            name="plain",
            display_name="普通 MCP",
            version="1.0.0",
            command="server.exe",
        ),
        user_id="user",
        agent_id="agent",
        session_id="session",
    )
    assert "DOBBY_AGENT_TOOL_BASE_URL" not in plain_env
    assert "DOBBY_AGENT_TOOL_TOKEN" not in plain_env
    assert "DOBBY_DATABASE_PATH" not in plain_env
    assert "AGENTSCOPE_SERVICE_TOKEN" not in plain_env
    assert "MINERU_FILE_PARSE_URL" not in plain_env

    gateway_env = manager._runtime_environment(
        MCPPackageManifest(
            name="initialization",
            display_name="项目初始化",
            version="1.0.0",
            command="server.exe",
            env={"DOBBY_AGENT_TOOL_TOKEN": "package-token"},
            platform_capabilities=["dobby_database_interactions"],
        ),
        user_id="user",
        agent_id="agent",
        session_id="session",
    )
    assert gateway_env["DOBBY_AGENT_TOOL_BASE_URL"] == (
        "http://gateway.test/api/internal/agent-tools"
    )
    assert gateway_env["DOBBY_AGENT_TOOL_TOKEN"] == "host-gateway-token"
    assert "MINERU_FILE_PARSE_URL" not in gateway_env
    assert "MINERU_BACKEND" not in gateway_env

    parser_env = manager._runtime_environment(
        MCPPackageManifest(
            name="attachment-parser",
            display_name="附件解析",
            version="2.0.0",
            command="server.exe",
        ),
        user_id="user",
        agent_id="agent",
        session_id="session",
    )
    assert parser_env["MINERU_FILE_PARSE_URL"] == (
        "http://mineru.test/file_parse"
    )
    assert parser_env["MINERU_BACKEND"] == "hybrid-engine"
    assert "AGENTSCOPE_SERVICE_TOKEN" not in gateway_env
    assert gateway_env["AGENTSCOPE_USER_ID"] == "user"
    assert gateway_env["AGENTSCOPE_AGENT_ID"] == "agent"
    assert gateway_env["AGENTSCOPE_SESSION_ID"] == "session"

    database_env = manager._runtime_environment(
        MCPPackageManifest(
            name="database-business-tool",
            display_name="数据库业务工具",
            version="1.0.0",
            command="server.exe",
            env={"DOBBY_DATABASE_PATH": "package-cannot-override.db"},
            platform_capabilities=["dobby_database_interactions"],
        ),
        user_id="user",
        agent_id="project-specialist",
        session_id="worker-session",
        platform_agent_id="initialization-orchestrator",
        platform_session_id="platform-session",
    )
    assert "DOBBY_DATABASE_PATH" not in database_env
    assert database_env["DOBBY_AGENT_TOOL_BASE_URL"].endswith(
        "/api/internal/agent-tools",
    )
    assert database_env["DOBBY_DATABASE_INTERACTION_BASE_URL"].endswith(
        "/api/internal/database-interactions",
    )
    assert database_env["DOBBY_AGENT_TOOL_TOKEN"] == "host-gateway-token"
    assert database_env["AGENTSCOPE_AGENT_ID"] == "project-specialist"
    assert database_env["AGENTSCOPE_SESSION_ID"] == "worker-session"
    assert database_env["DOBBY_PLATFORM_AGENT_ID"] == (
        "initialization-orchestrator"
    )
    assert database_env["DOBBY_PLATFORM_SESSION_ID"] == "platform-session"


def test_runtime_reuses_within_session_and_isolates_between_sessions(
    tmp_path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "packages" / "project-data" / "1.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "server.exe").write_bytes(b"complete-package")
    manager = MCPRegistryManager(tmp_path, max_active_instances=4)
    created: list[_FakeClient] = []

    def _build_client(record, **_kwargs):
        client = _FakeClient(record.id)
        created.append(client)
        return client

    monkeypatch.setattr(manager, "_build_client", _build_client)

    async def scenario() -> None:
        async with manager:
            manager._records["project-data"] = MCPPackageRecord(
                id="project-data",
                manifest=MCPPackageManifest(
                    name="project-data",
                    display_name="项目数据",
                    version="1.0.0",
                    command="server.exe",
                ),
                relative_dir="packages/project-data/1.0.0",
            )

            first = await manager.get_session_clients(
                user_id="user",
                agent_id="agent",
                session_id="session-a",
                package_ids=["project-data"],
            )
            same = await manager.get_session_clients(
                user_id="user",
                agent_id="agent",
                session_id="session-a",
                package_ids=["project-data"],
            )
            other = await manager.get_session_clients(
                user_id="user",
                agent_id="agent",
                session_id="session-b",
                package_ids=["project-data"],
            )

            assert first[0] is same[0]
            assert other[0] is not first[0]
            assert len(created) == 2
            await manager.close_session("session-a")
            assert created[0].close_count == 1
            assert created[1].is_connected

    asyncio.run(scenario())


def test_system_tool_is_hidden_from_assignment_and_loaded_for_every_agent(
    tmp_path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "packages" / "attachment-parser" / "1.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "server.exe").write_bytes(b"complete-package")
    manager = MCPRegistryManager(
        tmp_path,
        system_tool_package_ids={"attachment-parser"},
    )
    created: list[_FakeClient] = []

    def _build_client(record, **_kwargs):
        client = _FakeClient(record.id)
        created.append(client)
        return client

    monkeypatch.setattr(manager, "_build_client", _build_client)

    async def scenario() -> None:
        async with manager:
            manager._records["attachment-parser"] = MCPPackageRecord(
                id="attachment-parser",
                manifest=MCPPackageManifest(
                    name="attachment-parser",
                    display_name="附件解析",
                    version="1.0.0",
                    command="server.exe",
                ),
                relative_dir="packages/attachment-parser/1.0.0",
                tools=[
                    MCPPackageTool(
                        name="parse_attachment",
                        display_name="解析附件",
                    ),
                ],
            )

            assert await manager.list_views(set()) == []
            system_records = await manager.list_system_tool_records()
            assert [record.id for record in system_records] == [
                "attachment-parser",
            ]

            first = await manager.get_session_clients(
                user_id="user",
                agent_id="agent-a",
                session_id="session-a",
                package_ids=[],
            )
            repeated = await manager.get_session_clients(
                user_id="user",
                agent_id="agent-a",
                session_id="session-a",
                package_ids=[],
            )

            assert [client.name for client in first] == ["attachment-parser"]
            assert first[0] is repeated[0]
            assert len(created) == 1

    asyncio.run(scenario())


def test_runtime_enforces_process_capacity(tmp_path, monkeypatch) -> None:
    package_dir = tmp_path / "packages" / "project-data" / "1.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "server.exe").write_bytes(b"complete-package")
    manager = MCPRegistryManager(tmp_path, max_active_instances=1)
    monkeypatch.setattr(
        manager,
        "_build_client",
        lambda record, **_kwargs: _FakeClient(record.id),
    )

    async def scenario() -> None:
        async with manager:
            manager._records["project-data"] = MCPPackageRecord(
                id="project-data",
                manifest=MCPPackageManifest(
                    name="project-data",
                    display_name="项目数据",
                    version="1.0.0",
                    command="server.exe",
                ),
                relative_dir="packages/project-data/1.0.0",
            )
            await manager.get_session_clients(
                user_id="user",
                agent_id="agent",
                session_id="session-a",
                package_ids=["project-data"],
            )
            with pytest.raises(MCPRuntimeCapacityError):
                await manager.get_session_clients(
                    user_id="user",
                    agent_id="agent",
                    session_id="session-b",
                    package_ids=["project-data"],
                )

    asyncio.run(scenario())


def test_agent_mcp_config_normalises_assignment_ids() -> None:
    config = AgentMCPConfig(
        allowed_mcp_ids=[" project-data ", "project-data", "", "files"],
    )
    assert config.allowed_mcp_ids == ["project-data", "files"]
