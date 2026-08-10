"""
JSONL Audit Logger — memento pattern (§3.4).

Writes every message, compression event, and session boundary to
a human-readable JSONL file for offline analysis and debugging.

Independent of PostgresSaver — survives database failures.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config as _cfg

# ── Default log directory ──
DEFAULT_LOG_DIR = Path(__file__).parent.parent / "data" / "audit"

# ── Max file size before rotation (100 MB) ──
MAX_LOG_BYTES = 100 * 1024 * 1024


class AuditLogger:
    """Stateless JSONL audit logger — append-only, async, gracefully degrading."""

    def __init__(self, log_dir: str | Path | None = None):
        self._log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    # ── Public API ──────────────────────────────────────────

    async def log_entry(
        self,
        event: str,
        role: str,
        content: str,
        session_id: str = "",
        project_id: str = "",
        **meta,
    ) -> None:
        """Append a single audit entry.

        Args:
            event: "message" | "compress" | "tool_call" | "session_start" | "session_end"
            role: "user" | "assistant" | "system" | agent name
            content: message text or event description
            session_id: current session identifier
            project_id: project identifier
            **meta: additional metadata (token_estimate, round, error, etc.)
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "role": role,
            "content": content[:10_000],  # Truncate extremely long content
        }
        if session_id:
            entry["session_id"] = session_id
        if project_id:
            entry["project_id"] = project_id
        if meta:
            entry["metadata"] = meta

        try:
            await self._write_line(entry, session_id, project_id)
        except Exception:
            import warnings
            warnings.warn(f"[AuditLogger] Failed to write entry: {event}", RuntimeWarning)

    async def log_session_start(self, session_id: str, project_id: str, **meta) -> None:
        """Log session start event."""
        await self.log_entry(
            "session_start",
            "system",
            f"Session started: {session_id}",
            session_id=session_id,
            project_id=project_id,
            **meta,
        )

    async def log_session_end(
        self, session_id: str, project_id: str, stats: Optional[dict] = None, **meta
    ) -> None:
        """Log session end event with optional statistics."""
        await self.log_entry(
            "session_end",
            "system",
            f"Session ended: {session_id}",
            session_id=session_id,
            project_id=project_id,
            **(stats or {}),
            **meta,
        )

    async def log_message(
        self,
        role: str,
        content: str,
        session_id: str = "",
        project_id: str = "",
        **meta,
    ) -> None:
        """Shorthand for logging a message event."""
        await self.log_entry("message", role, content, session_id, project_id, **meta)

    async def log_tool_call(
        self,
        tool_name: str,
        arguments: dict,
        result_summary: str = "",
        session_id: str = "",
        project_id: str = "",
        **meta,
    ) -> None:
        """Log a tool call event."""
        await self.log_entry(
            "tool_call",
            "assistant",
            f"Tool: {tool_name}({json.dumps(arguments, ensure_ascii=False)}) → {result_summary[:500]}",
            session_id=session_id,
            project_id=project_id,
            tool=tool_name,
            **meta,
        )

    async def log_compress(
        self,
        before_tokens: int,
        after_tokens: int,
        summary_preview: str = "",
        session_id: str = "",
        project_id: str = "",
        **meta,
    ) -> None:
        """Log a compression event."""
        await self.log_entry(
            "compress",
            "system",
            f"Compressed: {before_tokens} → {after_tokens} tokens. Summary: {summary_preview[:200]}",
            session_id=session_id,
            project_id=project_id,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            **meta,
        )

    # ── Internal ────────────────────────────────────────────

    def _file_path(self, session_id: str = "", project_id: str = "") -> Path:
        """Determine log file path. Rotates if file exceeds MAX_LOG_BYTES."""
        pid = project_id or "unknown"
        sid = session_id or "default"
        stem = f"{pid}_{sid}_audit"

        base = self._log_dir / f"{stem}.jsonl"
        if not base.exists():
            return base
        if base.stat().st_size < MAX_LOG_BYTES:
            return base

        # Rotate: find next available _NNN suffix
        for idx in range(1, 10_000):
            rotated = self._log_dir / f"{stem}_{idx:03d}.jsonl"
            if not rotated.exists() or rotated.stat().st_size < MAX_LOG_BYTES:
                return rotated

        # Fallback: use timestamp suffix
        ts = int(time.time())
        return self._log_dir / f"{stem}_{ts}.jsonl"

    async def _write_line(
        self, entry: dict, session_id: str = "", project_id: str = ""
    ) -> None:
        """Write a single JSON line with file lock."""
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        filepath = self._file_path(session_id, project_id)

        async with self._lock:
            # Use low-level os.open for append safety
            fd = os.open(str(filepath), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)


# ── Module-level singleton ──────────────────────────────────

_audit_logger: Optional[AuditLogger] = None


def get_audit_logger(log_dir: str | Path | None = None) -> AuditLogger:
    """Get or create the module-level AuditLogger singleton."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger(log_dir)
    return _audit_logger
