# -*- coding: utf-8 -*-
"""Regression tests for workspace-aware and concurrent file caching."""
import asyncio
import os
from unittest.async_case import IsolatedAsyncioTestCase
from unittest.mock import patch

from agentscope.state import AgentState, ToolContext
from agentscope.state._state import ReadCacheEntry
from agentscope.tool import Edit, Read, Write
from agentscope.tool._builtin._backend import BackendBase, ExecResult


class _MemoryBackend(BackendBase):
    """A backend whose files exist only inside the workspace."""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self._mtimes: dict[str, float] = {}

    async def exec_shell(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        del command, cwd, timeout
        return ExecResult(exit_code=0, stdout=b"", stderr=b"")

    async def read_file(self, path: str) -> bytes:
        return self._files[path]

    async def write_file(self, path: str, data: bytes) -> None:
        self._files[path] = data
        self._mtimes[path] = self._mtimes.get(path, 1000.0) + 0.001

    async def stat_mtime(self, path: str) -> float | None:
        return self._mtimes.get(path)

    async def file_exists(self, path: str) -> bool:
        return path in self._files

    async def is_dir(self, path: str) -> bool:
        del path
        return False

    def isabs(self, path: str) -> bool:
        return path.startswith("/")

    def dirname(self, path: str) -> str:
        return os.path.dirname(path) or "/"


class BackendAwareCacheTest(IsolatedAsyncioTestCase):
    """Read/Edit/Write must share cache metadata from the same backend."""

    async def asyncSetUp(self) -> None:
        self.backend = _MemoryBackend()
        self.read_tool = Read(backend=self.backend)
        self.write_tool = Write(backend=self.backend)
        self.edit_tool = Edit(backend=self.backend)
        self.state = AgentState()
        self.path = "/workspace/test.txt"
        await self.backend.write_file(self.path, b"alpha\n")

    async def test_read_then_edit_backend_only_path(self) -> None:
        await self.read_tool(file_path=self.path, _agent_state=self.state)

        chunk = await self.edit_tool(
            file_path=self.path,
            old_string="alpha",
            new_string="beta",
            _agent_state=self.state,
        )

        self.assertEqual(chunk.state, "running")
        self.assertEqual(await self.backend.read_file(self.path), b"beta\n")

    async def test_read_then_write_backend_only_path(self) -> None:
        await self.read_tool(file_path=self.path, _agent_state=self.state)

        chunk = await self.write_tool(
            file_path=self.path,
            content="gamma\n",
            _agent_state=self.state,
        )

        self.assertEqual(chunk.state, "running")
        self.assertEqual(await self.backend.read_file(self.path), b"gamma\n")

    async def test_backend_change_invalidates_cache(self) -> None:
        await self.read_tool(file_path=self.path, _agent_state=self.state)
        await self.backend.write_file(self.path, b"changed\n")

        chunk = await self.edit_tool(
            file_path=self.path,
            old_string="alpha",
            new_string="beta",
            _agent_state=self.state,
        )

        self.assertEqual(chunk.state, "error")
        self.assertIn("must first read", chunk.content[0].text)
        self.assertListEqual(self.state.tool_context.read_file_cache, [])


class ConcurrentCacheTest(IsolatedAsyncioTestCase):
    """Concurrent cache hits must preserve one stable LRU entry."""

    async def test_concurrent_hits_preserve_lru_entries(self) -> None:
        context = ToolContext(
            read_file_cache=[
                ReadCacheEntry(
                    lines=["a"],
                    updated_at=1.0,
                    bytes=1.0,
                    file_path="a",
                ),
                ReadCacheEntry(
                    lines=["b"],
                    updated_at=1.0,
                    bytes=1.0,
                    file_path="b",
                ),
            ],
        )
        both_started = asyncio.Event()
        calls = 0

        async def synchronized_getmtime(_: str) -> float:
            nonlocal calls
            calls += 1
            if calls == 2:
                both_started.set()
            await both_started.wait()
            return 1.0

        with patch(
            "agentscope.state._state.aiofiles.os.path.getmtime",
            side_effect=synchronized_getmtime,
        ):
            results = await asyncio.gather(
                context.get_cache("a"),
                context.get_cache("a"),
            )

        self.assertTrue(all(result is not None for result in results))
        self.assertListEqual(
            [entry.file_path for entry in context.read_file_cache],
            ["b", "a"],
        )
