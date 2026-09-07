"""Tests for the platform-visible runtime stage timeline."""

from unittest.mock import patch

from backend.app.runtime_observability import (
    RuntimeStageTracker,
    runtime_stage_event,
)


def test_runtime_stages_keep_order_and_monotonic_duration() -> None:
    tracker = RuntimeStageTracker()
    with patch(
        "backend.app.runtime_observability.time.perf_counter",
        side_effect=[10.0, 10.125, 11.0, 11.75],
    ):
        authorization = tracker.start("authorization", "平台鉴权")
        tracker.finish(authorization)
        execution = tracker.start("execution", "智能体执行")
        tracker.finish(execution, status="awaiting_permission")

    stages = tracker.snapshot()
    assert [stage["stage_id"] for stage in stages] == [
        "authorization",
        "execution",
    ]
    assert stages[0]["duration_ms"] == 125
    assert stages[1]["duration_ms"] == 750
    assert stages[1]["status"] == "awaiting_permission"


def test_runtime_stage_event_uses_shared_custom_event_contract() -> None:
    tracker = RuntimeStageTracker()
    stage = tracker.start("catalog", "智能体目录读取")

    event = runtime_stage_event(stage)

    assert event["type"] == "CUSTOM"
    assert event["name"] == "runtime_stage_updated"
    assert event["value"]["stage_id"] == "catalog"
    assert event["value"]["status"] == "running"
