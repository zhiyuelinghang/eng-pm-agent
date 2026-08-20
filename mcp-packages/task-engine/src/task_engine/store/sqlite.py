"""SQLite 仓储。

负责领域对象与关系表之间的搬运。领域层对本模块一无所知——依赖是单向的。

所有时间以 ISO8601 字符串存储（带时区偏移），读出时还原为 aware datetime。
SQLite 没有原生时间类型，字符串排序恰好等价于时间排序，索引可用。
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

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

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _parse(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


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


class Store:
    """任务引擎的持久层。

    用法：
        with Store("engine.db") as store:
            store.save_flow(flow, now)
    """

    def __init__(self, path: str | Path = "task_engine.db") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """把多个写操作并成一个事务，失败时整体回滚。"""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

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
        self._conn.execute(
            """
            INSERT INTO flows (id, title, summary, category, priority, origin, origin_note,
                               steps_json, watchers_json, tags_json, scope_json,
                               site_ref, site_name, site_code, confirmer_ref, confirmer_name,
                               run_mode, first_at, interval_value, interval_unit, timezone,
                               until_at, max_fires, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (id) DO UPDATE SET
                title=excluded.title, summary=excluded.summary, category=excluded.category,
                priority=excluded.priority, steps_json=excluded.steps_json,
                watchers_json=excluded.watchers_json, tags_json=excluded.tags_json,
                scope_json=excluded.scope_json,
                site_ref=excluded.site_ref, site_name=excluded.site_name,
                site_code=excluded.site_code,
                confirmer_ref=excluded.confirmer_ref, confirmer_name=excluded.confirmer_name,
                run_mode=excluded.run_mode,
                first_at=excluded.first_at, interval_value=excluded.interval_value,
                interval_unit=excluded.interval_unit, timezone=excluded.timezone,
                until_at=excluded.until_at, max_fires=excluded.max_fires,
                updated_at=excluded.updated_at
            """,
            (
                flow.id, flow.title, flow.summary, flow.category, flow.priority,
                flow.origin, flow.origin_note,
                json.dumps(steps, ensure_ascii=False),
                json.dumps([_assignee_to_row(w) for w in flow.watchers], ensure_ascii=False),
                json.dumps(list(flow.tags), ensure_ascii=False),
                json.dumps(flow.scope, ensure_ascii=False),
                *_site_to_row(flow.site),
                *_assignee_to_row(flow.confirmer),
                str(trigger.run_mode), _iso(trigger.first_at),
                trigger.interval_value, str(trigger.interval_unit), trigger.timezone,
                _iso(trigger.until), trigger.max_fires,
                _iso(now), _iso(now),
            ),
        )
        self._conn.commit()

    def get_flow(self, flow_id: str) -> TaskFlow | None:
        row = self._conn.execute("SELECT * FROM flows WHERE id = ?", (flow_id,)).fetchone()
        return self._row_to_flow(row) if row else None

    def list_flows(self, *, category: str | None = None, limit: int = 100) -> list[TaskFlow]:
        if category:
            rows = self._conn.execute(
                "SELECT * FROM flows WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM flows ORDER BY updated_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return [self._row_to_flow(row) for row in rows]

    def _row_to_flow(self, row: sqlite3.Row) -> TaskFlow:
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
            for item in json.loads(row["steps_json"])
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
            watchers=tuple(_assignee_from_row(*w) for w in json.loads(row["watchers_json"]) if w[0]),
            tags=tuple(json.loads(row["tags_json"])),
            origin=row["origin"],
            origin_note=row["origin_note"],
            scope=json.loads(row["scope_json"]),
        )

    # ---- 触发计划 ----

    def save_schedule(self, schedule: Schedule, now: datetime) -> None:
        self.save_flow(schedule.flow, now)
        self._conn.execute(
            """
            INSERT INTO schedules (id, flow_id, next_fire_at, last_fire_at, fire_count,
                                   active, paused, last_error, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (id) DO UPDATE SET
                next_fire_at=excluded.next_fire_at, last_fire_at=excluded.last_fire_at,
                fire_count=excluded.fire_count, active=excluded.active,
                paused=excluded.paused, last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (
                schedule.id, schedule.flow.id,
                _iso(schedule.next_fire_at), _iso(schedule.last_fire_at),
                schedule.fire_count, int(schedule.active), int(schedule.paused),
                schedule.last_error,
                _iso(schedule.created_at or now), _iso(now),
            ),
        )
        self._conn.commit()

    def get_schedule(self, schedule_id: str) -> Schedule | None:
        row = self._conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if not row:
            return None
        flow = self.get_flow(row["flow_id"])
        return self._row_to_schedule(row, flow) if flow else None

    def list_schedules(self, *, active_only: bool = False) -> list[Schedule]:
        sql = "SELECT * FROM schedules"
        if active_only:
            sql += " WHERE active = 1 AND paused = 0"
        sql += " ORDER BY next_fire_at IS NULL, next_fire_at"
        result = []
        for row in self._conn.execute(sql).fetchall():
            flow = self.get_flow(row["flow_id"])
            if flow:
                result.append(self._row_to_schedule(row, flow))
        return result

    def due_schedules(self, now: datetime) -> list[Schedule]:
        """找出所有到期待触发的计划。tick 的核心查询。"""
        rows = self._conn.execute(
            """
            SELECT * FROM schedules
            WHERE active = 1 AND paused = 0
              AND next_fire_at IS NOT NULL AND next_fire_at <= ?
            ORDER BY next_fire_at
            """,
            (_iso(now),),
        ).fetchall()
        result = []
        for row in rows:
            flow = self.get_flow(row["flow_id"])
            if flow:
                result.append(self._row_to_schedule(row, flow))
        return result

    def _row_to_schedule(self, row: sqlite3.Row, flow: TaskFlow) -> Schedule:
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
        cur = self._conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # ---- 触发幂等 ----

    def claim_fire(self, schedule_id: str, fire_at: datetime, now: datetime) -> bool:
        """抢占一次触发。返回 False 表示该时刻已被处理过。

        依赖 (schedule_id, fire_at) 主键做幂等——重复 tick 不会重复建任务。
        """
        try:
            self._conn.execute(
                "INSERT INTO fire_log (schedule_id, fire_at, created_at) VALUES (?,?,?)",
                (schedule_id, _iso(fire_at), _iso(now)),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def record_fire_result(
        self, schedule_id: str, fire_at: datetime, *, task_id: str = "", error: str = "",
    ) -> None:
        self._conn.execute(
            "UPDATE fire_log SET task_id = ?, error = ? WHERE schedule_id = ? AND fire_at = ?",
            (task_id, error, schedule_id, _iso(fire_at)),
        )
        self._conn.commit()

    def release_fire(self, schedule_id: str, fire_at: datetime) -> None:
        """回滚抢占，让下次 tick 可以重试。"""
        self._conn.execute(
            "DELETE FROM fire_log WHERE schedule_id = ? AND fire_at = ?",
            (schedule_id, _iso(fire_at)),
        )
        self._conn.commit()

    # ---- 任务实例 ----

    def save_task(self, task: TaskInstance) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO tasks (id, flow_id, title, summary, state, priority, category,
                                   trigger_note, watchers_json, tags_json, scope_json,
                                   site_ref, site_name, site_code,
                                   confirmer_ref, confirmer_name,
                                   due_at, created_at, updated_at, closed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT (id) DO UPDATE SET
                    title=excluded.title, summary=excluded.summary, state=excluded.state,
                    priority=excluded.priority, category=excluded.category,
                    trigger_note=excluded.trigger_note, watchers_json=excluded.watchers_json,
                    tags_json=excluded.tags_json, scope_json=excluded.scope_json,
                    site_ref=excluded.site_ref, site_name=excluded.site_name,
                    site_code=excluded.site_code,
                    confirmer_ref=excluded.confirmer_ref, confirmer_name=excluded.confirmer_name,
                    due_at=excluded.due_at, updated_at=excluded.updated_at,
                    closed_at=excluded.closed_at
                """,
                (
                    task.id, task.flow_id, task.title, task.summary, str(task.state),
                    task.priority, task.category, task.trigger_note,
                    json.dumps([_assignee_to_row(w) for w in task.watchers], ensure_ascii=False),
                    json.dumps(task.tags, ensure_ascii=False),
                    json.dumps(task.scope, ensure_ascii=False),
                    *_site_to_row(task.site),
                    *_assignee_to_row(task.confirmer),
                    _iso(task.due_at), _iso(task.created_at), _iso(task.updated_at),
                    _iso(task.closed_at),
                ),
            )

            # 节点整体重写：数量少，且状态变化频繁，逐条 diff 不划算
            conn.execute("DELETE FROM steps WHERE task_id = ?", (task.id,))
            conn.executemany(
                """
                INSERT INTO steps (task_id, seq, name, state, assignee_ref, assignee_name,
                                   due_at, deliverable, instruction,
                                   requires_attachment, optional, started_at, finished_at,
                                   finished_by, comment, attachments_json, reopened)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        task.id, step.seq, step.name, str(step.state),
                        *_assignee_to_row(step.assignee),
                        _iso(step.due_at), step.deliverable, step.instruction,
                        int(step.requires_attachment), int(step.optional),
                        _iso(step.started_at), _iso(step.finished_at), step.finished_by,
                        step.comment, json.dumps(step.attachments, ensure_ascii=False),
                        int(step.reopened),
                    )
                    for step in task.steps
                ],
            )

            # 流转记录只增不改，用 INSERT OR IGNORE 避免重复写入
            conn.executemany(
                """
                INSERT OR IGNORE INTO activities (id, task_id, kind, at, actor, step_seq,
                                                  summary, detail_json)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        act.id, task.id, str(act.kind), _iso(act.at), act.actor,
                        act.step_seq, act.summary,
                        json.dumps(act.detail, ensure_ascii=False, default=str),
                    )
                    for act in task.activities
                ],
            )

    def get_task(self, task_id: str) -> TaskInstance | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return None

        steps = [
            Step(
                seq=srow["seq"],
                name=srow["name"],
                assignee=_assignee_from_row(
                    srow["assignee_ref"], srow["assignee_name"],
                ),
                state=StepState(srow["state"]),
                due_at=_parse(srow["due_at"]),
                deliverable=srow["deliverable"],
                instruction=srow["instruction"],
                requires_attachment=bool(srow["requires_attachment"]),
                optional=bool(srow["optional"]),
                started_at=_parse(srow["started_at"]),
                finished_at=_parse(srow["finished_at"]),
                finished_by=srow["finished_by"],
                comment=srow["comment"],
                attachments=json.loads(srow["attachments_json"]),
                reopened=bool(srow["reopened"]),
            )
            for srow in self._conn.execute(
                "SELECT * FROM steps WHERE task_id = ? ORDER BY seq", (task_id,),
            ).fetchall()
        ]

        activities = [
            Activity(
                id=arow["id"],
                kind=ActivityKind(arow["kind"]),
                at=_parse(arow["at"]),
                actor=arow["actor"],
                step_seq=arow["step_seq"],
                summary=arow["summary"],
                detail=json.loads(arow["detail_json"]),
            )
            for arow in self._conn.execute(
                "SELECT * FROM activities WHERE task_id = ? ORDER BY at, rowid", (task_id,),
            ).fetchall()
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
            watchers=[a for w in json.loads(row["watchers_json"]) if (a := _assignee_from_row(*w))],
            tags=json.loads(row["tags_json"]),
            scope=json.loads(row["scope_json"]),
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
        """查询任务。

        `assignee` 按「当前责任人」过滤——即该人负责的活跃节点所属任务，
        这正是「我的任务」的语义。
        `confirmer` 按确认人过滤，配合 state='review' 即「待我验收」。
        `site` 按工点过滤，支持「这个工点上还有哪些未闭环的活」。
        """
        clauses: list[str] = []
        params: list[Any] = []

        if state:
            clauses.append("t.state = ?")
            params.append(state)
        if open_only:
            clauses.append("t.state NOT IN ('done', 'cancelled')")
        if category:
            clauses.append("t.category = ?")
            params.append(category)
        if confirmer:
            clauses.append("t.confirmer_ref = ?")
            params.append(confirmer)
        if site:
            clauses.append("t.site_ref = ?")
            params.append(site)
        if assignee:
            clauses.append(
                "EXISTS (SELECT 1 FROM steps s WHERE s.task_id = t.id "
                "AND s.assignee_ref = ? AND s.state IN ('active', 'blocked'))",
            )
            params.append(assignee)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT t.id FROM tasks t {where} ORDER BY t.updated_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [task for row in rows if (task := self.get_task(row["id"]))]

    def count_tasks(self, *, state: str | None = None, open_only: bool = False) -> int:
        clauses = []
        params: list[Any] = []
        if state:
            clauses.append("state = ?")
            params.append(state)
        if open_only:
            clauses.append("state NOT IN ('done', 'cancelled')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._conn.execute(f"SELECT COUNT(*) AS n FROM tasks {where}", params).fetchone()
        return int(row["n"])

    def overdue_candidates(self, now: datetime) -> list[TaskInstance]:
        """找出已过截止时间但尚未标记逾期的任务。"""
        rows = self._conn.execute(
            """
            SELECT id FROM tasks
            WHERE state NOT IN ('done', 'cancelled', 'overdue')
              AND due_at IS NOT NULL AND due_at < ?
            """,
            (_iso(now),),
        ).fetchall()
        return [task for row in rows if (task := self.get_task(row["id"]))]

    def delete_task(self, task_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._conn.commit()
        return cur.rowcount > 0
