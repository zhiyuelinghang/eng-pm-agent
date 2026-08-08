from __future__ import annotations

from typing import Any


ENVELOPE_KEYS = (
    "status",
    "session_id",
    "state",
    "data",
    "options",
    "needs_user_decision",
    "next_tool",
    "message",
    "error",
)


def _envelope(
    status: str,
    *,
    session_id: str | None = None,
    state: str | None = None,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    needs_user_decision: list[str] | None = None,
    next_tool: str | None = None,
    message: str = "",
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "session_id": session_id,
        "state": state,
        "data": data or {},
        "options": options or {},
        "needs_user_decision": needs_user_decision or [],
        "next_tool": next_tool,
        "message": message,
        "error": error,
    }


def ok(**kwargs: Any) -> dict[str, Any]:
    return _envelope("ok", **kwargs)


def needs_input(**kwargs: Any) -> dict[str, Any]:
    return _envelope("needs_input", **kwargs)


def running(**kwargs: Any) -> dict[str, Any]:
    return _envelope("running", **kwargs)


def error(**kwargs: Any) -> dict[str, Any]:
    return _envelope("error", **kwargs)
