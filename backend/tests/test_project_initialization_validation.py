import importlib
import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.initialization_draft_queries import (
    compose_initialization_draft_payload,
)
from backend.app.models import (
    AgentConversation,
    Project,
    ProjectInitializationDraft,
    ProjectInitializationDraftSection,
    ProjectInitializationValidationRun,
    User,
)
from backend.app.project_initialization import (
    ApplyInitializationDraftInput,
    ProjectInitializationPayload,
    apply_initialization_draft,
    suggest_unique_username,
)


VALIDATOR_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mcp-packages"
    / "project-initialization-validator"
)
sys.path.insert(0, str(VALIDATOR_ROOT))
try:
    initialization_validator = importlib.import_module(
        "initialization_validator",
    )
finally:
    sys.path.remove(str(VALIDATOR_ROOT))


def validate_initialization_payload(
    payload: ProjectInitializationPayload,
) -> list[dict[str, object]]:
    data = payload.model_dump(mode="json")
    data["project"]["record_id"] = 1
    for section_index, section in enumerate(
        ("personnel", "wbs", "risks", "quality_requirements"),
        start=2,
    ):
        for row_index, item in enumerate(data[section], start=1):
            item["record_id"] = section_index * 1000 + row_index
    result = initialization_validator.validate_project_initialization(
        data,
    )
    return result["validation_issues"]


def test_ready_draft_can_be_applied_with_current_structured_validation() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="草稿入库测试项目")
        user = User(
            username="apply-admin",
            password_hash="test",
            role="admin",
            real_name="测试管理员",
            identity_card_no="APPLY_TEST_ADMIN",
        )
        db.add_all([project, user])
        db.flush()
        conversation = AgentConversation(
            project_id=project.id,
            user_id=user.id,
            agent_id="initializer",
            agent_name="初始化助手",
            conversation_type="initialization",
            title="初始化",
        )
        db.add(conversation)
        db.flush()
        draft = ProjectInitializationDraft(
            project_id=project.id,
            conversation_id=conversation.id,
            created_by_user_id=user.id,
            status="ready",
            payload={
                "project": {
                    "engineering_type_description": "测试工程",
                },
            },
        )
        db.add(draft)
        db.flush()
        db.add(
            ProjectInitializationDraftSection(
                draft_id=draft.id,
                project_id=project.id,
                conversation_id=conversation.id,
                section="project",
                writer_agent_id="project-specialist",
                payload={"engineering_type_description": "测试工程"},
                source_files=["工程概况.docx"],
                extraction_notes=[],
            ),
        )
        db.add(
            ProjectInitializationValidationRun(
                draft_id=draft.id,
                project_id=project.id,
                conversation_id=conversation.id,
                draft_revision=draft.revision,
                status="completed",
                result_status="ready",
                package_id="project-initialization-validator",
                package_version="2.0.0",
                ruleset_version="2026.08.2",
                validation_issues=[],
                duration_ms=10,
            ),
        )

        result = apply_initialization_draft(
            db,
            draft,
            ApplyInitializationDraftInput(allow_partial=True),
        )

        assert result["status"] == "applied"
        assert draft.status == "applied"
        assert draft.applied_at is not None
        assert project.engineering_type_description == "测试工程"


def test_review_composes_sections_and_ignores_legacy_draft_payload() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="分区组装测试")
        user = User(
            username="compose-admin",
            password_hash="test",
            role="admin",
            real_name="测试管理员",
            identity_card_no="COMPOSE_ADMIN",
        )
        db.add_all([project, user])
        db.flush()
        conversation = AgentConversation(
            project_id=project.id,
            user_id=user.id,
            agent_id="initializer",
            agent_name="初始化助手",
            conversation_type="initialization",
            title="初始化",
        )
        db.add(conversation)
        db.flush()
        draft = ProjectInitializationDraft(
            project_id=project.id,
            conversation_id=conversation.id,
            created_by_user_id=user.id,
            status="building",
            payload={
                "engineering_info": {"project_name": "旧结构"},
                "quality_metrics": [{"name": "旧字段"}],
            },
        )
        db.add(draft)
        db.flush()
        db.add_all(
            [
                ProjectInitializationDraftSection(
                    draft_id=draft.id,
                    project_id=project.id,
                    conversation_id=conversation.id,
                    section="project",
                    writer_agent_id="project-specialist",
                    payload={"engineering_type_description": "异地扩建项目"},
                    source_files=["工程概况.docx"],
                    extraction_notes=[],
                ),
                ProjectInitializationDraftSection(
                    draft_id=draft.id,
                    project_id=project.id,
                    conversation_id=conversation.id,
                    section="risks",
                    writer_agent_id="risk-specialist",
                    payload=[
                        {
                            "serial_no": 1,
                            "related_process_name": "基坑施工",
                            "risk_part": "深基坑",
                            "risk_level": "重大风险",
                            "evaluation_condition": "开挖深度超过 5 米",
                        },
                    ],
                    source_files=["风险清单.xlsx"],
                    extraction_notes=[],
                ),
            ],
        )
        db.flush()

        payload = compose_initialization_draft_payload(db, draft)

        assert payload.project.engineering_type_description == "异地扩建项目"
        assert isinstance(payload.project.record_id, int)
        assert len(payload.risks) == 1
        assert payload.risks[0].risk_part == "深基坑"
        assert isinstance(payload.risks[0].record_id, int)


def _wbs(
    code: str,
    *,
    parent: str | None,
    name: str,
    start: str,
    finish: str,
    predecessors: list[str] | None = None,
) -> dict:
    return {
        "wbs_code": code,
        "parent_wbs_code": parent,
        "predecessor_wbs_codes": predecessors or [],
        "name": name,
        "planned_start_at": start,
        "planned_finish_at": finish,
        "progress_percent": 0,
        "status_text": "打开",
        "priority_text": "中",
        "level": code.count(".") + 1,
    }


