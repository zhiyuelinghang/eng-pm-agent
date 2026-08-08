from __future__ import annotations

import logging
from typing import Any, Callable

from ..engine.errors import DomainError
from .context import service
from ..schemas.envelope import error, needs_input, ok
from ..schemas.errors import ErrorCode, error_from_exception
from ..session.state_machine import public_state_name


LOGGER = logging.getLogger(__name__)

NEXT_TOOL_MAP = {
    "create_session": "predict_create_session",
    "profile_data": "predict_profile_data",
    "confirm_variables": "predict_confirm_variables",
    "propose_pipeline_plan": "predict_propose_pipeline_plan",
    "confirm_pipeline_plan": "predict_confirm_pipeline_plan",
    "evaluate_models": "predict_evaluate_models",
    "export_model": "predict_export_model",
    "get_job_status": "predict_get_job_status",
}

CONTROL_KEYS = {
    "session_id",
    "stage",
    "state",
    "message",
    "next_tool",
    "intervention_required",
    "choices",
    "available_options",
}


def normalized_state(result: dict[str, Any] | None, session_id: str | None) -> str | None:
    if result:
        if result.get("state"):
            return str(result["state"]).upper()
        if result.get("stage"):
            return public_state_name(str(result["stage"]))
    if session_id:
        try:
            return public_state_name(service.store.load(session_id).get("stage"))
        except Exception:
            return None
    return None


def legacy_data(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in CONTROL_KEYS}


def mapped_next_tool(value: str | None) -> str | None:
    return NEXT_TOOL_MAP.get(value or "", value)


def failure(session_id: str | None, exc: Exception) -> dict[str, Any]:
    details = error_from_exception(exc)
    state = normalized_state(None, session_id)
    if details["recoverable"]:
        return needs_input(
            session_id=session_id,
            state=state,
            data={},
            options={
                "correction": {
                    "type": "free_text",
                    "candidates": [
                        {
                            "value": "correct_and_retry",
                            "label": "修正后重试",
                            "reason": details["suggestion"],
                        }
                    ],
                }
            },
            needs_user_decision=["correction"],
            message=details["message"],
            error=details,
        )
    return error(
        session_id=session_id,
        state=state,
        message="服务器无法完成请求",
        error=details,
    )


def call_sync(
    session_id: str | None,
    function: Callable[[], dict[str, Any]],
    *,
    message: str | None = None,
) -> dict[str, Any]:
    try:
        result = function()
        return ok(
            session_id=result.get("session_id", session_id),
            state=normalized_state(result, result.get("session_id", session_id)),
            data=legacy_data(result),
            next_tool=mapped_next_tool(result.get("next_tool")),
            message=message or str(result.get("message", "操作完成")),
        )
    except DomainError as exc:
        return failure(session_id, exc)
    except Exception as exc:  # never expose raw engine failures
        LOGGER.exception("Unhandled MCP tool failure")
        internal = DomainError(
            "服务器内部故障",
            code=ErrorCode.INTERNAL_ERROR.value,
            recoverable=False,
            suggestion="稍后重试；若持续失败请联系管理员并提供 session_id",
        )
        return failure(session_id, internal)
