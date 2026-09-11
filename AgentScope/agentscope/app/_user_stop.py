"""Keep late team/background events from undoing a user's explicit stop."""
from datetime import UTC, datetime
from ..message import Msg


async def team_root_was_stopped(storage, user_id: str, session) -> bool:
    context = getattr(session.config, "platform_context", None)
    root_id = getattr(context, "root_session_id", None)
    if not root_id or root_id == session.id:
        return False
    root = await storage.get_session(user_id, "", root_id)
    return root is None or getattr(root.config, "user_stopped_at", None) is not None


def input_resumes_stopped_session(input_msg, stopped_at: datetime | None) -> bool:
    if stopped_at is None:
        return True
    messages = input_msg if isinstance(input_msg, list) else [input_msg]
    for message in messages:
        if not isinstance(message, Msg) or message.role != "user":
            continue
        try:
            created_at = datetime.fromisoformat(message.created_at).astimezone(UTC)
        except (ValueError, TypeError):
            continue
        if created_at > stopped_at.astimezone(UTC):
            return True
    return False
