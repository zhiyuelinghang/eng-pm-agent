# -*- coding: utf-8 -*-
"""Shared delivery primitive for messages between team sessions."""

from ._bus_ops import deliver_to_inbox
from .message_bus import MessageBus
from ..message import HintBlock


async def deliver_team_message(
    message_bus: MessageBus,
    *,
    user_id: str,
    recipient_session_id: str,
    recipient_agent_id: str,
    sender_name: str,
    content: str,
) -> None:
    """Push one team message to a session and schedule its next run.

    Both the explicit :class:`TeamSay` tool and the worker completion
    fallback use this function. Keeping the envelope and wake-up behavior in
    one place prevents the two delivery paths from drifting apart.
    """
    hint = HintBlock(
        hint=(
            f'<team-message from="{sender_name}">\n'
            f"{content}\n"
            f"</team-message>"
        ),
        source=sender_name,
    )
    await deliver_to_inbox(
        message_bus,
        user_id=user_id,
        session_id=recipient_session_id,
        agent_id=recipient_agent_id,
        payload=hint.model_dump(mode="json"),
    )
