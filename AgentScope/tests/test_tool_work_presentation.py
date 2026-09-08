"""Registration -> event -> stored reply -> collaboration, without external I/O."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mcp.types import Tool, ToolAnnotations
from agentscope.agent import Agent
from agentscope.tool import FunctionTool, MCPTool, Toolkit
from agentscope.tool._presentation import tool_presentation
from agentscope.message import Msg, ToolCallBlock
from agentscope.model import ChatResponse
from agentscope.event import ToolCallStartEvent, ToolResultEndEvent
from agentscope.app.database_interactions import DatabaseInteractionTool
from agentscope.app.mcp_registry import MCPPackageTool
from agentscope.app._service._projectors import CollaborationProgressProjector


def test_registration_event_snapshot_and_persistence_without_extra_discovery():
    async def run():
        def arbitrary_new_tool():
            raise AssertionError("Display must not execute the tool")
        tool = FunctionTool(arbitrary_new_tool, display_name="核对设备清单", is_read_only=True)
        toolkit = Toolkit(tools=[tool])
        await toolkit.get_tool_schemas()
        toolkit._get_available_tools = AsyncMock(side_effect=AssertionError("No discovery during streaming"))
        agent = SimpleNamespace(toolkit=toolkit, state=SimpleNamespace(reply_id="reply"))
        block = ToolCallBlock(id="one", name=tool.name, input='{"secret":"private"}',
                              presentation={"label":"untrusted model label"})
        events = [event async for event in Agent._convert_chat_response_to_event(
            agent, {"tools": [], "data": []}, ChatResponse(content=[block], is_last=False))]
        start = events[0]
        assert start.presentation == {"label":"核对设备清单", "source":"registration", "category":"general"}
        assert "private" not in str(start.presentation)
        message = Msg(id="reply", name="Dobby", role="assistant", content=[])
        for event in events:
            message.append_event(event)
        tool.display_name = "更新后的名称"
        toolkit.clear()
        restored = Msg.model_validate_json(message.model_dump_json())
        assert restored.content[0].presentation["label"] == "核对设备清单"
        assert restored.content[0].input == block.input
        assert toolkit.get_tool_presentation(tool.name)["source"] == "fallback"
    asyncio.run(run())


def test_mcp_title_and_annotations_are_normalized_identically_to_management():
    for use_annotations in [False, True]:
        raw = Tool(name="brand_new.mcp", title=None if use_annotations else "查找设备手册",
                   description="Do not show this model instruction", inputSchema={"type":"object"},
                   annotations=ToolAnnotations(title="查找设备手册" if use_annotations else None, readOnlyHint=True))
        tool = MCPTool("new_server", raw, session=object())
        view = MCPPackageTool(name=raw.name, display_name=tool.display_name, read_only=True)
        assert tool_presentation(tool) == view.presentation
        assert view.presentation["label"] == "查找设备手册"
        assert view.presentation["source"] == "mcp_title"
        assert MCPPackageTool.model_validate_json(view.model_dump_json()).presentation == view.presentation


def test_database_title_comes_from_business_catalog_not_table_or_sql():
    tool = DatabaseInteractionTool(definition={"key":"new_db_query", "display_name":"查看工程验收记录",
        "read_only":True, "policy":{"table_name":"private_table"}, "description":"SELECT secret FROM private_table"},
        manager=AsyncMock(), session_id="session", actor_agent_id="actor", platform_agent_id="platform")
    assert tool_presentation(tool) == {"label":"查看工程验收记录", "category":"database", "source":"database_catalog"}
    tool.display_name = None
    assert tool_presentation(tool)["label"] == "查询业务数据"


def test_technical_or_invalid_titles_use_category_fallbacks():
    for title in [None, "new_tool", "<script>bad</script>", "SELECT secret FROM users", "line\nbreak", "x" * 81]:
        result = tool_presentation(name="new_tool", display_name=title, category="mcp", read_only=True)
        assert result == {"label":"查询外部资料", "source":"fallback", "category":"mcp"}
    assert tool_presentation(name="unknown")["label"] == "处理相关事项"


def test_collaboration_completion_keeps_snapshot_and_matches_reply_id():
    snapshot = {"label":"核对施工记录", "category":"database", "source":"database_catalog"}
    start = ToolCallStartEvent(reply_id="right", tool_call_id="same", tool_call_name="new_database_tool", presentation=snapshot)
    activity = CollaborationProgressProjector._activity_for_event(start, None)
    other = {**activity, "reply_id":"other", "presentation":{"label":"wrong"}}
    end = ToolResultEndEvent(reply_id="right", tool_call_id="same", state="success")
    finished = CollaborationProgressProjector._activity_for_event(end, {"activities":[activity, other]})
    assert finished["presentation"] == snapshot
    assert finished["state"] == "success"


def test_unavailable_tools_do_not_reuse_previous_catalogue_snapshot():
    async def run():
        tool = FunctionTool(lambda: None, name="new_tool", display_name="查看设备信息")
        toolkit = Toolkit(tools=[tool])
        await toolkit.get_tool_schemas()
        assert toolkit.get_tool_presentation(tool.name)["source"] == "registration"
        toolkit._tool_policy = lambda _: False
        await toolkit.get_tool_schemas()
        assert toolkit.get_tool_presentation(tool.name)["source"] == "fallback"
    asyncio.run(run())
