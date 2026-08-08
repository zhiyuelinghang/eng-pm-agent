from __future__ import annotations


class DomainError(ValueError):
    """Expected domain failure that public tools must convert to an envelope."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        recoverable: bool = True,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.suggestion = suggestion
