"""验证 Task 任务引擎已接入平台后端适配层。

不依赖真实 PostgreSQL，只验证 gateway 的解析、任务流构建、调度与 tick 链路。
"""

from __future__ import annotations

import os
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "smoke-test-secret-0123456789abcdef")
os.environ.setdefault("TASK_ENGINE_TZ", "Asia/Shanghai")

import sys  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.app import models  # noqa: E402
from backend.app.db import Base  # noqa: E402
from backend.app.task_engine_gateway import (  # noqa: E402
    build_flow,
    to_api_task,
)
from task_engine.engine import TaskEngine  # noqa: E402


_PINYIN_STUB = types.ModuleType("pypinyin")
_PINYIN_STUB.lazy_pinyin = lambda text: list(text)
sys.modules["pypinyin"] = _PINYIN_STUB

import backend.app.api as api  # noqa: E402
from backend.app.schemas import (  # noqa: E402
    TaskInput,
    TaskStepUpdate,
    TaskTransitionInput,
)


class _Payload:
    def __init__(self) -> None:
        self.title = "每周核查基坑监测数据"
        self.task_type = "risk_alert"
        self.risk_level = "high"
        self.assignee_user_id = 1
        self.confirmer_user_id = 2
        self.wbs_item_id = 1
        self.risk_source_id = None
        self.trigger_reason = "任务引擎接入验证"
        self.required_materials = ["监测日报"]
        self.workflow_steps = [
            {
                "name": "现场检查",
                "owner_user_id": "1",
                "due_at": "2026-08-21",
                "material": "现场照片",
            },
            {
                "name": "监测复核",
                "owner_user_id": "2",
                "due_at": "2026-08-22",
                "material": "复核意见",
            },
        ]
        self.run_mode = "recurring"
        self.trigger_date = "2026-08-21"
        self.trigger_time = "09:00"
        self.trigger_interval_value = 1
        self.trigger_interval_unit = "week"
        self.trigger_end_mode = "never"
        self.trigger_until_date = None
        self.trigger_max_fires = None
        self.trigger_calendar_mode = "weekdays"
        self.trigger_weekdays = []
        self.trigger_day_of_month = None
        self.cc = "项目经理"


def main() -> int:
    orm_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(orm_engine)
    with Session(orm_engine) as db:
        project = models.Project(name="任务引擎接入验证项目")
        owner = models.User(
            username="task-owner",
            password_hash="hash",
            role="user",
            real_name="任务责任人",
            identity_card_no="TASK_OWNER",
        )
        confirmer = models.User(
            username="task-confirmer",
            password_hash="hash",
            role="user",
            real_name="任务确认人",
            identity_card_no="TASK_CONFIRMER",
        )
        db.add_all([project, owner, confirmer])
        db.flush()
        db.add_all(
            [
                models.ProjectMember(project_id=project.id, user_id=owner.id),
                models.ProjectMember(project_id=project.id, user_id=confirmer.id),
            ],
        )
        site = models.WbsItem(
            project_id=project.id,
            sort_order=1,
            wbs_code="WBS-001",
            name="一号工点",
            level=1,
        )
        db.add(site)
        db.commit()

        flow = build_flow(db, project.id, _Payload())
        assert flow.site is not None and flow.site.ref == str(site.id)
        assert flow.confirmer is not None and flow.confirmer.ref == str(confirmer.id)
        assert len(flow.steps) == 2
        assert flow.trigger.is_recurring

        with tempfile.TemporaryDirectory(prefix="task-engine-smoke-") as tmp:
            engine = TaskEngine(Path(tmp) / "engine.db", timezone="Asia/Shanghai")
            timezone = ZoneInfo("Asia/Shanghai")
            first_at = datetime(2026, 8, 21, 9, 0, tzinfo=timezone)
            plan = engine.schedule(flow, now=first_at - timedelta(minutes=1))
            assert plan.next_fire_at == first_at

            report = engine.tick(now=first_at)
            assert report.created_count == 1
            duplicate = engine.tick(now=first_at)
            assert duplicate.created_count == 0
            task = engine.list_tasks()[0]
            view = to_api_task(task)
            assert view["status"] in {"pending", "processing"}
            assert view["wbs_item_id"] == site.id
            assert view["task_type"] == "risk_alert"
            print(view["status"], view["workflow_steps"][0]["status"])
            engine.close()

    with Session(orm_engine) as db:
        project = models.Project(name="任务引擎 API 接入验证项目")
        owner = models.User(
            username="api-owner",
            password_hash="hash",
            role="user",
            real_name="API责任人",
            identity_card_no="API_OWNER",
        )
        confirmer = models.User(
            username="api-confirmer",
            password_hash="hash",
            role="user",
            real_name="API确认人",
            identity_card_no="API_CONFIRMER",
        )
        db.add_all([project, owner, confirmer])
        db.flush()
        db.add_all(
            [
                models.ProjectMember(project_id=project.id, user_id=owner.id),
                models.ProjectMember(project_id=project.id, user_id=confirmer.id),
            ],
        )
        site = models.WbsItem(
            project_id=project.id,
            sort_order=1,
            wbs_code="WBS-API-001",
            name="API工点",
            level=1,
        )
        db.add(site)
        db.commit()

        with tempfile.TemporaryDirectory(prefix="task-engine-api-smoke-") as tmp:
            reference = TaskEngine(
                Path(tmp) / "api.db",
                timezone="Asia/Shanghai",
            )
            api.get_engine = lambda: reference
            payload = TaskInput(
                title="API 立即布置",
                task_type="risk_alert",
                risk_level="high",
                confirmer_user_id=confirmer.id,
                wbs_item_id=site.id,
                trigger_reason="API 接入验证",
                workflow_steps=[
                    {
                        "name": "现场检查",
                        "owner_user_id": str(owner.id),
                        "due_at": "2026-08-21",
                        "material": "现场照片",
                    },
                ],
            )
            created = api.create_task(
                project.id,
                payload,
                db,
                owner,
            )["data"]
            assert created["status"] == "processing"
            api.update_task_step(
                created["id"],
                0,
                TaskStepUpdate(
                    status="completed",
                    note="已完成",
                    attachments=["现场照片.jpg"],
                ),
                db,
                owner,
            )
            accepted = api.transition_task(
                created["id"],
                TaskTransitionInput(status="completed"),
                db,
                confirmer,
            )["data"]
            assert accepted["status"] == "completed"

            recurring = TaskInput(
                title="API 周期检查",
                task_type="risk_alert",
                risk_level="low",
                confirmer_user_id=confirmer.id,
                wbs_item_id=site.id,
                run_mode="recurring",
                trigger_date="2026-08-21",
                trigger_time="09:00",
                trigger_interval_value=1,
                trigger_interval_unit="week",
                workflow_steps=[
                    {
                        "name": "周期检查",
                        "owner_user_id": str(owner.id),
                        "due_at": "2026-08-21",
                        "material": "检查记录",
                    },
                ],
            )
            registered = api.create_task(
                project.id,
                recurring,
                db,
                owner,
            )["data"]
            assert registered["schedule_id"].startswith("sched_")
            reference.close()

    print("任务引擎平台接入冒烟测试：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
