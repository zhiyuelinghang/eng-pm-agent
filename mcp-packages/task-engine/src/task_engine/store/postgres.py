"""PostgreSQL 仓储。

保持 SQLite ``Store`` 的公开方法契约不变，只替换持久化实现。任务领域层、
TaskEngine、FastAPI 兼容层和 MCP 都不需要了解 PostgreSQL 表结构。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..domain.models import (
    Activity,
    ActivityKind,
    Assignee,
    IntervalUnit,
    RunMode,
    Schedule,
    Site,
    Step,
    StepSpec,
    StepState,
    TaskFlow,
    TaskInstance,
    TaskState,
    Trigger,
)


_IDENTIFIER_PATTERN = re.compile(r"[a-z_][a-z0-9_]{0,62}")


def _parse(raw: datetime | str | None) -> datetime | None:
    if raw is None or isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(raw)


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_load(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _assignee_to_row(assignee: Assignee | None) -> tuple[str, str]:
    if assignee is None:
        return "", ""
    return assignee.ref, assignee.display_name


def _assignee_from_row(ref: str, name: str) -> Assignee | None:
    if not ref:
        return None
    return Assignee(ref=ref, display_name=name)


def _site_to_row(site: Site | None) -> tuple[str, str, str]:
    if site is None:
        return "", "", ""
    return site.ref, site.name, site.code


def _site_from_row(ref: str, name: str, code: str) -> Site | None:
    if not ref:
        return None
    return Site(ref=ref, name=name, code=code)


class PostgresStore:
    """与分支 ``Store`` 同契约的 PostgreSQL 实现。"""

    def __init__(
        self,
        engine: Engine,
        *,
        schema: str = "task_engine",
        dispose_on_close: bool = False,
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgresStore 只能使用 PostgreSQL Engine")
        if not _IDENTIFIER_PATTERN.fullmatch(schema):
            raise ValueError(f"非法 PostgreSQL schema：{schema!r}")
        self.engine = engine
        self.schema = schema
        self.dispose_on_close = dispose_on_close

    def _table(self, name: str) -> str:
        if not _IDENTIFIER_PATTERN.fullmatch(name):
            raise ValueError(f"非法 PostgreSQL 表名：{name!r}")
        return f'"{self.schema}"."{name}"'

    def close(self) -> None:
        if self.dispose_on_close:
            self.engine.dispose()

    def __enter__(self) -> PostgresStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- 任务流定义 ----

    def save_flow(self, flow: TaskFlow, now: datetime) -> None:
        steps = [
            {
                "name": spec.name,
                "assignee": _assignee_to_row(spec.assignee),
                "due_offset_days": spec.due_offset_days,
                "deliverable": spec.deliverable,
                "instruction": spec.instruction,
                "requires_attachment": spec.requires_attachment,
                "optional": spec.optional,
            }
            for spec in flow.steps
        ]
        trigger = flow.trigger
        site_ref, site_name, site_code = _site_to_row(flow.site)
        confirmer_ref, confirmer_name = _assignee_to_row(flow.confirmer)
        flows = self._table("flows")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {flows} (
                        id, title, summary, category, priority, origin, origin_note,
                        steps_json, watchers_json, tags_json, scope_json,
                        site_ref, site_name, site_code, confirmer_ref, confirmer_name,
                        run_mode, first_at, interval_value, interval_unit, timezone,
                        until_at, max_fires, created_at, updated_at
                    ) VALUES (
                        :id, :title, :summary, :category, :priority, :origin, :origin_note,
                        CAST(:steps_json AS jsonb), CAST(:watchers_json AS jsonb),
                        CAST(:tags_json AS jsonb), CAST(:scope_json AS jsonb),
                        :site_ref, :site_name, :site_code, :confirmer_ref, :confirmer_name,
                        :run_mode, :first_at, :interval_value, :interval_unit, :timezone,
                        :until_at, :max_fires, :created_at, :updated_at
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title=EXCLUDED.title, summary=EXCLUDED.summary,
                        category=EXCLUDED.category, priority=EXCLUDED.priority,
                        steps_json=EXCLUDED.steps_json,
                        watchers_json=EXCLUDED.watchers_json,
                        tags_json=EXCLUDED.tags_json, scope_json=EXCLUDED.scope_json,
                        site_ref=EXCLUDED.site_ref, site_name=EXCLUDED.site_name,
                        site_code=EXCLUDED.site_code,
                        confirmer_ref=EXCLUDED.confirmer_ref,
                        confirmer_name=EXCLUDED.confirmer_name,
                        run_mode=EXCLUDED.run_mode, first_at=EXCLUDED.first_at,
                        interval_value=EXCLUDED.interval_value,
                        interval_unit=EXCLUDED.interval_unit,
                        timezone=EXCLUDED.timezone, until_at=EXCLUDED.until_at,
                        max_fires=EXCLUDED.max_fires, updated_at=EXCLUDED.updated_at
                    """,
                ),
                {
                    "id": flow.id,
                    "title": flow.title,
                    "summary": flow.summary,
                    "category": flow.category,
                    "priority": flow.priority,
                    "origin": flow.origin,
                    "origin_note": flow.origin_note,
                    "steps_json": _json_dump(steps),
                    "watchers_json": _json_dump(
                        [_assignee_to_row(item) for item in flow.watchers],
                    ),
                    "tags_json": _json_dump(list(flow.tags)),
                    "scope_json": _json_dump(flow.scope),
                    "site_ref": site_ref,
                    "site_name": site_name,
                    "site_code": site_code,
                    "confirmer_ref": confirmer_ref,
                    "confirmer_name": confirmer_name,
                    "run_mode": str(trigger.run_mode),
                    "first_at": trigger.first_at,
                    "interval_value": trigger.interval_value,
                    "interval_unit": str(trigger.interval_unit),
                    "timezone": trigger.timezone,
                    "until_at": trigger.until,
                    "max_fires": trigger.max_fires,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    def get_flow(self, flow_id: str) -> TaskFlow | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(f"SELECT * FROM {self._table('flows')} WHERE id = :id"),
                {"id": flow_id},
            ).mappings().first()
        return self._row_to_flow(row) if row else None

    def list_flows(
        self,
        *,
        category: str | None = None,
        limit: int = 100,
    ) -> list[TaskFlow]:
        where = "WHERE category = :category" if category else ""
        params: dict[str, Any] = {"limit": limit}
        if category:
            params["category"] = category
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT * FROM {self._table('flows')} {where} "
                    "ORDER BY updated_at DESC LIMIT :limit",
                ),
                params,
            ).mappings().all()
        return [self._row_to_flow(row) for row in rows]

    def _row_to_flow(self, row: Mapping[str, Any]) -> TaskFlow:
        steps = tuple(
            StepSpec(
                name=item["name"],
                assignee=_assignee_from_row(*item["assignee"]),
                due_offset_days=item["due_offset_days"],
                deliverable=item["deliverable"],
                instruction=item["instruction"],
                requires_attachment=item["requires_attachment"],
                optional=item["optional"],
            )
            for item in _json_load(row["steps_json"], [])
        )
        trigger = Trigger(
            run_mode=RunMode(row["run_mode"]),
            first_at=_parse(row["first_at"]),
            interval_value=row["interval_value"],
            interval_unit=IntervalUnit(row["interval_unit"]),
            timezone=row["timezone"],
            until=_parse(row["until_at"]),
            max_fires=row["max_fires"],
        )
        watchers = tuple(
            assignee
            for item in _json_load(row["watchers_json"], [])
            if (assignee := _assignee_from_row(*item)) is not None
        )
        return TaskFlow(
            id=row["id"],
            title=row["title"],
            steps=steps,
            summary=row["summary"],
            category=row["category"],
            priority=row["priority"],
            trigger=trigger,
            site=_site_from_row(row["site_ref"], row["site_name"], row["site_code"]),
            confirmer=_assignee_from_row(row["confirmer_ref"], row["confirmer_name"]),
            watchers=watchers,
            tags=tuple(_json_load(row["tags_json"], [])),
            origin=row["origin"],
            origin_note=row["origin_note"],
            scope=dict(_json_load(row["scope_json"], {})),
        )

    # ---- 触发计划 ----

    def save_schedule(self, schedule: Schedule, now: datetime) -> None:
        self.save_flow(schedule.flow, now)
        schedules = self._table("schedules")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {schedules} (
                        id, flow_id, next_fire_at, last_fire_at, fire_count,
                        active, paused, last_error, created_at, updated_at
                    ) VALUES (
                        :id, :flow_id, :next_fire_at, :last_fire_at, :fire_count,
                        :active, :paused, :last_error, :created_at, :updated_at
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        next_fire_at=EXCLUDED.next_fire_at,
                        last_fire_at=EXCLUDED.last_fire_at,
                        fire_count=EXCLUDED.fire_count, active=EXCLUDED.active,
                        paused=EXCLUDED.paused, last_error=EXCLUDED.last_error,
                        updated_at=EXCLUDED.updated_at
                    """,
                ),
                {
                    "id": schedule.id,
                    "flow_id": schedule.flow.id,
                    "next_fire_at": schedule.next_fire_at,
                    "last_fire_at": schedule.last_fire_at,
                    "fire_count": schedule.fire_count,
                    "active": schedule.active,
                    "paused": schedule.paused,
                    "last_error": schedule.last_error,
                    "created_at": schedule.created_at or now,
                    "updated_at": now,
                },
            )

    def get_schedule(self, schedule_id: str) -> Schedule | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(f"SELECT * FROM {self._table('schedules')} WHERE id = :id"),
                {"id": schedule_id},
            ).mappings().first()
        if not row:
            return None
        flow = self.get_flow(row["flow_id"])
        return self._row_to_schedule(row, flow) if flow else None

    def list_schedules(self, *, active_only: bool = False) -> list[Schedule]:
        where = "WHERE active IS TRUE AND paused IS FALSE" if active_only else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT * FROM {self._table('schedules')} {where} "
                    "ORDER BY next_fire_at IS NULL, next_fire_at",
                ),
            ).mappings().all()
        result: list[Schedule] = []
        for row in rows:
            flow = self.get_flow(row["flow_id"])
            if flow:
                result.append(self._row_to_schedule(row, flow))
        return result

    def due_schedules(self, now: datetime) -> list[Schedule]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT * FROM {self._table('schedules')}
                    WHERE active IS TRUE AND paused IS FALSE
                      AND next_fire_at IS NOT NULL AND next_fire_at <= :now
                    ORDER BY next_fire_at
                    """,
                ),
                {"now": now},
            ).mappings().all()
        result: list[Schedule] = []
        for row in rows:
            flow = self.get_flow(row["flow_id"])
            if flow:
                result.append(self._row_to_schedule(row, flow))
        return result

    def _row_to_schedule(
        self,
        row: Mapping[str, Any],
        flow: TaskFlow,
    ) -> Schedule:
        return Schedule(
            id=row["id"],
            flow=flow,
            next_fire_at=_parse(row["next_fire_at"]),
            last_fire_at=_parse(row["last_fire_at"]),
            fire_count=row["fire_count"],
            active=bool(row["active"]),
            paused=bool(row["paused"]),
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
            last_error=row["last_error"],
        )

    def delete_schedule(self, schedule_id: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(f"DELETE FROM {self._table('schedules')} WHERE id = :id"),
                {"id": schedule_id},
            )
        return result.rowcount > 0

    # ---- 触发幂等 ----

    def claim_fire(self, schedule_id: str, fire_at: datetime, now: datetime) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    f"""
                    INSERT INTO {self._table('fire_log')} (
                        schedule_id, fire_at, created_at
                    ) VALUES (:schedule_id, :fire_at, :created_at)
                    ON CONFLICT (schedule_id, fire_at) DO NOTHING
                    """,
                ),
                {
                    "schedule_id": schedule_id,
                    "fire_at": fire_at,
                    "created_at": now,
                },
            )
        return result.rowcount > 0

    def record_fire_result(
        self,
        schedule_id: str,
        fire_at: datetime,
        *,
        task_id: str = "",
        error: str = "",
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    UPDATE {self._table('fire_log')}
                    SET task_id = :task_id, error = :error
                    WHERE schedule_id = :schedule_id AND fire_at = :fire_at
                    """,
                ),
                {
                    "task_id": task_id,
                    "error": error,
                    "schedule_id": schedule_id,
                    "fire_at": fire_at,
                },
            )

    def release_fire(self, schedule_id: str, fire_at: datetime) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"DELETE FROM {self._table('fire_log')} "
                    "WHERE schedule_id = :schedule_id AND fire_at = :fire_at",
                ),
                {"schedule_id": schedule_id, "fire_at": fire_at},
            )

    # ---- 任务实例 ----

    def save_task(self, task: TaskInstance) -> None:
        tasks = self._table("tasks")
        steps = self._table("steps")
        activities = self._table("activities")
        site_ref, site_name, site_code = _site_to_row(task.site)
        confirmer_ref, confirmer_name = _assignee_to_row(task.confirmer)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {tasks} (
                        id, flow_id, title, summary, state, priority, category,
                        trigger_note, watchers_json, tags_json, scope_json,
                        site_ref, site_name, site_code, confirmer_ref, confirmer_name,
                        due_at, created_at, updated_at, closed_at
                    ) VALUES (
                        :id, :flow_id, :title, :summary, :state, :priority, :category,
                        :trigger_note, CAST(:watchers_json AS jsonb),
                        CAST(:tags_json AS jsonb), CAST(:scope_json AS jsonb),
                        :site_ref, :site_name, :site_code, :confirmer_ref, :confirmer_name,
                        :due_at, :created_at, :updated_at, :closed_at
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title=EXCLUDED.title, summary=EXCLUDED.summary,
                        state=EXCLUDED.state, priority=EXCLUDED.priority,
                        category=EXCLUDED.category,
                        trigger_note=EXCLUDED.trigger_note,
                        watchers_json=EXCLUDED.watchers_json,
                        tags_json=EXCLUDED.tags_json, scope_json=EXCLUDED.scope_json,
                        site_ref=EXCLUDED.site_ref, site_name=EXCLUDED.site_name,
                        site_code=EXCLUDED.site_code,
                        confirmer_ref=EXCLUDED.confirmer_ref,
                        confirmer_name=EXCLUDED.confirmer_name,
                        due_at=EXCLUDED.due_at, updated_at=EXCLUDED.updated_at,
                        closed_at=EXCLUDED.closed_at
                    """,
                ),
                {
                    "id": task.id,
                    "flow_id": task.flow_id,
                    "title": task.title,
                    "summary": task.summary,
                    "state": str(task.state),
                    "priority": task.priority,
                    "category": task.category,
                    "trigger_note": task.trigger_note,
                    "watchers_json": _json_dump(
                        [_assignee_to_row(item) for item in task.watchers],
                    ),
                    "tags_json": _json_dump(task.tags),
                    "scope_json": _json_dump(task.scope),
                    "site_ref": site_ref,
                    "site_name": site_name,
                    "site_code": site_code,
                    "confirmer_ref": confirmer_ref,
                    "confirmer_name": confirmer_name,
                    "due_at": task.due_at,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                    "closed_at": task.closed_at,
                },
            )
            connection.execute(
                text(f"DELETE FROM {steps} WHERE task_id = :task_id"),
                {"task_id": task.id},
            )
            step_rows = []
            for step in task.steps:
                assignee_ref, assignee_name = _assignee_to_row(step.assignee)
                step_rows.append(
                    {
                        "task_id": task.id,
                        "seq": step.seq,
                        "name": step.name,
                        "state": str(step.state),
                        "assignee_ref": assignee_ref,
                        "assignee_name": assignee_name,
                        "due_at": step.due_at,
                        "deliverable": step.deliverable,
                        "instruction": step.instruction,
                        "requires_attachment": step.requires_attachment,
                        "optional": step.optional,
                        "started_at": step.started_at,
                        "finished_at": step.finished_at,
                        "finished_by": step.finished_by,
                        "comment": step.comment,
                        "attachments_json": _json_dump(step.attachments),
                        "reopened": step.reopened,
                    },
                )
            if step_rows:
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {steps} (
                            task_id, seq, name, state, assignee_ref, assignee_name,
                            due_at, deliverable, instruction, requires_attachment,
                            optional, started_at, finished_at, finished_by, comment,
                            attachments_json, reopened
                        ) VALUES (
                            :task_id, :seq, :name, :state, :assignee_ref,
                            :assignee_name, :due_at, :deliverable, :instruction,
                            :requires_attachment, :optional, :started_at,
                            :finished_at, :finished_by, :comment,
                            CAST(:attachments_json AS jsonb), :reopened
                        )
                        """,
                    ),
                    step_rows,
                )
            activity_rows = [
                {
                    "id": item.id,
                    "task_id": task.id,
                    "kind": str(item.kind),
                    "at": item.at,
                    "actor": item.actor,
                    "step_seq": item.step_seq,
                    "summary": item.summary,
                    "detail_json": _json_dump(item.detail),
                }
                for item in task.activities
            ]
            if activity_rows:
                connection.execute(
                    text(
                        f"""
                        INSERT INTO {activities} (
                            id, task_id, kind, at, actor, step_seq, summary, detail_json
                        ) VALUES (
                            :id, :task_id, :kind, :at, :actor, :step_seq, :summary,
                            CAST(:detail_json AS jsonb)
                        )
                        ON CONFLICT (id) DO NOTHING
                        """,
                    ),
                    activity_rows,
                )

    def get_task(self, task_id: str) -> TaskInstance | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(f"SELECT * FROM {self._table('tasks')} WHERE id = :id"),
                {"id": task_id},
            ).mappings().first()
            if not row:
                return None
            step_rows = connection.execute(
                text(
                    f"SELECT * FROM {self._table('steps')} "
                    "WHERE task_id = :task_id ORDER BY seq",
                ),
                {"task_id": task_id},
            ).mappings().all()
            activity_rows = connection.execute(
                text(
                    f"SELECT * FROM {self._table('activities')} "
                    "WHERE task_id = :task_id ORDER BY at, id",
                ),
                {"task_id": task_id},
            ).mappings().all()
        steps = [
            Step(
                seq=item["seq"],
                name=item["name"],
                assignee=_assignee_from_row(item["assignee_ref"], item["assignee_name"]),
                state=StepState(item["state"]),
                due_at=_parse(item["due_at"]),
                deliverable=item["deliverable"],
                instruction=item["instruction"],
                requires_attachment=bool(item["requires_attachment"]),
                optional=bool(item["optional"]),
                started_at=_parse(item["started_at"]),
                finished_at=_parse(item["finished_at"]),
                finished_by=item["finished_by"],
                comment=item["comment"],
                attachments=list(_json_load(item["attachments_json"], [])),
                reopened=bool(item["reopened"]),
            )
            for item in step_rows
        ]
        activities = [
            Activity(
                id=item["id"],
                kind=ActivityKind(item["kind"]),
                at=_parse(item["at"]),
                actor=item["actor"],
                step_seq=item["step_seq"],
                summary=item["summary"],
                detail=dict(_json_load(item["detail_json"], {})),
            )
            for item in activity_rows
        ]
        watchers = [
            assignee
            for item in _json_load(row["watchers_json"], [])
            if (assignee := _assignee_from_row(*item)) is not None
        ]
        return TaskInstance(
            id=row["id"],
            title=row["title"],
            steps=steps,
            flow_id=row["flow_id"],
            state=TaskState(row["state"]),
            priority=row["priority"],
            category=row["category"],
            summary=row["summary"],
            site=_site_from_row(row["site_ref"], row["site_name"], row["site_code"]),
            confirmer=_assignee_from_row(row["confirmer_ref"], row["confirmer_name"]),
            watchers=watchers,
            tags=list(_json_load(row["tags_json"], [])),
            scope=dict(_json_load(row["scope_json"], {})),
            trigger_note=row["trigger_note"],
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
            closed_at=_parse(row["closed_at"]),
            activities=activities,
        )

    def list_tasks(
        self,
        *,
        state: str | None = None,
        assignee: str | None = None,
        confirmer: str | None = None,
        site: str | None = None,
        category: str | None = None,
        open_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskInstance]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if state:
            clauses.append("t.state = :state")
            params["state"] = state
        if open_only:
            clauses.append("t.state NOT IN ('done', 'cancelled')")
        if category:
            clauses.append("t.category = :category")
            params["category"] = category
        if confirmer:
            clauses.append("t.confirmer_ref = :confirmer")
            params["confirmer"] = confirmer
        if site:
            clauses.append("t.site_ref = :site")
            params["site"] = site
        if assignee:
            clauses.append(
                f"EXISTS (SELECT 1 FROM {self._table('steps')} s "
                "WHERE s.task_id = t.id AND s.assignee_ref = :assignee "
                "AND s.state IN ('active', 'blocked'))",
            )
            params["assignee"] = assignee
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT t.id FROM {self._table('tasks')} t {where} "
                    "ORDER BY t.updated_at DESC LIMIT :limit OFFSET :offset",
                ),
                params,
            ).mappings().all()
        return [task for row in rows if (task := self.get_task(row["id"]))]

    def count_tasks(self, *, state: str | None = None, open_only: bool = False) -> int:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if state:
            clauses.append("state = :state")
            params["state"] = state
        if open_only:
            clauses.append("state NOT IN ('done', 'cancelled')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.engine.connect() as connection:
            value = connection.scalar(
                text(f"SELECT COUNT(*) FROM {self._table('tasks')} {where}"),
                params,
            )
        return int(value or 0)

    def overdue_candidates(self, now: datetime) -> list[TaskInstance]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    SELECT id FROM {self._table('tasks')}
                    WHERE state NOT IN ('done', 'cancelled', 'overdue')
                      AND due_at IS NOT NULL AND due_at < :now
                    """,
                ),
                {"now": now},
            ).mappings().all()
        return [task for row in rows if (task := self.get_task(row["id"]))]

    def delete_task(self, task_id: str) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(f"DELETE FROM {self._table('tasks')} WHERE id = :id"),
                {"id": task_id},
            )
        return result.rowcount > 0
