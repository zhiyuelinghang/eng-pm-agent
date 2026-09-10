"""Checkpoint completed rounds while a long run remains active."""
from time import monotonic


class RunCheckpoint:
    def __init__(self, storage, user_id, agent_id, session_id, interval=30.0, *, message_bus=None):
        self.storage = storage
        self.message_bus = message_bus
        self.user_id, self.agent_id, self.session_id = user_id, agent_id, session_id
        self.interval = interval
        self.last_saved = monotonic()

    async def save(self, agent, reply_msg):
        now = monotonic()
        if reply_msg is None or agent.state.cur_iter == 0 or now - self.last_saved < self.interval:
            return
        # Called at the start of the NEXT model round: all preceding tool
        # results have already been incorporated into the agent state.
        guard = getattr(agent, "_execution_guard", None)
        if guard:
            guard.checkpoint()
        if self.message_bus is None:
            await self.storage.upsert_message(self.user_id, self.session_id, reply_msg)
        else:
            from ._collaboration_archive import save_message_with_collaboration_progress
            await save_message_with_collaboration_progress(self.storage, self.message_bus, self.user_id, self.session_id, reply_msg)
        await self.storage.update_session_state(
            user_id=self.user_id, agent_id=self.agent_id,
            session_id=self.session_id, state=agent.state,
        )
        self.last_saved = now
