from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api import (
    create_quality_metric,
    create_risk,
    create_wbs,
    update_quality_metric,
    update_risk,
    update_wbs,
)
from backend.app.db import Base
from backend.app.models import Project, User, WbsItem, WbsPredecessor
from backend.app.schemas import QualityMetricInput, RiskInput, WbsInput


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_wbs_full_details_can_be_created_and_updated(db: Session) -> None:
    user = User(
        username="wbs-admin",
        password_hash="test",
        role="admin",
        real_name="项目管理员",
        identity_card_no="wbs-api-test-admin",
    )
    project = Project(name="WBS接口测试项目")
    db.add_all([user, project])
    db.commit()

    root_result = create_wbs(
        project.id,
        WbsInput(code="1", name="项目计划", level=1, status=None),
        db,
        user,
    )
    root_id = root_result["data"]["id"]
    assert root_result["data"]["status_text"] is None

    child_result = create_wbs(
        project.id,
        WbsInput(
            code="1.1",
            name="施工准备",
            parent_id=root_id,
            level=2,
            sort_order=7,
            assigned_to_text="张工",
            planned_start="2026-08-01",
            planned_finish="2026-08-05",
            deadline="2026-08-06",
            progress=Decimal("12.5"),
            duration_hours=Decimal("40"),
            estimated_hours=Decimal("36.5"),
            time_log_minutes=90,
            status="打开",
            priority_text="高",
            description="完成现场、技术和资料准备。",
            budget=Decimal("12000.50"),
            actual_cost=Decimal("3500"),
            item_type="任务",
            predecessor_ids=[root_id],
        ),
        db,
        user,
    )
    child_id = child_result["data"]["id"]

    updated = update_wbs(
        child_id,
        WbsInput(
            code="1.1",
            name="施工准备（修订）",
            parent_id=root_id,
            level=3,
            sort_order=8,
            assigned_to_text="李工",
            planned_start="2026-08-02",
            planned_finish="2026-08-07",
            deadline=None,
            progress=Decimal("25.5"),
            duration_hours=Decimal("48"),
            estimated_hours=None,
            time_log_minutes=180,
            status=None,
            priority_text="紧急",
            description="修订后的完整工作内容。",
            budget=Decimal("15000"),
            actual_cost=Decimal("5000"),
            item_type="里程碑",
            predecessor_ids=[root_id],
        ),
        db,
        user,
    )["data"]

    assert updated["parent_id"] == root_id
    assert updated["level"] == 3
    assert updated["sort_order"] == 8
    assert updated["assigned_to_text"] == "李工"
    assert updated["status_text"] is None
    assert updated["description"] == "修订后的完整工作内容。"
    assert updated["predecessor_ids"] == [root_id]
    assert db.scalar(
        select(WbsPredecessor).where(WbsPredecessor.wbs_item_id == child_id),
    ) is not None


def test_wbs_parent_cannot_be_changed_to_a_descendant(db: Session) -> None:
    user = User(
        username="wbs-cycle-admin",
        password_hash="test",
        role="admin",
        real_name="项目管理员",
        identity_card_no="wbs-api-cycle-admin",
    )
    project = Project(name="WBS层级校验项目")
    db.add_all([user, project])
    db.flush()
    root = WbsItem(
        project_id=project.id,
        wbs_code="1",
        name="根节点",
        level=1,
        sort_order=1,
    )
    db.add(root)
    db.flush()
    child = WbsItem(
        project_id=project.id,
        parent_id=root.id,
        wbs_code="1.1",
        name="子节点",
        level=2,
        sort_order=2,
    )
    db.add(child)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        update_wbs(
            root.id,
            WbsInput(code="1", name="根节点", parent_id=child.id, level=1),
            db,
            user,
        )
    assert exc_info.value.detail == "不能把当前工序或其下级设为上级工序"

    db.add(WbsPredecessor(wbs_item_id=child.id, predecessor_wbs_item_id=root.id))
    db.commit()
    with pytest.raises(HTTPException) as predecessor_exc:
        update_wbs(
            root.id,
            WbsInput(code="1", name="根节点", level=1, predecessor_ids=[child.id]),
            db,
            user,
        )
    assert predecessor_exc.value.detail == "前置工序关系不能形成循环"


def test_quality_and_risk_details_can_be_updated_without_fake_fields(db: Session) -> None:
    user = User(
        username="formal-data-admin",
        password_hash="test",
        role="admin",
        real_name="项目管理员",
        identity_card_no="formal-data-api-admin",
    )
    project = Project(name="质量风险接口测试项目")
    db.add_all([user, project])
    db.flush()
    wbs = WbsItem(
        project_id=project.id,
        wbs_code="1.13.1",
        name="竣工验收及移交",
        level=3,
        sort_order=1,
    )
    db.add(wbs)
    db.commit()

    quality = create_quality_metric(
        project.id,
        QualityMetricInput(
            wbs_item_id=wbs.id,
            name="竣工实体质量检查",
            requirement="实体质量合格，功能检测通过。",
            inspection_frequency="竣工验收前一次",
            related_documents="竣工验收报告、功能检测报告",
        ),
        db,
        user,
    )["data"]
    quality = update_quality_metric(
        quality["id"],
        QualityMetricInput(
            wbs_item_id=wbs.id,
            name="竣工实体质量检查",
            requirement="实体质量合格，功能检测及观感验收通过。",
            inspection_frequency="验收前及整改后各一次",
            related_documents="竣工验收报告\n功能检测报告\n整改复查记录",
        ),
        db,
        user,
    )["data"]
    assert quality["wbs_item_id"] == wbs.id
    assert quality["wbs_name"] == "竣工验收及移交"
    assert quality["related_documents"] == "竣工验收报告\n功能检测报告\n整改复查记录"

    risk = create_risk(
        project.id,
        RiskInput(
            serial_no=8,
            name="竣工资料缺项",
            level="较大",
            risk_type="竣工验收及移交",
            planned_start="2026-08-01",
            planned_finish="2026-08-15",
            control_requirements="验收前完成资料目录核查，缺项须闭环。",
            summary="影响竣工验收与移交节点。",
        ),
        db,
        user,
    )["data"]
    risk = update_risk(
        risk["id"],
        RiskInput(
            serial_no=9,
            name="竣工资料缺项",
            level="重大",
            risk_type="竣工验收及移交",
            planned_start="2026-08-02",
            planned_finish="2026-08-20",
            control_requirements="逐项核对目录、责任人和最迟补齐日期。",
            summary="可能推迟验收备案和项目移交。",
        ),
        db,
        user,
    )["data"]
    assert risk["serial_no"] == 9
    assert str(risk["risk_window_start_date"]) == "2026-08-02"
    assert str(risk["risk_window_end_date"]) == "2026-08-20"
    assert risk["risk_level"] == "重大"
    assert risk["evaluation_condition"] == "逐项核对目录、责任人和最迟补齐日期。"
    assert risk["summary"] == "可能推迟验收备案和项目移交。"
    assert "related_wbs_item_id" not in risk
    assert "related_wbs_code" not in risk
