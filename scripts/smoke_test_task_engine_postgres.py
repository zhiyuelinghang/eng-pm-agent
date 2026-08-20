"""在平台 PostgreSQL 中验证后端与 MCP 任务引擎共库及调度幂等。"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from backend.app.config import get_settings
        from task_engine.domain.models import (
            Assignee,
            IntervalUnit,
            RunMode,
            Site,
            StepSpec,
            TaskFlow,
            TaskState,
            Trigger,
        )
        from task_engine.engine import TaskEngine
        from task_engine.domain.flow import TransitionError
        from task_engine.store.postgres import PostgresStore
    finally:
        sys.path.remove(str(PROJECT_ROOT))

    settings = get_settings()
    schema = settings.task_engine_schema.strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
        raise ValueError("TASK_ENGINE_SCHEMA 不是合法 PostgreSQL 标识符")

    backend_sql_engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
    )
    mcp_url = make_url(settings.database_url)
    if mcp_url.drivername == "postgresql":
        mcp_url = mcp_url.set(drivername="postgresql+psycopg")
    mcp_sql_engine = create_engine(mcp_url, pool_pre_ping=True)
    backend_engine = TaskEngine(
        timezone=settings.task_engine_tz,
        store=PostgresStore(backend_sql_engine, schema=schema),
    )
    mcp_engine = TaskEngine(
        timezone=settings.task_engine_tz,
        store=PostgresStore(mcp_sql_engine, schema=schema),
    )

    token = uuid.uuid4().hex[:12]
    flow_id = f"flow_pg_smoke_{token}"
    timezone = ZoneInfo(settings.task_engine_tz)
    now = datetime.now(timezone).replace(microsecond=0)
    assignee_a = Assignee(ref=f"smoke_owner_a_{token}", display_name="联调甲")
    assignee_b = Assignee(ref=f"smoke_owner_b_{token}", display_name="联调乙")
    confirmer = Assignee(ref=f"smoke_confirmer_{token}", display_name="联调验收人")
    flow = TaskFlow(
        id=flow_id,
        title="PostgreSQL 共库联调",
        steps=(
            StepSpec(
                name="后端办理",
                assignee=assignee_a,
                deliverable="后端证明",
                requires_attachment=True,
            ),
            StepSpec(name="MCP 复核", assignee=assignee_b),
        ),
        site=Site(ref=f"smoke_site_{token}", name="联调工点"),
        confirmer=confirmer,
        category=f"pg_smoke_{token}",
        scope={"smoke_test": token},
    )

    quoted_schema = f'"{schema}"'
    try:
        missing_site_flow = TaskFlow(
            id=flow_id,
            title=flow.title,
            steps=flow.steps,
            confirmer=flow.confirmer,
            category=flow.category,
            scope=flow.scope,
        )
        try:
            backend_engine.dispatch(
                missing_site_flow,
                now=now,
                actor="backend-smoke",
            )
        except ValueError as exc:
            assert str(exc) == "任务未关联工点，无法布置"
        else:
            raise AssertionError("缺少工点的任务未被引擎拒绝")

        task = backend_engine.dispatch(flow, now=now, actor="backend-smoke")
        from_mcp = mcp_engine.get_task(task.id)
        assert from_mcp is not None
        assert from_mcp.site is not None and from_mcp.site.ref == flow.site.ref

        mcp_engine.complete_step(
            task.id,
            0,
            actor=assignee_a.ref,
            attachments=["postgres-smoke.txt"],
            now=now,
        )
        from_backend = backend_engine.get_task(task.id)
        assert from_backend is not None
        assert from_backend.current_step is not None
        assert from_backend.current_step.assignee == assignee_b

        backend_engine.complete_step(
            task.id,
            1,
            actor=assignee_b.ref,
            now=now,
        )
        try:
            mcp_engine.accept(task.id, actor="not-confirmer", now=now)
        except TransitionError as exc:
            assert str(exc) == (
                f"只有确认人 {confirmer.display_name} 可以验收该任务"
            )
        else:
            raise AssertionError("非确认人验收未被引擎拒绝")
        mcp_engine.accept(task.id, actor=confirmer.ref, now=now)
        assert backend_engine.get_task(task.id).state is TaskState.DONE

        schedule = backend_engine.schedule(
            flow,
            trigger=Trigger(
                run_mode=RunMode.RECURRING,
                first_at=now,
                interval_value=1,
                interval_unit=IntervalUnit.HOUR,
                timezone=settings.task_engine_tz,
            ),
            now=now,
        )
        unrelated_due = [
            item.id
            for item in backend_engine.store.due_schedules(now)
            if item.id != schedule.id
        ]
        if unrelated_due:
            raise RuntimeError(
                "存在其他到期计划，为避免联调触发真实任务，已停止 tick 验证",
            )
        first_report = backend_engine.tick(now=now)
        first_duplicate = mcp_engine.tick(now=now)
        second_at = now + timedelta(hours=1)
        unrelated_due = [
            item.id
            for item in backend_engine.store.due_schedules(second_at)
            if item.id != schedule.id
        ]
        if unrelated_due:
            raise RuntimeError(
                "存在其他到期计划，为避免联调触发真实任务，已停止第二次 tick 验证",
            )
        second_report = mcp_engine.tick(now=second_at)
        second_duplicate = backend_engine.tick(now=second_at)
        assert first_report.created_count == 1
        assert first_duplicate.created_count == 0
        assert second_report.created_count == 1
        assert second_duplicate.created_count == 0
        with backend_sql_engine.connect() as connection:
            task_count = connection.execute(
                text(
                    f"SELECT count(*) FROM {quoted_schema}.tasks "
                    "WHERE flow_id = :flow_id",
                ),
                {"flow_id": flow_id},
            ).scalar_one()
        assert task_count == 3
    finally:
        with backend_sql_engine.begin() as connection:
            connection.execute(
                text(
                    f"DELETE FROM {quoted_schema}.fire_log "
                    f"WHERE schedule_id IN (SELECT id FROM {quoted_schema}.schedules "
                    "WHERE flow_id = :flow_id)",
                ),
                {"flow_id": flow_id},
            )
            connection.execute(
                text(
                    f"DELETE FROM {quoted_schema}.tasks WHERE flow_id = :flow_id",
                ),
                {"flow_id": flow_id},
            )
            connection.execute(
                text(
                    f"DELETE FROM {quoted_schema}.schedules WHERE flow_id = :flow_id",
                ),
                {"flow_id": flow_id},
            )
            connection.execute(
                text(f"DELETE FROM {quoted_schema}.flows WHERE id = :flow_id"),
                {"flow_id": flow_id},
            )
        backend_engine.close()
        mcp_engine.close()
        backend_sql_engine.dispose()
        mcp_sql_engine.dispose()

    print("验证 A：缺少工点按指南原文拒绝：通过")
    print("后端写入、MCP 读取与流转：通过")
    print("验证 C：非确认人按指南原文拒绝，确认人验收成功：通过")
    print("两个周期恰好创建两个任务，跨实例重复 tick 不重复：通过")
    print("联调记录清理：完成")


if __name__ == "__main__":
    main()
