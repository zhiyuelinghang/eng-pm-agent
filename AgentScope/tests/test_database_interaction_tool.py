import asyncio
import json
from unittest.mock import AsyncMock

from agentscope.app.database_interactions import (
    DatabaseInteractionTool,
    create_database_interaction_tools,
    runtime_argument_error,
)
from agentscope.message import ToolResultState


ATTACHMENT_POLICY = {
    "argument_guard": {
        "type": "single_record_text_page",
        "content_field": "content",
        "max_page_size": 6000,
    },
}
SECTION_POLICY = {
    "argument_guard": {
        "type": "single_partition_json_page",
        "payload_field": "payload",
        "partition_field": "section",
        "max_page_size": 20,
        "partitions": {
            "project": {"paged": False},
            "wbs": {"paged": True},
        },
    },
}


def test_attachment_content_requires_one_bounded_text_page() -> None:
    assert runtime_argument_error(ATTACHMENT_POLICY, {}) is not None
    assert runtime_argument_error(
        ATTACHMENT_POLICY,
        {"fields": ["id", "file_id", "chunk_index"]},
    ) is None
    assert runtime_argument_error(
        ATTACHMENT_POLICY,
        {"fields": ["id", "content"], "record_id": 7, "limit": 1},
    ) is not None
    assert runtime_argument_error(
        ATTACHMENT_POLICY,
        {
            "fields": ["id", "content"],
            "record_id": 7,
            "limit": 1,
            "text_field": "content",
            "text_offset": 0,
            "text_limit": 6000,
        },
    ) is None
    assert runtime_argument_error(
        ATTACHMENT_POLICY,
        {
            "fields": ["id", "content"],
            "record_ids": [7, 8],
            "limit": 1,
            "text_field": "content",
            "text_offset": 0,
            "text_limit": 6000,
        },
    ) is not None


def test_section_payload_requires_one_partition_and_bounded_json_page() -> None:
    assert runtime_argument_error(
        SECTION_POLICY,
        {"fields": ["id", "section"], "limit": 20},
    ) is None
    assert runtime_argument_error(
        SECTION_POLICY,
        {"fields": ["section", "payload"], "limit": 1},
    ) is not None
    assert runtime_argument_error(
        SECTION_POLICY,
        {
            "fields": ["section", "payload"],
            "filters": {"section": "project"},
            "limit": 1,
        },
    ) is None
    assert runtime_argument_error(
        SECTION_POLICY,
        {
            "fields": ["section", "payload"],
            "filters": {"section": "wbs"},
            "limit": 1,
        },
    ) is not None
    assert runtime_argument_error(
        SECTION_POLICY,
        {
            "fields": ["section", "payload"],
            "filters": {"section": "wbs"},
            "limit": 1,
            "json_field": "payload",
            "json_offset": 0,
            "json_limit": 20,
        },
    ) is None


def test_successful_write_uses_declarative_team_completion_metadata() -> None:
    manager = AsyncMock()
    manager.execute_interaction.return_value = {
        "success": True,
        "data": {"id": 12},
    }
    tool = DatabaseInteractionTool(
        definition={
            "key": "submit_section",
            "description": "提交草稿分区",
            "input_schema": {"type": "object"},
            "read_only": False,
            "requires_confirmation": False,
            "runtime_policy": {
                "team_completion": {
                    "enabled": True,
                    "message": "草稿分区已持久化。",
                },
            },
        },
        manager=manager,
        session_id="session-1",
        actor_agent_id="worker-1",
        platform_agent_id="main-1",
    )

    result = asyncio.run(tool.call(payload={"name": "工程"}))

    assert result.state == ToolResultState.SUCCESS
    assert json.loads(result.content[0].text)["success"] is True
    assert result.metadata["platform_data_changed"] is True
    assert result.metadata["team_report_on_success"] is True
    assert result.metadata["team_report_message"] == "草稿分区已持久化。"


def test_builder_loads_only_current_agent_assignments() -> None:
    manager = AsyncMock()
    manager.resolve_context.return_value = {"agent_id": "platform-agent"}
    manager.list_runtime.return_value = [
        {
            "key": "read_project",
            "description": "读取项目",
            "input_schema": {"type": "object"},
            "read_only": True,
        },
        {
            "key": "write_project",
            "description": "更新项目",
            "input_schema": {"type": "object"},
            "read_only": False,
        },
    ]

    tools = asyncio.run(
        create_database_interaction_tools(
            manager=manager,
            agent_id="worker-agent",
            session_id="worker-session",
            platform_agent_id="platform-agent",
            platform_session_id="platform-session",
            read_only=True,
        ),
    )

    assert [tool.name for tool in tools] == ["read_project"]
    manager.resolve_context.assert_awaited_once_with("platform-session")
    manager.list_runtime.assert_awaited_once_with(
        agent_id="worker-agent",
        session_id="platform-session",
        legacy_allowed_names=None,
    )