def test_numeric_wbs_order_allows_1_1_9_before_1_1_10() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "wbs": [
                _wbs(
                    "1",
                    parent=None,
                    name="项目",
                    start="2025-01-01T08:00:00",
                    finish="2025-12-31T17:00:00",
                ),
                _wbs(
                    "1.1",
                    parent="1",
                    name="施工",
                    start="2025-01-01T08:00:00",
                    finish="2025-04-30T17:00:00",
                ),
                _wbs(
                    "1.1.9",
                    parent="1.1",
                    name="2025年春节放假",
                    start="2025-01-21T08:00:00",
                    finish="2025-02-12T17:00:00",
                ),
                _wbs(
                    "1.1.10",
                    parent="1.1",
                    name="节后复工",
                    start="2025-02-13T08:00:00",
                    finish="2025-02-20T17:00:00",
                    predecessors=["1.1.9"],
                ),
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert not any("1.1.10 的计划开始早于前任" in item["message"] for item in issues)
    assert not any("同级 WBS 编码顺序" in item["message"] for item in issues)


def test_sibling_start_dates_must_follow_numeric_wbs_order() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "wbs": [
                _wbs(
                    "1",
                    parent=None,
                    name="项目",
                    start="2025-01-01T08:00:00",
                    finish="2025-12-31T17:00:00",
                ),
                _wbs(
                    "1.1",
                    parent="1",
                    name="第一项",
                    start="2025-02-01T08:00:00",
                    finish="2025-02-10T17:00:00",
                ),
                _wbs(
                    "1.2",
                    parent="1",
                    name="第二项",
                    start="2025-01-01T08:00:00",
                    finish="2025-01-10T17:00:00",
                ),
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert any(
        item["level"] == "warning"
        and item["rule_id"] == "wbs.sibling_start_order"
        and item["field_name"] == "planned_start_at"
        and item["target_record_id"] == 3003
        for item in issues
    )


def test_overlapping_predecessor_dates_are_reported_for_confirmation() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "wbs": [
                _wbs(
                    "1",
                    parent=None,
                    name="项目",
                    start="2025-01-01T08:00:00",
                    finish="2025-12-31T17:00:00",
                ),
                _wbs(
                    "1.1",
                    parent="1",
                    name="前任",
                    start="2025-01-01T08:00:00",
                    finish="2025-02-10T17:00:00",
                ),
                _wbs(
                    "1.2",
                    parent="1",
                    name="后续",
                    start="2025-02-01T08:00:00",
                    finish="2025-03-01T17:00:00",
                    predecessors=["1.1"],
                ),
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert any(
        item["level"] == "warning"
        and item["rule_id"] == "wbs.predecessor_overlap"
        and item["field_name"] == "planned_start_at"
        and "搭接施工" in str(item["suggestion"])
        for item in issues
    )


def test_placeholder_wbs_name_is_preserved_but_warned() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "wbs": [
                _wbs(
                    "1",
                    parent=None,
                    name="项目",
                    start="2025-01-01T08:00:00",
                    finish="2025-12-31T17:00:00",
                ),
                _wbs(
                    "1.1",
                    parent="1",
                    name="任务名称",
                    start="2025-01-01T08:00:00",
                    finish="2025-01-02T17:00:00",
                ),
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert any(
        item["level"] == "warning"
        and item["rule_id"] == "wbs.placeholder_name"
        and item["field_name"] == "name"
        and item["target_record_id"] == 3002
        for item in issues
    )


def test_username_suggestion_uses_name_pinyin_and_avoids_collisions() -> None:
    unavailable = {"zhanghuaide", "zhanghuaide2"}

    username = suggest_unique_username(
        "张怀德",
        "310108198611171091",
        unavailable,
    )

    assert username == "zhanghuaide3"


def test_same_person_with_multiple_positions_reuses_one_account() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "personnel": [
                {
                    "serial_no": 1,
                    "real_name": "马泽坤",
                    "identity_card_no": "320922199610153614",
                    "position_name": "项目商务副经理",
                    "certificate_no": "CERT-1",
                    "responsibility_description": "负责商务管理",
                },
                {
                    "serial_no": 2,
                    "real_name": "马泽坤",
                    "identity_card_no": "320922199610153614",
                    "position_name": "劳务员",
                    "certificate_no": "CERT-2",
                    "responsibility_description": "负责劳务管理",
                },
            ],
        },
    )

    issues = validate_initialization_payload(payload)
    personnel_issues = [item for item in issues if item["section"] == "personnel"]

    assert any(
        item["level"] == "warning"
        and "共用同一个平台账号" in str(item["suggestion"])
        for item in personnel_issues
    )
    assert not any(item["level"] == "error" for item in personnel_issues)


def test_same_person_cannot_repeat_the_same_position() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "personnel": [
                {
                    "serial_no": 1,
                    "real_name": "马泽坤",
                    "identity_card_no": "320922199610153614",
                    "position_name": "项目商务副经理",
                    "certificate_no": "CERT-1",
                    "responsibility_description": "负责商务管理",
                },
                {
                    "serial_no": 2,
                    "real_name": "马泽坤",
                    "identity_card_no": "320922199610153614",
                    "position_name": "项目商务副经理",
                    "certificate_no": "CERT-2",
                    "responsibility_description": "负责成本管理",
                },
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert any(
        item["level"] == "error"
        and "岗位「项目商务副经理」重复" in item["message"]
        for item in issues
    )
