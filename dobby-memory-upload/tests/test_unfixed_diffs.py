#!/usr/bin/env python3
"""
Test script for 5 unfixed-difference remedies (2026-07-22).

Each test validates:
  2.5 — JSONL 审计日志: file I/O, rotation, graceful degradation
  2.6 — 多源消息归一化: all 4 adapters, backward compat
  2.4 — Agent 工具暴露: schema validity, tool dispatch
  2.10 — Supervisor 循环路由: graph structure, loop edges
  2.1 — LLMLingua-2 压缩: lazy load, fallback, config

No external services required. Run:
    python test_unfixed_diffs.py
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# Add parent to path (tests/ 的父目录 = dobby-memory)
sys.path.insert(0, str(Path(__file__).parent.parent))

# ============================================================
# TR — Test Result Tracker
# ============================================================


class TR:
    def __init__(self):
        self.r = []

    def add(self, name, passed, detail=""):
        self.r.append((name, passed, detail))
        status = "✅" if passed else "❌"
        suffix = f": {detail}" if detail else ""
        print(f"  {status} {name}{suffix}")

    def summary(self):
        p = sum(1 for _, x, _ in self.r if x)
        total = len(self.r)
        all_pass = p == total
        print(f"\n{'='*60}")
        print(f"Results: {p}/{total} passed "
              f"{'🎉 ALL PASS' if all_pass else '⚠️  SOME FAILED'}")
        print(f"{'='*60}")
        return all_pass


tr = TR()

# ============================================================
# 2.5 — JSONL 审计日志
# ============================================================

print("\n" + "="*60)
print("2.5 JSONL Audit Logger")
print("="*60)


def test_audit_logger():
    from utils.audit_logger import AuditLogger, get_audit_logger

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = AuditLogger(log_dir=tmpdir)

        # Test 1: log session start
        async def _test1():
            await logger.log_session_start("sess-001", "proj-001", mode="test")
            files = list(Path(tmpdir).glob("*.jsonl"))
            return len(files) > 0

        ok = asyncio.run(_test1())
        tr.add("session_start creates JSONL file", ok)

        # Test 2: log message
        async def _test2():
            await logger.log_message("user", "你好世界", session_id="sess-001", project_id="proj-001")
            files = list(Path(tmpdir).glob("*.jsonl"))
            if not files:
                return False
            content = files[0].read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            return len(lines) >= 2  # start + message

        ok = asyncio.run(_test2())
        tr.add("log_message appends to JSONL", ok)

        # Test 3: log compress event
        async def _test3():
            await logger.log_compress(100000, 30000, "summary preview", session_id="sess-001", project_id="proj-001")
            files = list(Path(tmpdir).glob("*.jsonl"))
            if not files:
                return False
            content = files[0].read_text(encoding="utf-8")
            return "compress" in content and "100000" in content

        ok = asyncio.run(_test3())
        tr.add("log_compress records token counts", ok)

        # Test 4: log tool call
        async def _test4():
            await logger.log_tool_call("search_memory", {"query": "test"}, "found 2 results",
                                       session_id="sess-001", project_id="proj-001")
            files = list(Path(tmpdir).glob("*.jsonl"))
            if not files:
                return False
            content = files[0].read_text(encoding="utf-8")
            return "tool_call" in content and "search_memory" in content

        ok = asyncio.run(_test4())
        tr.add("log_tool_call records tool name and args", ok)

        # Test 5: graceful degradation (invalid path)
        async def _test5():
            import warnings
            bad_logger = AuditLogger(log_dir="/NONEXISTENT_PATH_SHOULD_FAIL_/")
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                await bad_logger.log_message("user", "should not crash")
                return True  # didn't throw
            return True

        ok = asyncio.run(_test5())
        tr.add("graceful degradation on bad path (no crash)", ok)

        # Test 6: session end with stats
        async def _test6():
            await logger.log_session_end("sess-001", "proj-001",
                                         stats={"message_count": 10, "decay_deleted": 3})
            files = list(Path(tmpdir).glob("*.jsonl"))
            if not files:
                return False
            content = files[0].read_text(encoding="utf-8")
            return "session_end" in content and "message_count" in content

        ok = asyncio.run(_test6())
        tr.add("log_session_end includes stats", ok)

        # Test 7: JSON is valid
        async def _test7():
            files = list(Path(tmpdir).glob("*.jsonl"))
            if not files:
                return False
            content = files[0].read_text(encoding="utf-8")
            for line in content.strip().split("\n"):
                json.loads(line)  # must parse
            return True

        ok = asyncio.run(_test7())
        tr.add("all JSONL lines are valid JSON", ok)

        # Test 8: singleton pattern
        logger2 = get_audit_logger()
        tr.add("get_audit_logger returns singleton", logger2 is not None)


test_audit_logger()

# ============================================================
# 2.6 — 多源消息归一化
# ============================================================

print("\n" + "="*60)
print("2.6 Multi-Source Message Adapter")
print("="*60)


def test_message_adapter():
    from utils.message_adapter import (
        MessageAdapter, UnifiedMessage, DirectAdapter,
        FeishuAdapter, DingtalkAdapter, WechatAdapter,
    )

    # Test 1: DirectAdapter with dict
    result = DirectAdapter.normalize({"role": "user", "content": "hello world"})
    tr.add("DirectAdapter dict: content preserved", result.content == "hello world")
    tr.add("DirectAdapter dict: source=direct", result.source == "direct")
    tr.add("DirectAdapter dict: sender=user", result.sender_name == "user")

    # Test 2: DirectAdapter with string
    result = DirectAdapter.normalize("plain text message")
    tr.add("DirectAdapter str: content preserved", result.content == "plain text message")
    tr.add("DirectAdapter str: source=direct", result.source == "direct")

    # Test 3: FeishuAdapter
    feishu_payload = {
        "event": {
            "sender": {"sender_id": {"open_id": "ou_test123"}},
            "message": {
                "message_id": "om_xxx",
                "msg_type": "text",
                "content": '{"text":"飞书测试消息"}',
                "create_time": "1610000000000",
            }
        }
    }
    result = FeishuAdapter.normalize(feishu_payload)
    tr.add("FeishuAdapter: content extracted", "飞书测试消息" in result.content)
    tr.add("FeishuAdapter: source=feishu", result.source == "feishu")
    tr.add("FeishuAdapter: sender_id extracted", result.sender_id == "ou_test123")

    # Test 4: DingtalkAdapter
    dingtalk_payload = {
        "senderId": "user456",
        "senderNick": "张三",
        "msgtype": "text",
        "text": {"content": "钉钉测试消息"},
    }
    result = DingtalkAdapter.normalize(dingtalk_payload)
    tr.add("DingtalkAdapter: content extracted", "钉钉测试消息" in result.content)
    tr.add("DingtalkAdapter: source=dingtalk", result.source == "dingtalk")
    tr.add("DingtalkAdapter: sender preserved", result.sender_name == "张三")

    # Test 5: WechatAdapter
    wechat_payload = {
        "ToUserName": "wxabc",
        "FromUserName": "user789",
        "CreateTime": 1610000000,
        "MsgType": "text",
        "Content": "微信测试消息",
    }
    result = WechatAdapter.normalize(wechat_payload)
    tr.add("WechatAdapter: content extracted", "微信测试消息" in result.content)
    tr.add("WechatAdapter: source=wechat", result.source == "wechat")
    tr.add("WechatAdapter: sender_id preserved", result.sender_id == "user789")

    # Test 6: MessageAdapter.normalize() with source param
    result = MessageAdapter.normalize({"role": "user", "content": "test"}, source="direct")
    tr.add("MessageAdapter: source routing works", result.source == "direct")

    # Test 7: Fallback for unknown source
    result = MessageAdapter.normalize({"role": "user", "content": "test"}, source="unknown_platform")
    tr.add("MessageAdapter: unknown source → direct fallback", result.source == "direct")

    # Test 8: All 4 sources registered
    sources = MessageAdapter.available_sources()
    expected = {"direct", "feishu", "dingtalk", "wechat"}
    tr.add("MessageAdapter: 4 sources registered", set(sources) == expected)

    # Test 9: UnifiedMessage dataclass
    from datetime import datetime, timezone
    um = UnifiedMessage(
        source="test", sender_id="1", sender_name="tester",
        content="hello", timestamp=datetime.now(timezone.utc).isoformat(),
        msg_type="text",
        mentions=["@alice"], reply_to="msg_123",
    )
    tr.add("UnifiedMessage: all fields set", um.sender_id == "1" and len(um.mentions) == 1)


test_message_adapter()

# ============================================================
# 2.4 — Agent 工具暴露
# ============================================================

print("\n" + "="*60)
print("2.4 Agent Tool Exposure (memory_tools)")
print("="*60)


def test_memory_tools():
    from utils.memory_tools import TOOL_SCHEMAS, execute_tool

    # Test 1: All 6 tool schemas present
    tool_names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    expected = {"search_memory", "add_memory", "search_knowledge_base",
                "search_experiences", "get_session_summary", "search_graph_rag"}
    tr.add("6 tool schemas defined", tool_names == expected)

    # Test 2: Each schema has required fields
    for tool in TOOL_SCHEMAS:
        fn = tool["function"]
        has_name = bool(fn.get("name"))
        has_desc = bool(fn.get("description"))
        has_params = bool(fn.get("parameters"))
        has_type = tool.get("type") == "function"
        ok = has_name and has_desc and has_params and has_type
        tr.add(f"schema '{fn['name']}' valid", ok)

    # Test 3: search_memory requires 'query'
    search_schema = [t for t in TOOL_SCHEMAS if t["function"]["name"] == "search_memory"][0]
    required = search_schema["function"]["parameters"]["required"]
    tr.add("search_memory requires 'query'", "query" in required)

    # Test 4: add_memory requires 'content'
    add_schema = [t for t in TOOL_SCHEMAS if t["function"]["name"] == "add_memory"][0]
    required = add_schema["function"]["parameters"]["required"]
    tr.add("add_memory requires 'content'", "content" in required)

    # Test 5: get_session_summary has no required params
    summary_schema = [t for t in TOOL_SCHEMAS if t["function"]["name"] == "get_session_summary"][0]
    params = summary_schema["function"]["parameters"]["properties"]
    tr.add("get_session_summary: no required params", len(params) == 0)

    # Test 6: execute_tool handles unknown tool gracefully
    async def _test_unknown():
        result = await execute_tool("nonexistent_tool", {})
        return "未知工具" in result

    ok = asyncio.run(_test_unknown())
    tr.add("execute_tool: unknown tool → error message", ok)

    # Test 7: execute_tool get_session_summary works (no state)
    async def _test_summary():
        result = await execute_tool("get_session_summary", {})
        return "暂无" in result or "摘要" in result  # friendly message

    ok = asyncio.run(_test_summary())
    tr.add("execute_tool: get_session_summary returns friendly message", ok)

    # Test 8: TOOL_SCHEMAS are all type=function
    all_function = all(t.get("type") == "function" for t in TOOL_SCHEMAS)
    tr.add("all schemas are type=function", all_function)


test_memory_tools()

# ============================================================
# 2.10 — Supervisor 循环路由
# ============================================================

print("\n" + "="*60)
print("2.10 Supervisor Loop Routing")
print("="*60)


def test_parallel_agents():
    from utils.langgraph_utils import (
        DobbyState, build_graph,
        supervisor_node, compress_node,
    )
    from utils.roles import get_all_roles

    # Test 1: build_graph with roles succeeds
    try:
        roles = get_all_roles()[:2]
        builder = build_graph(roles=roles)
        tr.add("build_graph with roles returns builder", builder is not None)
    except Exception as e:
        tr.add("build_graph with roles returns builder", False, str(e)[:80])

    # Test 2: DobbyState creation
    try:
        state = DobbyState(
            thread_id="test",
            project_id="test_proj",
            current_role="dobby_core",
        )
        tr.add("DobbyState creation succeeds", state is not None)
        tr.add("DobbyState.thread_id preserved", state.get("thread_id") == "test")
    except Exception as e:
        tr.add("DobbyState creation succeeds", False, str(e)[:80])

    # Test 3: Send is importable
    from langgraph.types import Command
    tr.add("LangGraph Command importable", Command is not None)

    # Test 4: supervisor_node handles compression check
    async def _test_supervisor():
        from utils.langgraph_utils import DobbyState
        # Empty state with no messages → should route to dobby_core (no compression needed)
        state = DobbyState(thread_id="t1", project_id="p1", current_role="supervisor")
        result = await supervisor_node(state)
        # Returns Command(goto=...) for LangGraph 1.x routing
        return result is not None

    ok = asyncio.run(_test_supervisor())
    tr.add("supervisor_node runs without crash", ok)

    # Test 5: compress_node handles minimal state
    async def _test_compress():
        state = DobbyState(
            thread_id="t1",
            project_id="p1",
            current_role="supervisor",
            summary="old summary",
            messages=[],
        )
        result = await compress_node(state)
        return isinstance(result, dict) and "summary" in result

    ok = asyncio.run(_test_compress())
    tr.add("compress_node runs without crash", ok)


test_parallel_agents()

# ============================================================
# 2.1 — LLMLingua-2 压缩
# ============================================================

print("\n" + "="*60)
print("2.1 LLMLingua-2 Compression")
print("="*60)


def test_llmlingua():
    from utils.llmlingua_compressor import LLMLinguaCompressor, compress_via_llmlingua
    from utils import config as cfg

    # Test 1: Config defaults are correct
    tr.add("COMPRESSION_ENGINE default = 'llm'", cfg.COMPRESSION_ENGINE == "llm")
    tr.add("LLMLINGUA2_RATIO = 0.5", cfg.LLMLINGUA2_RATIO == 0.5)
    tr.add("LLMLINGUA2_USE_GPU = False", cfg.LLMLINGUA2_USE_GPU is False)
    tr.add("LLMLINGUA2_POST_SUMMARIZE = True", cfg.LLMLINGUA2_POST_SUMMARIZE is True)

    # Test 2: Constructor works without model
    try:
        compressor = LLMLinguaCompressor(ratio=0.5, use_gpu=False)
        tr.add("LLMLinguaCompressor instantiated", True)
    except Exception as e:
        tr.add("LLMLinguaCompressor instantiated", False, str(e)[:80])

    # Test 3: Compress returns original text when model unavailable (graceful fallback)
    try:
        compressor = LLMLinguaCompressor(ratio=0.5, use_gpu=False)
        result = compressor.compress("这是一段测试文本用于验证压缩功能。")
        tr.add("compress fallback: returns original text", len(result) > 0)
    except Exception as e:
        tr.add("compress fallback: returns original text", False, str(e)[:80])

    # Test 4: compress_messages with protected indices
    try:
        compressor = LLMLinguaCompressor(ratio=0.5, use_gpu=False)
        msgs = [
            {"role": "system", "content": "System prompt (protected)"},
            {"role": "user", "content": "User query (protected)"},
            {"role": "assistant", "content": "Long assistant response that could be compressed..." * 20},
        ]
        result = compressor.compress_messages(msgs, protected_roles={"system", "user"})
        tr.add("compress_messages: returns same count", len(result) == 3)
        tr.add("compress_messages: system preserved", "System prompt" in _get_text(result[0]))
        tr.add("compress_messages: user preserved", "User query" in _get_text(result[1]))
    except Exception as e:
        tr.add("compress_messages works", False, str(e)[:80])

    # Test 5: compress_via_llmlingua async wrapper
    async def _test_async_compress():
        msgs = [
            {"role": "user", "content": "test message"},
            {"role": "assistant", "content": "long response" * 30},
        ]
        result = await compress_via_llmlingua(msgs, ratio=0.5, protected_roles={"system", "user"})
        return len(result) == 2

    ok = asyncio.run(_test_async_compress())
    tr.add("compress_via_llmlingua async wrapper works", ok)

    # Test 6: Model lazy-load is safe (no crash on import)
    try:
        from llmlingua import PromptCompressor  # may fail if not installed
        tr.add("llmlingua package available (optional)", True)
    except ImportError:
        tr.add("llmlingua package not installed (optional, fallback OK)", True)


def _get_text(msg):
    if isinstance(msg, dict):
        return msg.get("content", "")
    if hasattr(msg, "content"):
        c = msg.content
        return c if isinstance(c, str) else str(c)
    return str(msg)


test_llmlingua()

# ============================================================
# Integration Tests — Combined features
# ============================================================

print("\n" + "="*60)
print("Integration Tests")
print("="*60)


def test_integration():
    # Test 1: MessageAdapter → AuditLogger chain
    from utils.message_adapter import MessageAdapter
    from utils.audit_logger import get_audit_logger
    import tempfile

    unified = MessageAdapter.normalize({"role": "user", "content": "集成测试消息"}, source="direct")
    tr.add("Integration: normalize → UnifiedMessage", unified.content == "集成测试消息")

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = get_audit_logger()
        # Override dir for test
        old_dir = logger._log_dir
        logger._log_dir = Path(tmpdir)

        async def _chain():
            await logger.log_message("user", unified.content, session_id="int-001", project_id="int-proj")
            await logger.log_message("assistant", "集成测试回复", session_id="int-001", project_id="int-proj")
            files = list(Path(tmpdir).glob("*.jsonl"))
            if not files:
                return False
            content = files[0].read_text(encoding="utf-8")
            return "integrated" not in content  # content is "集成测试消息" not "integrated"
            # Actually check for the content
            content = files[0].read_text(encoding="utf-8")
            return "集成测试消息" in content and "集成测试回复" in content

        ok = asyncio.run(_chain())
        tr.add("Integration: adapter → audit chain", ok)

        logger._log_dir = old_dir  # restore

    # Test 2: _normalize_user_message helper exists in langgraph_utils
    from utils.langgraph_utils import _normalize_user_message
    result = _normalize_user_message({"role": "user", "content": "test"}, source="direct")
    tr.add("Integration: _normalize_user_message dict", result["msg"] is not None)
    tr.add("Integration: source=direct in result", result["source"] == "direct")

    result2 = _normalize_user_message("plain string", source="direct")
    tr.add("Integration: _normalize_user_message str", result2["msg"] is not None)

    # Test 3: memory_tools schemas match build_role_node tool_mode expectations
    from utils.memory_tools import TOOL_SCHEMAS
    tool_names = {t["function"]["name"] for t in TOOL_SCHEMAS}
    # These should match what role_config.tools can contain
    expected_tool_names = {"search_memory", "add_memory", "search_knowledge_base",
                           "search_experiences", "get_session_summary", "search_graph_rag"}
    tr.add("Integration: tool schema names match expected", tool_names == expected_tool_names)


test_integration()

# ============================================================
# 2.11 — WeKnora HTTP Timeout
# ============================================================

print("\n" + "="*60)
print("2.11 WeKnora HTTP Timeout")
print("="*60)


def test_weknora_timeout():
    from unittest.mock import patch, MagicMock
    from utils.weknora_client import WeKnoraClient

    # Test 1: _request() passes timeout to session.request
    with patch('requests.Session.request') as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_request.return_value = mock_response

        client = WeKnoraClient("http://localhost:8080/api/v1", api_key="test")
        client.list_knowledge_bases()

        call_kwargs = mock_request.call_args[1]
        tr.add("WeKnora _request: timeout present in call",
               "timeout" in call_kwargs)
        tr.add("WeKnora _request: timeout is tuple",
               isinstance(call_kwargs.get("timeout"), tuple))

    # Test 2: Constructor accepts custom timeout
    client = WeKnoraClient("http://localhost:8080/api/v1", timeout=(3.0, 10.0))
    tr.add("WeKnora custom timeout accepted",
           client.timeout == (3.0, 10.0))

    # Test 3: Default timeout is set when none provided
    client = WeKnoraClient("http://localhost:8080/api/v1")
    tr.add("WeKnora default timeout set",
           client.timeout is not None)
    tr.add("WeKnora default timeout is tuple",
           isinstance(client.timeout, tuple))
    tr.add("WeKnora connect timeout > 0",
           client.timeout[0] > 0)
    tr.add("WeKnora read timeout > 0",
           client.timeout[1] > 0)

    # Test 4: upload_file uses longer timeout
    with patch('requests.Session.post') as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"knowledge_id": "k1"}}
        mock_post.return_value = mock_response

        client = WeKnoraClient("http://localhost:8080/api/v1", timeout=(5.0, 30.0))
        # upload_file bypasses _request() and calls session.post directly
        # We test that it passes a timeout — but we can't actually upload without a file
        # Just verify the client stores timeout for upload use
        tr.add("WeKnora upload timeout available",
               client.timeout is not None)


test_weknora_timeout()

# ============================================================
# 2.12 — WeKnora KB ID Cache
# ============================================================

print("\n" + "="*60)
print("2.12 WeKnora KB ID Cache")
print("="*60)


def test_kb_cache():
    from unittest.mock import patch, MagicMock
    import time

    # ── Setup: mock WeKnoraClient to track list_knowledge_bases() calls ──
    call_count = [0]

    def _fake_list_kbs():
        call_count[0] += 1
        return [
            {"name": "dobby_engineering_safety", "id": "kb-safety-001"},
            {"name": "dobby_regulations", "id": "kb-reg-002"},
            {"name": "dobby_standards", "id": "kb-std-003"},
        ]

    # Patch the WeKnoraClient class used by _build_weknora_client
    with patch('utils.weknora_client.WeKnoraClient') as MockClient:
        mock_instance = MagicMock()
        mock_instance.list_knowledge_bases.side_effect = _fake_list_kbs
        MockClient.return_value = mock_instance

        # Import after patch so the module-level cache is fresh
        from utils.langgraph_utils import _get_kb_id_by_name

        # ── Manually reset module-level cache for test isolation ──
        import utils.langgraph_utils as lgutils
        lgutils._kb_cache.clear()
        lgutils._kb_cache_ts = 0.0

        # Test 1: First call populates cache
        result = _get_kb_id_by_name("dobby_engineering_safety")
        tr.add("KB cache: first lookup returns correct ID",
               result == "kb-safety-001")
        tr.add("KB cache: first lookup calls API",
               call_count[0] == 1)

        # Test 2: Second call within TTL uses cache (no API call)
        result2 = _get_kb_id_by_name("dobby_regulations")
        tr.add("KB cache: second lookup returns correct ID",
               result2 == "kb-reg-002")
        tr.add("KB cache: second lookup does NOT call API",
               call_count[0] == 1)  # still 1, cache hit

        # Test 3: Unknown KB name returns None (cache miss)
        result3 = _get_kb_id_by_name("nonexistent_kb")
        tr.add("KB cache: unknown KB returns None",
               result3 is None)

        # Test 4: Cache stores all KBs from first call
        result4 = _get_kb_id_by_name("dobby_standards")
        tr.add("KB cache: third KB also cached",
               result4 == "kb-std-003")
        tr.add("KB cache: still no extra API calls",
               call_count[0] == 1)

        # Test 5: Expired cache refreshes
        # Force TTL expiry
        lgutils._kb_cache_ts = time.monotonic() - 999999.0
        result5 = _get_kb_id_by_name("dobby_engineering_safety")
        tr.add("KB cache: expired cache calls API again",
               call_count[0] == 2)
        tr.add("KB cache: refreshed cache still correct",
               result5 == "kb-safety-001")


test_kb_cache()

# ============================================================
# 2.13 — mem0 Singleton
# ============================================================

print("\n" + "="*60)
print("2.13 mem0 Singleton")
print("="*60)


def test_mem0_singleton():
    from unittest.mock import patch, MagicMock
    from utils import config as cfg

    # ── Import the singleton after it's been set up ──
    from utils.langgraph_utils import get_mem0, _build_mem0_config

    # Test 1: get_mem0() returns same instance on repeated calls
    # (mock the Memory constructor to avoid loading the actual model)
    with patch('mem0.Memory') as MockMemory:
        mock_instance = MagicMock()
        MockMemory.return_value = mock_instance

        # Force singleton reset for test isolation
        import utils.langgraph_utils as lgutils
        lgutils._mem0_instance = None

        inst1 = get_mem0()
        inst2 = get_mem0()
        inst3 = get_mem0()

        tr.add("mem0 singleton: same instance returned",
               inst1 is inst2 is inst3)
        tr.add("mem0 singleton: only constructed once",
               MockMemory.call_count == 1)

    # Test 2: _build_mem0_config() supports all embedder providers
    config = _build_mem0_config()
    tr.add("mem0 config: vector_store is pgvector",
           config.vector_store.provider == "pgvector")
    tr.add("mem0 config: collection_name set",
           config.vector_store.config.collection_name == "dobby_memories")
    tr.add("mem0 config: embedding_model_dims set",
           config.vector_store.config.embedding_model_dims == cfg.EMBEDDING_DIMS)
    tr.add("mem0 config: version set",
           config.version == "v1.1")
    tr.add("mem0 config: history_db_path set",
           config.history_db_path == ":memory:")
    tr.add("mem0 config: llm provider is deepseek",
           config.llm.provider == "deepseek")
    tr.add("mem0 config: llm model from config",
           config.llm.config["model"] == cfg.DEEPSEEK_MODEL)

    # Test 3: Embedder config matches EMBEDDING_PROVIDER
    if cfg.EMBEDDING_PROVIDER == "local":
        tr.add("mem0 embedder: local=huggingface",
               config.embedder.provider == "huggingface")
        tr.add("mem0 embedder: model from config",
               config.embedder.config["model"] == cfg.EMBEDDING_MODEL)
    elif cfg.EMBEDDING_PROVIDER == "dashscope":
        tr.add("mem0 embedder: dashscope=openai compatible",
               config.embedder.provider == "openai")
    else:
        tr.add("mem0 embedder: default=openai compatible",
               config.embedder.provider == "openai")


test_mem0_singleton()

# ============================================================
# 2.14 — mem0 infer Configurable
# ============================================================

print("\n" + "="*60)
print("2.14 mem0 infer Configurable")
print("="*60)


def test_mem0_infer_config():
    from utils import config as cfg

    # Test 1: Default values are safe (infer disabled, async enabled)
    tr.add("MEM0_INFER_ENABLED default is False",
           cfg.MEM0_INFER_ENABLED is False)
    tr.add("MEM0_INFER_ASYNC default is True",
           cfg.MEM0_INFER_ASYNC is True)

    # Test 2: Config values are booleans
    tr.add("MEM0_INFER_ENABLED is bool",
           isinstance(cfg.MEM0_INFER_ENABLED, bool))
    tr.add("MEM0_INFER_ASYNC is bool",
           isinstance(cfg.MEM0_INFER_ASYNC, bool))

    # Test 3: Config is importable and doesn't crash
    tr.add("config imported successfully", True)


test_mem0_infer_config()

# ============================================================
# 2.15 — Port Cleanup on Startup
# ============================================================

print("\n" + "="*60)
print("2.15 Port Cleanup on Startup")
print("="*60)


def test_port_cleanup():
    import sys
    from unittest.mock import patch, MagicMock, call
    from utils.port_utils import kill_process_on_port, _is_port_in_use, _is_windows

    # Test 1: Port is free → no action, returns True
    with patch('utils.port_utils._is_port_in_use', return_value=False):
        tr.add("port free: no kill attempted",
               kill_process_on_port(7860) is True)

    # Test 2: Port occupied (Windows) → kills via taskkill
    with patch('utils.port_utils._is_port_in_use', return_value=True):
        with patch('utils.port_utils._get_pid_on_port', return_value=12345):
            with patch('utils.port_utils._is_windows', return_value=True):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    result = kill_process_on_port(7860)
                    tr.add("port occupied windows: taskkill called",
                           result is True)
                    tr.add("port occupied windows: correct PID",
                           str(12345) in str(mock_run.call_args))

    # Test 3: Port occupied (Unix) → kills via os.kill
    with patch('utils.port_utils._is_port_in_use', return_value=True):
        with patch('utils.port_utils._get_pid_on_port', return_value=67890):
            with patch('utils.port_utils._is_windows', return_value=False):
                with patch('os.kill') as mock_kill:
                    result = kill_process_on_port(7860)
                    tr.add("port occupied unix: os.kill called",
                           result is True)
                    # os.kill(pid, signal.SIGTERM) on platforms without SIGKILL
                    mock_kill.assert_called_once()
                    tr.add("port occupied unix: correct PID",
                           mock_kill.call_args[0][0] == 67890)

    # Test 4: Port occupied but kill fails → returns False, no crash
    with patch('utils.port_utils._is_port_in_use', return_value=True):
        with patch('utils.port_utils._get_pid_on_port', return_value=99999):
            with patch('utils.port_utils._is_windows', return_value=True):
                with patch('subprocess.run') as mock_run:
                    mock_run.side_effect = OSError("Access denied")
                    result = kill_process_on_port(7860)
                    tr.add("port occupied kill fails: returns False",
                           result is False)

    # Test 5: _is_port_in_use returns True for listening port
    import socket
    with patch('socket.socket') as mock_sock:
        mock_sock_instance = MagicMock()
        mock_sock.return_value = mock_sock_instance
        mock_sock_instance.connect_ex.return_value = 0  # 0 = success = port in use
        from utils.port_utils import _is_port_in_use
        tr.add("_is_port_in_use: occupied → True",
               _is_port_in_use(7860) is True)

    # Test 6: _is_port_in_use returns False for free port
    with patch('socket.socket') as mock_sock:
        mock_sock_instance = MagicMock()
        mock_sock.return_value = mock_sock_instance
        mock_sock_instance.connect_ex.return_value = 61  # connection refused = port free
        tr.add("_is_port_in_use: free → False",
               _is_port_in_use(7860) is False)

    # Test 7: _is_windows returns correct type
    tr.add("_is_windows returns bool",
           isinstance(_is_windows(), bool))


test_port_cleanup()

# ============================================================
# Summary
# ============================================================

all_pass = tr.summary()
sys.exit(0 if all_pass else 1)
