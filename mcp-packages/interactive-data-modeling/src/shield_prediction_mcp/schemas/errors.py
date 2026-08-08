from __future__ import annotations

from enum import Enum
import re
from typing import Any


class ErrorCode(str, Enum):
    UNKNOWN_SESSION = "UNKNOWN_SESSION"
    WRONG_STATE = "WRONG_STATE"
    INVALID_INPUT = "INVALID_INPUT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    JOB_FAILED = "JOB_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


_ABSOLUTE_PATH_AND_MESSAGE_SUFFIX = re.compile(
    r"(?i)(?:['\"]?(?:"
    r"(?<![\w])file:(?=/)|"
    r"(?<![\w])[A-Za-z]:[\\/]|"
    r"(?<![\\])\\\\|"
    r"(?<![:/])//|"
    r"(?<![\w:/])/(?!/)"
    r"))[\s\S]*"
)


def _without_internal_paths(message: str) -> str:
    """Redact an absolute path and the rest of the message.

    An unquoted filesystem path has no unambiguous punctuation boundary:
    Windows accepts brackets and several punctuation characters, while POSIX
    accepts almost every character except slash and NUL. Security therefore
    even permits newlines. Security therefore takes precedence over preserving
    any text that follows a detected path.
    """

    return _ABSOLUTE_PATH_AND_MESSAGE_SUFFIX.sub("<server-path>", message)


def sanitize_error_details(details: dict[str, Any]) -> dict[str, Any]:
    """Allowlist and redact a persisted/public error dictionary."""

    return {
        "code": str(details.get("code") or ErrorCode.INTERNAL_ERROR.value),
        "message": _without_internal_paths(str(details.get("message") or "请求处理失败")),
        "recoverable": bool(details.get("recoverable", False)),
        "suggestion": _without_internal_paths(
            str(details.get("suggestion") or "稍后重试；若持续失败请联系管理员")
        ),
    }


def error_from_exception(exc: Exception) -> dict[str, Any]:
    message = _without_internal_paths(str(exc) or "请求处理失败")
    lowered = message.lower()
    code = getattr(exc, "code", None)
    recoverable = bool(getattr(exc, "recoverable", True))
    suggestion = getattr(exc, "suggestion", None)
    if not code:
        if "会话不存在" in message or "session" in lowered and "不存在" in message:
            code = ErrorCode.UNKNOWN_SESSION.value
            suggestion = suggestion or "重新调用 predict_create_session 创建会话"
        elif "当前阶段" in message or "仅允许" in message or "先调用" in message:
            code = ErrorCode.WRONG_STATE.value
        elif "依赖" in message or "需要安装" in message:
            code = ErrorCode.DEPENDENCY_UNAVAILABLE.value
            recoverable = False
        elif "上限" in message or "过大" in message or "超出" in message:
            code = ErrorCode.RESOURCE_LIMIT.value
        elif any(
            marker in message
            for marker in (
                "泄漏",
                "时序任务禁止",
                "目标变量缺失",
                "原始数据在",
                "从未见过的目标类别",
                "类型不符",
            )
        ):
            code = ErrorCode.VALIDATION_FAILED.value
        else:
            # Syntax, enum, range and ordinary parameter errors are input
            # errors. VALIDATION_FAILED is reserved for domain/data rules.
            code = ErrorCode.INVALID_INPUT.value
    return sanitize_error_details({
        "code": str(code),
        "message": message,
        "recoverable": recoverable,
        "suggestion": suggestion or "根据 message 修正输入后重试",
    })
