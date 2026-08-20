# -*- coding: utf-8 -*-
"""Regression tests for reliable session-inbox handoff."""

import asyncio
from contextlib import AsyncExitStack
from unittest import IsolatedAsyncioTestCase

from agentscope.app._bus_ops import (
    abandon_inbox_consumer,
    deliver_to_inbox,
    has_pending_inbox_or_release,
    register_inbox_consumer,
)
from agentscope.app.message_bus import InMemoryMessageBus, MessageBusKeys


class SessionInboxHandoffTest(IsolatedAsyncioTestCase):
    """A payload must be consumed by the live run or a follow-up run."""

    async def asyncSetUp(self) -> None:
        self._stack = AsyncExitStack()
        self.bus = await self._stack.enter_async_context(InMemoryMessageBus())
        self.session_id = "session-1"

    async def asyncTearDown(self) -> None:
        await self._stack.aclose()

    async def _deliver(self, text: str) -> None:
        await deliver_to_inbox(
            self.bus,
            user_id="user",
            session_id=self.session_id,
            agent_id="agent",
            payload={"type": "hint", "hint": text},
        )

    async def _wakeups(self) -> list[dict]:
        entries = await self.bus.queue_drain(MessageBusKeys.wakeup_queue())
        return [payload for _entry_id, payload in entries]

    async def test_delivery_without_consumer_wakes_session(self) -> None:
        await self._deliver("hello")

        self.assertEqual(len(await self._wakeups()), 1)

    async def test_registered_consumer_suppresses_redundant_wakeup(
        self,
    ) -> None:
        await register_inbox_consumer(self.bus, self.session_id)
        await self._deliver("hello")

        self.assertEqual(await self._wakeups(), [])

    async def test_delivery_during_release_is_never_stranded(self) -> None:
        await register_inbox_consumer(self.bus, self.session_id)

        release = asyncio.create_task(
            has_pending_inbox_or_release(self.bus, self.session_id),
        )
        delivery = asyncio.create_task(self._deliver("racing"))
        pending, _ = await asyncio.gather(release, delivery)

        wakeups = await self._wakeups()
        self.assertEqual(pending, not wakeups)
        entries = await self.bus.queue_drain(
            MessageBusKeys.inbox(self.session_id),
        )
        self.assertEqual(
            [payload["hint"] for _entry_id, payload in entries],
            ["racing"],
        )

    async def test_abnormal_exit_wakes_for_pending_payload(self) -> None:
        await register_inbox_consumer(self.bus, self.session_id)
        await self._deliver("pending")

        await abandon_inbox_consumer(
            self.bus,
            user_id="user",
            session_id=self.session_id,
            agent_id="agent",
        )

        self.assertEqual(len(await self._wakeups()), 1)
        self.assertFalse(
            await self.bus.registry_exists(
                MessageBusKeys.inbox_consumer(self.session_id),
                MessageBusKeys.INBOX_CONSUMER_FIELD,
            ),
        )
