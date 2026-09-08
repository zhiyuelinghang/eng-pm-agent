import asyncio
from copy import deepcopy
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import json
from pathlib import Path
import subprocess
import sys

from agentscope.agent import Agent
from agentscope.app._service._history_tool_presentation import builtin_presentations, enrich_history, fill_presentations
from agentscope.app.memory._direct import direct_memory_tools
from agentscope.app.mcp_registry import MCPPackageTool
from agentscope.message import ToolCallBlock
from agentscope.model import ChatResponse
from agentscope.tool import FunctionTool, Toolkit


def call(name, presentation=None):
    return {"type":"tool_call", "name":name, "id":name, "input":"private-arguments", "presentation":presentation}


def test_existing_builtin_registration_coverage_and_legacy_memory():
    catalogue = builtin_presentations()
    for name in ["TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "Skill", "ToolStop",
                 "ScheduleCreate", "ScheduleList", "ScheduleView", "ScheduleDelete", "agent_cancel",
                 "agent_retry_or_switch", "add_memory", "search_memory"]:
        assert catalogue[name]["source"] != "fallback", name
    assert catalogue["agent_retry_or_switch"]["label"] == "重新安排协同任务"
    assert len(direct_memory_tools(None)) == 5


def test_cold_process_reads_memory_history_without_loading_memory_runtime():
    # This file imports _direct for other tests. A subprocess is essential:
    # reusing the pytest process previously concealed the startup-only failure.
    code = '''
import asyncio, json, sys
sys.path.insert(0, '.')
from types import SimpleNamespace
from unittest.mock import AsyncMock
from agentscope.app._router import _session
from agentscope.message import Msg, ToolCallBlock
assert "agentscope.app.memory._direct" not in sys.modules
async def run():
    names = ["search_memory", "search_memory", "add_memory", "memory_search", "memory_read", "memory_write"]
    original = Msg(id="reply", name="Dobby", role="assistant", content=[
        ToolCallBlock(id=str(i), name=name, input='{"private":"do-not-display"}') for i,name in enumerate(names)])
    storage = SimpleNamespace(get_session=AsyncMock(return_value=object()),
                              list_messages=AsyncMock(return_value=([original], False)))
    bus = SimpleNamespace(is_locked=AsyncMock(return_value=False), registry_getall=AsyncMock(return_value={}))
    _session.require_runtime_session_access = lambda *args: None
    _session.SessionProjection = lambda *args: SimpleNamespace(list=AsyncMock(return_value=[]))
    forbidden_catalog = AsyncMock(side_effect=AssertionError("Memory history needs no remote discovery"))
    state = SimpleNamespace(extra_agent_tool_catalog=forbidden_catalog)
    result = await _session.list_messages(session_id="s",agent_id="a",before=None,offset=None,limit=50,
        user_id="u",principal=object(),storage=storage,message_bus=bus,
        request=SimpleNamespace(app=SimpleNamespace(state=state)))
    forbidden_catalog.assert_not_awaited()
    assert "agentscope.app.memory._direct" not in sys.modules
    assert all(block.presentation is None for block in original.content)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False))
asyncio.run(run())
'''
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True,
                            text=True, encoding="utf-8", timeout=20, check=True)
    blocks = json.loads(result.stdout)["messages"][0]["content"]
    assert [block["presentation"]["label"] for block in blocks] == [
        "回顾相关信息", "回顾相关信息", "记下重要信息", "回顾相关信息", "回顾相关信息", "记下重要信息"]
    assert all(block["presentation"]["source"] == "catalog_backfill" for block in blocks)


def test_runtime_memory_registration_and_history_share_the_same_declarations():
    from agentscope.tool._presentation import tool_presentation
    catalogue = builtin_presentations()
    for tool in direct_memory_tools(None):
        assert tool_presentation(tool) == catalogue[tool.name]


def test_fill_legacy_and_collaboration_without_rewriting_parameters_or_real_snapshots():
    original = {"content":[call("search_memory"), call("TaskList", {"label":"旧版标题", "source":"registration"})],
                "metadata":{"platform_runtime_trace":{"collaborations":[{"activities":[
                    {"kind":"tool", "tool_name":"add_memory", "state":"success"}]}]}}}
    before = deepcopy(original)
    filled = fill_presentations(original, builtin_presentations())
    assert filled["content"][0]["presentation"]["label"] == "回顾相关信息"
    assert filled["content"][0]["presentation"]["source"] == "catalog_backfill"
    assert filled["content"][0]["input"] == "private-arguments"
    assert filled["content"][1]["presentation"]["label"] == "旧版标题"
    activity = filled["metadata"]["platform_runtime_trace"]["collaborations"][0]["activities"][0]
    assert activity["presentation"]["label"] == "记下重要信息"
    assert original == before


