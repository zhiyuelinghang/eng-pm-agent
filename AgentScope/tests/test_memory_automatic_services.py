"""Automatic index startup and invocation-local compression behavior."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agentscope.app.memory._middleware import DobbyMemoryMiddleware
from agentscope.message import AssistantMsg, UserMsg
from utils import memory_service


def test_existing_indexes_initialize_without_pending_writes(monkeypatch):
    repository = SimpleNamespace(claim_index_job=Mock(return_value=None))
    embed = Mock(return_value=[0.1])
    monkeypatch.setattr(memory_service, '_embedder', None)
    monkeypatch.setattr(memory_service, 'get_memory_repository', lambda: repository)
    monkeypatch.setattr(memory_service, 'embed_memory', embed)
    async def stop(_):
        raise asyncio.CancelledError
    monkeypatch.setattr(memory_service.asyncio, 'sleep', stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(memory_service.run_memory_index_worker())
    embed.assert_called_once_with('记忆检索就绪')


def test_unavailable_embeddings_leave_text_retrieval_ready(monkeypatch):
    monkeypatch.setattr(memory_service, '_embedder', None)
    embed = Mock(side_effect=RuntimeError('offline'))
    monkeypatch.setattr(memory_service, 'embed_memory', embed)
    assert asyncio.run(memory_service.search_vector_if_ready('周报格式')) is None
    embed.assert_not_called()


def test_parallel_compressions_keep_their_own_models():
    async def run():
        started = asyncio.Event()
        model_b = AsyncMock(return_value=AssistantMsg('assistant', '乙对话摘要'))
        async def model_a(_):
            await started.wait()
            return AssistantMsg('assistant', '甲专用摘要')
        first = asyncio.create_task(DobbyMemoryMiddleware._call_agent_model(
            SimpleNamespace(model=model_b), [UserMsg('user', '甲')], model_override=model_a))
        second = await DobbyMemoryMiddleware._call_agent_model(
            SimpleNamespace(model=model_b), [UserMsg('user', '乙')])
        started.set()
        assert (await first).get_text_content() == '甲专用摘要'
        assert second.get_text_content() == '乙对话摘要'
        model_b.assert_awaited_once()
    asyncio.run(run())
