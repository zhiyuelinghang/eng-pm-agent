"""Tests for three-mode context assembly."""
import pytest
from unittest.mock import AsyncMock, patch
from utils.memory_manager import MemoryManager, ContextAssembly


class TestContextAssemblyModes:
    """Note: These tests verify the mode parameter flow.
    Full integration tests require Mem0/WeKnora servers."""

    def test_context_assembly_has_mode_used_field(self):
        """ContextAssembly dataclass contains mode_used field"""
        ca = ContextAssembly()
        assert hasattr(ca, "mode_used")
        assert ca.mode_used == "standard"

    @pytest.mark.asyncio
    async def test_mode_minimal_skips_retrieval(self):
        """mode='minimal' does not trigger retrieval"""
        mm = MemoryManager(project_id="test", role_id="dobby_core")

        # Mock internal search methods to track calls
        mm._search_memory = AsyncMock()
        mm._search_knowledge = AsyncMock()

        state = {
            "project_id": "test",
            "current_role": "dobby_core",
            "summary": "",
            "tasks": {},
            "messages": [],
            "thread_id": "test-session",
        }

        with patch('utils.memory_manager._make_system', return_value={"role":"system","content":"test"}):
            with patch('utils.memory_manager._make_user', return_value={"role":"user","content":"hello"}):
                result = await mm.assemble_context(state, "hello", mode="minimal")

        # verify search was NOT called
        mm._search_memory.assert_not_called()
        mm._search_knowledge.assert_not_called()

    @pytest.mark.asyncio
    async def test_mode_standard_triggers_retrieval(self):
        """mode='standard' triggers retrieval (current behavior)"""
        mm = MemoryManager(project_id="test", role_id="dobby_core")

        mm._search_memory = AsyncMock(return_value=[])
        mm._search_knowledge = AsyncMock(return_value=[])

        state = {
            "project_id": "test",
            "current_role": "dobby_core",
            "summary": "",
            "tasks": {},
            "messages": [],
            "thread_id": "test-session",
        }

        with patch('utils.memory_manager._make_system', return_value={"role":"system","content":"test"}):
            with patch('utils.memory_manager._make_user', return_value={"role":"user","content":"query"}):
                with patch('utils.memory_manager._search_experiences_structured', AsyncMock(return_value=[])):
                    with patch('utils.graphiti_client.graphiti_search', AsyncMock(return_value={})):
                        with patch('utils.memory_manager._graphiti_to_items', return_value=[]):
                            result = await mm.assemble_context(state, "project progress", mode="standard")

        # verify search WAS called
        mm._search_memory.assert_called_once()
        mm._search_knowledge.assert_called_once()

    @pytest.mark.asyncio
    async def test_mode_full_includes_experience(self):
        """mode='full' includes 4-source retrieval with experience"""
        mm = MemoryManager(project_id="test", role_id="dobby_core")

        mm._search_memory = AsyncMock(return_value=[])
        mm._search_knowledge = AsyncMock(return_value=[])

        state = {
            "project_id": "test",
            "current_role": "dobby_core",
            "summary": "",
            "tasks": {},
            "messages": [],
            "thread_id": "test-session",
        }

        with patch('utils.memory_manager._make_system', return_value={"role":"system","content":"test"}):
            with patch('utils.memory_manager._make_user', return_value={"role":"user","content":"query"}):
                with patch('utils.memory_manager._search_experiences_structured', AsyncMock(return_value=[])) as mock_exp:
                    with patch('utils.graphiti_client.graphiti_search', AsyncMock(return_value={})):
                        with patch('utils.memory_manager._graphiti_to_items', return_value=[]):
                            result = await mm.assemble_context(state, "safety standard GB", mode="full")

        # verify experience search WAS called in full mode
        mock_exp.assert_called_once()

    def test_mode_auto_default(self):
        """assemble_context default mode is 'auto'"""
        import inspect
        sig = inspect.signature(MemoryManager.assemble_context)
        assert sig.parameters["mode"].default == "auto"

    @pytest.mark.asyncio
    async def test_result_includes_mode_used(self):
        """ContextAssembly result includes mode_used field"""
        mm = MemoryManager(project_id="test", role_id="dobby_core")

        mm._search_memory = AsyncMock(return_value=[])
        mm._search_knowledge = AsyncMock(return_value=[])

        state = {
            "project_id": "test",
            "current_role": "dobby_core",
            "summary": "",
            "tasks": {},
            "messages": [],
            "thread_id": "test-session",
        }

        with patch('utils.memory_manager._make_system', return_value={"role":"system","content":"test"}):
            with patch('utils.memory_manager._make_user', return_value={"role":"user","content":"hello"}):
                result = await mm.assemble_context(state, "hello", mode="minimal")

        assert result.mode_used == "minimal"