def test_mcp_database_history_catalogues_are_cached_and_isolated():
    async def run():
        registry = SimpleNamespace(list_records=AsyncMock(return_value=[
            SimpleNamespace(id="actual-server-id", tools=[MCPPackageTool(name="query", display_name="核对材料清单", read_only=True)])]))
        manager = SimpleNamespace(list_catalog=AsyncMock(return_value=[
            {"key":"db_query", "display_name":"查看项目通知", "read_only":True}]))
        state = SimpleNamespace(mcp_registry_manager=registry, database_interaction_manager=manager)
        storage = SimpleNamespace(get_agent=AsyncMock(return_value=SimpleNamespace(data=SimpleNamespace(tool_config=SimpleNamespace(allowed_tool_names=[])))))
        messages = [{"content":[call("mcp__actual-server-id__query"), call("db_query")]}]
        async def fetch(user):
            return await enrich_history(messages, [], state=state, storage=storage, user_id=user, agent_id="agent")
        first = await fetch("one")
        assert first[0][0]["content"][0]["presentation"]["label"] == "核对材料清单"
        assert first[0][0]["content"][1]["presentation"]["label"] == "查看项目通知"
        assert await fetch("one") == first
        assert registry.list_records.await_count == manager.list_catalog.await_count == 1
        await fetch("two")
        assert manager.list_catalog.await_count == 2
    asyncio.run(run())


def test_ambiguous_mcp_short_names_and_catalogue_errors_do_not_corrupt_history():
    async def run():
        registry = SimpleNamespace(list_records=AsyncMock(return_value=[
            SimpleNamespace(id=name, tools=[MCPPackageTool(name="query", display_name=label)])
            for name,label in [("a","查询采购资料"),("b","查询验收资料")]]))
        state = SimpleNamespace(mcp_registry_manager=registry)
        messages = [{"content":[call("query"),call("mcp__a__query")]}]
        filled, _ = await enrich_history(messages, [], state=state, storage=None, user_id="u", agent_id="a")
        assert filled[0]["content"][0]["presentation"] is None
        assert filled[0]["content"][1]["presentation"]["label"] == "查询采购资料"
        registry.list_records.side_effect = RuntimeError("catalogue unavailable")
        filled, _ = await enrich_history(messages, [], state=state, storage=None, user_id="u2", agent_id="a")
        assert filled == messages
    asyncio.run(run())


def test_complete_model_response_keeps_titles_for_permission_and_resume_context():
    async def run():
        toolkit = Toolkit(tools=[FunctionTool(lambda: None, name="new_tool", display_name="核对资料")])
        await toolkit.get_tool_schemas()
        response = ChatResponse(content=[ToolCallBlock(id="c", name="new_tool", input="{}")], is_last=True)
        agent = SimpleNamespace(toolkit=toolkit, state=SimpleNamespace(reply_id="reply"), model=SimpleNamespace(model="test"),
                                _prepare_model_input=AsyncMock(return_value={}), _call_model=AsyncMock(return_value=response),
                                _save_to_context=Mock())
        agent._convert_chat_response_to_event = MethodType(Agent._convert_chat_response_to_event, agent)
        events = [event async for event in Agent._reasoning_impl(agent)]
        assert events
        saved = agent._save_to_context.call_args.args[0][0]
        assert saved.presentation["label"] == "核对资料"
    asyncio.run(run())


def test_history_route_applies_compatibility_only_after_session_access_check(monkeypatch):
    from fastapi import HTTPException
    from agentscope.app._router import _session
    from agentscope.message import Msg

    async def run():
        original = Msg(id="reply", name="Dobby", role="assistant", content=[
            ToolCallBlock(id="c", name="TaskList", input="{}")])
        storage = SimpleNamespace(get_session=AsyncMock(return_value=object()),
                                  list_messages=AsyncMock(return_value=([original], False)))
        bus = SimpleNamespace(is_locked=AsyncMock(return_value=False), registry_getall=AsyncMock(return_value={}))
        access = Mock()
        monkeypatch.setattr(_session, "require_runtime_session_access", access)
        monkeypatch.setattr(_session, "SessionProjection", lambda _: SimpleNamespace(list=AsyncMock(return_value=[])))
        kwargs = dict(session_id="session", agent_id="agent", before=None, offset=None, limit=50,
                      user_id="owner", principal=object(), storage=storage, message_bus=bus,
                      request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))
        response = await _session.list_messages(**kwargs)
        access.assert_called_once()
        assert response.messages[0]["content"][0]["presentation"]["label"] == "查看执行计划"
        assert original.content[0].presentation is None
        storage.list_messages.reset_mock()
        access.side_effect = HTTPException(status_code=403)
        try:
            await _session.list_messages(**kwargs)
            assert False, "Forbidden session must not be read"
        except HTTPException as exc:
            assert exc.status_code == 403
        storage.list_messages.assert_not_awaited()
    asyncio.run(run())
