# -*- coding: utf-8 -*-
"""Regression test for AgentScope v2.0.7 index-worker cancellation."""
import asyncio
from datetime import timedelta
from typing import Any
from unittest import IsolatedAsyncioTestCase

from agentscope.app._service._index_worker import IndexWorker


class _LeaseStorage:
    """Minimal storage double for worker lifecycle assertions."""

    def __init__(self) -> None:
        self.released: list[dict[str, Any]] = []
        self.status_updates: list[dict[str, Any]] = []

    async def acquire_knowledge_document_lease(self, **kwargs: Any) -> bool:
        """Always acquire the test lease."""
        del kwargs
        return True

    async def renew_knowledge_document_lease(self, **kwargs: Any) -> bool:
        """Keep the lease alive until the caller cancels the worker."""
        del kwargs
        return True

    async def release_knowledge_document_lease(self, **kwargs: Any) -> None:
        """Record lease release."""
        self.released.append(kwargs)

    async def update_knowledge_document_status(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
        status: str,
        error: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        """Record status updates."""
        del user_id, knowledge_base_id, document_id
        self.status_updates.append(
            {"status": status, "error": error, "chunk_count": chunk_count},
        )


class _SlowWorker(IndexWorker):
    """Worker whose child tasks stay alive until cancellation."""

    def __init__(self, storage: _LeaseStorage) -> None:
        self._storage = storage  # type: ignore[assignment]
        self._node_id = "test-node"
        self._lease_ttl = timedelta(seconds=10)
        self._renew_interval = timedelta(seconds=0.05)
        self._sem = asyncio.Semaphore(1)
        self.pipeline_started = asyncio.Event()
        self.heartbeat_started = asyncio.Event()
        self.pipeline_cancelled = False
        self.heartbeat_stopped = False

    async def _run_pipeline(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """Wait until cancelled by ``process`` cleanup."""
        del user_id, knowledge_base_id, document_id
        self.pipeline_started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.pipeline_cancelled = True
            raise

    async def _heartbeat(
        self,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """Record heartbeat cleanup while retaining production behavior."""
        self.heartbeat_started.set()
        try:
            await super()._heartbeat(user_id, knowledge_base_id, document_id)
        finally:
            self.heartbeat_stopped = True


class IndexWorkerCancellationV207Test(IsolatedAsyncioTestCase):
    """Caller cancellation tears down both worker child tasks."""

    async def test_external_cancel_stops_children_and_releases_lease(
        self,
    ) -> None:
        """No pipeline or heartbeat may outlive a cancelled process call."""
        storage = _LeaseStorage()
        worker = _SlowWorker(storage)
        process_task = asyncio.create_task(worker.process("u", "kb", "doc"))
        await asyncio.wait_for(
            asyncio.gather(
                worker.pipeline_started.wait(),
                worker.heartbeat_started.wait(),
            ),
            timeout=1,
        )

        process_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(process_task, timeout=1)

        self.assertTrue(worker.pipeline_cancelled)
        self.assertTrue(worker.heartbeat_stopped)
        self.assertEqual(storage.status_updates, [])
        self.assertEqual(len(storage.released), 1)
