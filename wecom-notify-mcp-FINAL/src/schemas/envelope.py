from typing import Optional, Any
from dataclasses import dataclass, field, asdict

@dataclass
class ErrorInfo:
    code: str
    message: str
    recoverable: bool = True
    suggestion: Optional[str] = None

@dataclass
class ToolResult:
    status: str  # ok | needs_input | running | error
    session_id: str
    state: str
    data: Optional[Any] = None
    options: Optional[dict] = None
    needs_user_decision: list = field(default_factory=list)
    next_tool: Optional[str] = None
    message: str = ""
    error: Optional[ErrorInfo] = None

    def to_dict(self):
        d = asdict(self)
        if self.error and isinstance(self.error, ErrorInfo):
            d["error"] = asdict(self.error)
        return d

def ok(session_id: str, state: str, data=None, message="", next_tool=None):
    return ToolResult(status="ok", session_id=session_id, state=state,
                      data=data, message=message, next_tool=next_tool)

def err(session_id: str, state: str, code: str, message: str, recoverable=True, suggestion=None):
    return ToolResult(status="error", session_id=session_id, state=state,
                      error=ErrorInfo(code=code, message=message, recoverable=recoverable, suggestion=suggestion))

def needs_input(session_id: str, state: str, message: str, options: dict, needs: list):
    return ToolResult(status="needs_input", session_id=session_id, state=state,
                      message=message, options=options, needs_user_decision=needs)
