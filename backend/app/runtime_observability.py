"""Shared stage timing primitives for platform-to-agent runs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class RuntimeStage:
    """One user-visible phase measured with a monotonic clock."""

    stage_id: str
    label: str
    started_at: str
    started_monotonic: float
    status: str = "running"
    finished_at: str | None = None
    duration_ms: int | None = None

    def public(self) -> dict[str, object]:
        return {
            "stage_id": self.stage_id,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }


class RuntimeStageTracker:
    """Collect ordered, updateable timing stages for one run."""

    def __init__(self) -> None:
        self._stages: list[RuntimeStage] = []

    def start(self, stage_id: str, label: str) -> RuntimeStage:
        stage = RuntimeStage(
            stage_id=stage_id,
            label=label,
            started_at=datetime.now(UTC).isoformat(),
            started_monotonic=time.perf_counter(),
        )
        self._stages.append(stage)
        return stage

    @staticmethod
    def finish(
        stage: RuntimeStage,
        *,
        status: str = "completed",
    ) -> dict[str, object]:
        if stage.finished_at is None:
            stage.finished_at = datetime.now(UTC).isoformat()
            stage.duration_ms = max(
                0,
                round((time.perf_counter() - stage.started_monotonic) * 1000),
            )
        stage.status = status
        return stage.public()

    def snapshot(self) -> list[dict[str, object]]:
        return [stage.public() for stage in self._stages]


def runtime_stage_event(stage: RuntimeStage) -> dict[str, object]:
    """Project a stage into the AgentScope-compatible CUSTOM event shape."""

    return {
        "type": "CUSTOM",
        "name": "runtime_stage_updated",
        "created_at": datetime.now(UTC).isoformat(),
        "value": stage.public(),
    }
