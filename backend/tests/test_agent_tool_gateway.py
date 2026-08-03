from pathlib import Path

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agent_tool_gateway import (
    execute_tool_operation,
    get_initialization_file_content,
    resolve_tool_context,
)
from backend.app.db import Base
from backend.app.models import (
    AgentConversation,
    OperationLog,
    Project,
    ProjectInitializationArtifact,
    ProjectInitializationDraft,
    ProjectInitializationDraftSection,
    ProjectInitializationFile,
    ProjectMember,
    ProjectMemberPosition,
    ProjectPosition,
    Task,
    User,
    WbsItem,
)
from backend.app.project_initialization import (
    ApplyInitializationDraftInput,
    PersonnelCredentialInput,
    ProjectInitializationPayload,
    apply_initialization_draft,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    with session_factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _seed_context(
    db: Session,
    *,
    role: str = "user",
    conversation_type: str = "general",
    session_id: str = "session-1",
) -> tuple[User, Project, AgentConversation]:
    user = User(
        username=f"user-{session_id}",
        password_hash="unused",
        real_name="测试用户",
        identity_card_no=f"CARD-{session_id}",
        role=role,
    )
    project = Project(name=f"项目-{session_id}")
    db.add_all([user, project])
    db.flush()
    member = ProjectMember(project_id=project.id, user_id=user.id)
    position = ProjectPosition(
        project_id=project.id,
        position_name="项目经理",
    )
    db.add_all([member, position])
    db.flush()
    db.add(
        ProjectMemberPosition(
            project_id=project.id,
            project_member_id=member.id,
            position_id=position.id,
            serial_no=1,
            certificate_no=f"CERT-{session_id}",
            responsibility_description="负责项目管理",
        ),
    )
    conversation = AgentConversation(
        project_id=project.id,
        user_id=user.id,
        agent_id="agent-main",
        agent_name="Dobby 智能体",
        conversation_type=conversation_type,
        title="平台会话",
        agentscope_session_id=session_id,
        status="active",
    )
    db.add(conversation)
    db.commit()
    return user, project, conversation


def _initialization_payload() -> dict:
    return {
        "project": {
            "engineering_type_description": "社区卫生服务中心扩建工程",
            "construction_unit_name": "建设单位",
        },
        "personnel": [
            {
                "serial_no": 1,
                "real_name": "张项目",
                "identity_card_no": "310000000000000001",
                "position_name": "项目经理",
                "certificate_no": "CERT-001",
                "responsibility_description": "负责项目统筹",
            },
        ],
        "wbs": [
            {
                "wbs_code": "1",
                "parent_wbs_code": None,
                "name": "施工阶段",
                "planned_start_at": "2026-07-01T08:00:00",
                "planned_finish_at": "2026-07-31T17:00:00",
                "progress_percent": 0,
                "status_text": None,
                "priority_text": None,
                "level": 1,
                "sort_order": 1,
            },
            {
                "wbs_code": "1.1",
                "parent_wbs_code": "1",
                "name": "基础施工",
                "planned_start_at": "2026-07-01T08:00:00",
                "planned_finish_at": "2026-07-15T17:00:00",
                "progress_percent": 0,
                "status_text": "未开始",
                "priority_text": "中",
                "level": 2,
                "sort_order": 1,
            },
        ],
        "risks": [
            {
                "serial_no": 1,
                "related_process_name": "基础施工",
                "risk_part": "基坑",
                "risk_level": "较大风险",
                "evaluation_condition": "深度达到风险清单条件",
            },
        ],
        "quality_requirements": [
            {
                "wbs_code": "1.1",
                "quality_acceptance_item": "基础验收",
                "control_indicator": "符合设计要求",
                "inspection_frequency": "每道工序",
                "related_documents": "验收记录",
            },
        ],
    }


def test_legacy_risk_wbs_relation_is_discarded() -> None:
    payload = _initialization_payload()
    payload["risks"][0]["related_wbs_code"] = "1.1"

    normalized = ProjectInitializationPayload.model_validate(payload).model_dump()

    assert "related_wbs_code" not in normalized["risks"][0]


def _create_finalized_initialization_draft(
    db: Session,
    context,
    payload: dict | None = None,
) -> ProjectInitializationDraft:
    data = payload or _initialization_payload()
    sections = [
        "project",
        "personnel",
        "wbs",
        "risks",
        "quality_requirements",
    ]
    normalization_id = _create_ready_initialization_normalization(
        db,
        context,
        data,
        sections,
    )
    started, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_draft",
        {
            "normalization_id": normalization_id,
            "expected_sections": sections,
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    draft_id = started["draft"]["id"]
    for section in sections:
        execute_tool_operation(
            db,
            context,
            "import_project_initialization_artifact",
            {
                "draft_id": draft_id,
                "normalization_id": normalization_id,
            },
            actor_agent_id=f"{section}-specialist",
            initialization_role=section,
        )
    execute_tool_operation(
        db,
        context,
        "finalize_project_initialization_draft",
        {
            "draft_id": draft_id,
            "semantic_issues": [],
        },
        actor_agent_id="validator",
        initialization_role="validator",
    )
    draft = db.get(ProjectInitializationDraft, draft_id)
    assert draft is not None
    return draft


def _create_ready_initialization_normalization(
    db: Session,
    context,
    payload: dict,
    sections: list[str],
) -> int:
    started, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_normalization",
        {"source_file_ids": []},
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    normalization_id = started["id"]
    for section in sections:
        value = payload[section]
        parts = (
            [value]
            if section == "project"
            else [
                value[:1],
                *[
                    value[index:index + 20]
                    for index in range(1, len(value), 20)
                ],
            ]
        )
        for part_index, part in enumerate(parts, start=1):
            execute_tool_operation(
                db,
                context,
                "write_project_initialization_artifact",
                {
                    "normalization_id": normalization_id,
                    "section": section,
                    "artifact_format": "json",
                    "part_index": part_index,
                    "file_name": f"{section}-{part_index}.json",
                    "json_data": part,
                    "source_file_ids": [],
                    "source_locations": [f"测试标准资料：{section}"],
                },
                actor_agent_id="initializer",
                initialization_role="orchestrator",
            )
    execute_tool_operation(
        db,
        context,
        "finalize_project_initialization_normalization",
        {
            "normalization_id": normalization_id,
            "expected_sections": sections,
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    return normalization_id


def test_read_operation_is_strictly_scoped_to_bound_project(db: Session) -> None:
    _, project, conversation = _seed_context(db)
    other = Project(name="无权项目")
    db.add(other)
    db.flush()
    db.add_all(
        [
            Task(
                project_id=project.id,
                title="当前项目任务",
                task_type="risk_alert",
                status="pending",
            ),
            Task(
                project_id=other.id,
                title="其他项目任务",
                task_type="risk_alert",
                status="pending",
            ),
        ],
    )
    db.commit()

    context = resolve_tool_context(db, conversation.agentscope_session_id)
    data, _ = execute_tool_operation(
        db,
        context,
        "list_project_items",
        {"resource": "tasks"},
    )

    assert [item["title"] for item in data] == ["当前项目任务"]


def test_removed_member_cannot_resolve_existing_session(db: Session) -> None:
    user, project, conversation = _seed_context(db)
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
        ),
    )
    assert membership is not None
    db.delete(membership)
    db.commit()

    with pytest.raises(HTTPException) as error:
        resolve_tool_context(db, conversation.agentscope_session_id)

    assert error.value.status_code == 403


def test_business_agent_session_cannot_write(db: Session) -> None:
    _, _, conversation = _seed_context(db, conversation_type="business")
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    with pytest.raises(HTTPException) as error:
        execute_tool_operation(
            db,
            context,
            "create_task",
            {"title": "不应创建"},
        )

    assert error.value.status_code == 403
    assert db.scalar(select(Task).where(Task.title == "不应创建")) is None


def test_cross_project_reference_is_hidden_and_rejected(db: Session) -> None:
    _, _, conversation = _seed_context(db)
    foreign_project = Project(name="其他项目")
    db.add(foreign_project)
    db.flush()
    foreign_wbs = WbsItem(
        project_id=foreign_project.id,
        wbs_code="OTHER-01",
        name="其他工序",
        level=1,
        sort_order=1,
    )
    db.add(foreign_wbs)
    db.commit()
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    with pytest.raises(HTTPException) as error:
        execute_tool_operation(
            db,
            context,
            "create_task",
            {"title": "越权引用", "wbs_item_id": foreign_wbs.id},
        )

    assert error.value.status_code == 404


def test_admin_main_can_update_new_wbs_fields_and_audit(db: Session) -> None:
    _, project, conversation = _seed_context(db, role="admin")
    wbs = WbsItem(
        project_id=project.id,
        wbs_code="WBS-01",
        name="基础施工",
        level=1,
        sort_order=1,
        progress_percent=10,
        status_text="in_progress",
    )
    db.add(wbs)
    db.commit()
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    result, _ = execute_tool_operation(
        db,
        context,
        "update_wbs_progress",
        {
            "wbs_item_id": wbs.id,
            "progress_percent": 35,
            "status_text": "delayed",
            "note": "根据今日核验结果",
        },
    )

    assert result["progress_percent"] == 35
    assert result["status_text"] == "delayed"
    log = db.scalar(
        select(OperationLog).where(
            OperationLog.target_type == "wbs",
            OperationLog.target_id == wbs.id,
        ),
    )
    assert log is not None
    assert "Dobby 智能体会话" in log.detail


def test_initialization_agent_can_only_maintain_draft(db: Session) -> None:
    _, project, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)

    draft = _create_finalized_initialization_draft(db, context)

    assert draft.status == "ready"
    assert len(draft.payload["wbs"]) == 2
    assert draft.payload["wbs"][0]["progress_percent"] == "0"
    assert draft.payload["wbs"][0]["parent_wbs_code"] is None
    assert db.get(Project, project.id).engineering_type_description is None
    with pytest.raises(HTTPException) as error:
        execute_tool_operation(
            db,
            context,
            "create_task",
            {"title": "初始化智能体不能直接写业务表"},
        )
    assert error.value.status_code == 403


def test_draft_cannot_start_before_standardization_is_ready(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="normalization-required",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    normalization, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_normalization",
        {"source_file_ids": []},
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )

    with pytest.raises(HTTPException) as not_ready:
        execute_tool_operation(
            db,
            context,
            "begin_project_initialization_draft",
            {
                "normalization_id": normalization["id"],
                "expected_sections": ["wbs"],
            },
            actor_agent_id="initializer",
            initialization_role="orchestrator",
        )
    assert not_ready.value.status_code == 409
    assert "标准化" in not_ready.value.detail

    execute_tool_operation(
        db,
        context,
        "write_project_initialization_artifact",
        {
            "normalization_id": normalization["id"],
            "section": "wbs",
            "artifact_format": "markdown",
            "part_index": 1,
            "file_name": "wbs.md",
            "markdown_content": "# WBS 说明\n只有说明，尚无规范数据。",
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    with pytest.raises(HTTPException) as markdown_only:
        execute_tool_operation(
            db,
            context,
            "finalize_project_initialization_normalization",
            {
                "normalization_id": normalization["id"],
                "expected_sections": ["wbs"],
            },
            actor_agent_id="initializer",
            initialization_role="orchestrator",
        )
    assert markdown_only.value.status_code == 422
    assert "只有 Markdown" in str(markdown_only.value.detail)


def test_standardized_json_parts_are_read_and_bulk_imported(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="artifact-parts",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    payload = _initialization_payload()
    normalization, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_normalization",
        {"source_file_ids": []},
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    normalization_id = normalization["id"]
    for index, item in enumerate(payload["wbs"], start=1):
        execute_tool_operation(
            db,
            context,
            "write_project_initialization_artifact",
            {
                "normalization_id": normalization_id,
                "section": "wbs",
                "artifact_format": "json",
                "part_index": index,
                "file_name": f"wbs-{index}.json",
                "json_data": [item],
                "source_locations": [f"计划表第 {index + 1} 行"],
            },
            actor_agent_id="initializer",
            initialization_role="orchestrator",
        )

    ready, _ = execute_tool_operation(
        db,
        context,
        "finalize_project_initialization_normalization",
        {
            "normalization_id": normalization_id,
            "expected_sections": ["wbs"],
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    assert ready["status"] == "ready"
    manifest, _ = execute_tool_operation(
        db,
        context,
        "read_project_initialization_artifact",
        {
            "normalization_id": normalization_id,
            "section": "wbs",
        },
        actor_agent_id="wbs-specialist",
        initialization_role="wbs",
    )
    assert [item["part_index"] for item in manifest["parts"]] == [1, 2]
    first_part, _ = execute_tool_operation(
        db,
        context,
        "read_project_initialization_artifact",
        {
            "normalization_id": normalization_id,
            "section": "wbs",
            "artifact_format": "json",
            "part_index": 1,
            "start": 1,
            "limit": 1,
        },
        actor_agent_id="wbs-specialist",
        initialization_role="wbs",
    )
    assert first_part["data"][0]["wbs_code"] == "1"

    started, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_draft",
        {
            "normalization_id": normalization_id,
            "expected_sections": ["wbs"],
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    imported, _ = execute_tool_operation(
        db,
        context,
        "import_project_initialization_artifact",
        {
            "normalization_id": normalization_id,
            "draft_id": started["draft"]["id"],
        },
        actor_agent_id="wbs-specialist",
        initialization_role="wbs",
    )
    assert imported["record_count"] == 2
    assert imported["workflow"]["completed_sections"] == ["wbs"]


def test_artifact_json_requires_one_record_probe_before_batches(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="artifact-probe",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    normalization, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_normalization",
        {"source_file_ids": []},
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    records = _initialization_payload()["wbs"]

    with pytest.raises(HTTPException) as bulk_first:
        execute_tool_operation(
            db,
            context,
            "write_project_initialization_artifact",
            {
                "normalization_id": normalization["id"],
                "section": "wbs",
                "artifact_format": "json",
                "part_index": 1,
                "file_name": "wbs-1.json",
                "json_data": records,
            },
            actor_agent_id="initializer",
            initialization_role="orchestrator",
        )
    assert bulk_first.value.status_code == 422
    assert "只提交 1 条" in str(bulk_first.value.detail)

    probe, _ = execute_tool_operation(
        db,
        context,
        "write_project_initialization_artifact",
        {
            "normalization_id": normalization["id"],
            "section": "wbs",
            "artifact_format": "json",
            "part_index": 1,
            "file_name": "wbs-1.json",
            "json_data": records[:1],
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    assert probe["write_stage"] == "probe_accepted"
    assert probe["record_count"] == 1
    assert probe["schema_validated"] is True
    assert probe["batch_limit"] == 20
    assert probe["next_part_index"] == 2


def test_artifact_batches_are_bounded_and_validation_errors_are_compact(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="artifact-bounds",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    normalization, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_normalization",
        {"source_file_ids": []},
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    bad_record = {
        "wbs_code": "1",
        "parent_code": None,
        "name": "错误字段试写",
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
        "progress_percent": 0,
        "status": None,
        "priority": None,
        "level": 1,
    }
    with pytest.raises(HTTPException) as invalid:
        execute_tool_operation(
            db,
            context,
            "write_project_initialization_artifact",
            {
                "normalization_id": normalization["id"],
                "section": "wbs",
                "artifact_format": "json",
                "part_index": 1,
                "file_name": "wbs-1.json",
                "json_data": [bad_record],
            },
            actor_agent_id="initializer",
            initialization_role="orchestrator",
        )
    detail = invalid.value.detail
    assert detail["error_count"] > 0
    assert len(detail["errors"]) <= 5
    assert detail["truncated"] is True
    assert "parent_wbs_code" in detail["expected_fields"]
    assert "planned_start_at" in detail["expected_fields"]
    assert "input" not in str(detail)
    assert len(str(detail)) < 4000

    valid_record = _initialization_payload()["wbs"][0]
    execute_tool_operation(
        db,
        context,
        "write_project_initialization_artifact",
        {
            "normalization_id": normalization["id"],
            "section": "wbs",
            "artifact_format": "json",
            "part_index": 1,
            "file_name": "wbs-1.json",
            "json_data": [valid_record],
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    oversized_batch = [
        {
            **valid_record,
            "wbs_code": f"1.{index}",
            "parent_wbs_code": "1",
            "level": 2,
        }
        for index in range(1, 22)
    ]
    with pytest.raises(HTTPException) as oversized:
        execute_tool_operation(
            db,
            context,
            "write_project_initialization_artifact",
            {
                "normalization_id": normalization["id"],
                "section": "wbs",
                "artifact_format": "json",
                "part_index": 2,
                "file_name": "wbs-2.json",
                "json_data": oversized_batch,
            },
            actor_agent_id="initializer",
            initialization_role="orchestrator",
        )
    assert oversized.value.status_code == 422
    assert "最多 20 条" in str(oversized.value.detail)


def test_json_and_markdown_artifacts_with_same_part_do_not_overwrite(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="artifact-formats",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    normalization, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_normalization",
        {"source_file_ids": []},
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    for artifact_format, content in (
        ("json", {"json_data": _initialization_payload()["project"]}),
        (
            "markdown",
            {"markdown_content": "# 工程信息来源\n来自工程描述第一段。"},
        ),
    ):
        execute_tool_operation(
            db,
            context,
            "write_project_initialization_artifact",
            {
                "normalization_id": normalization["id"],
                "section": "project",
                "artifact_format": artifact_format,
                "part_index": 1,
                "file_name": f"project.{ 'json' if artifact_format == 'json' else 'md'}",
                **content,
            },
            actor_agent_id="initializer",
            initialization_role="orchestrator",
        )

    rows = db.scalars(
        select(ProjectInitializationArtifact).where(
            ProjectInitializationArtifact.normalization_id
            == normalization["id"],
        ),
    ).all()
    assert {(row.artifact_format, row.part_index) for row in rows} == {
        ("json", 1),
        ("markdown", 1),
    }
    ready, _ = execute_tool_operation(
        db,
        context,
        "finalize_project_initialization_normalization",
        {
            "normalization_id": normalization["id"],
            "expected_sections": ["project"],
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    assert ready["status"] == "ready"


def test_new_workflow_run_preserves_unrequested_existing_sections(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    first = _create_finalized_initialization_draft(db, context)
    payload = _initialization_payload()
    payload["risks"] = [
        {
            "serial_no": 2,
            "related_process_name": "基础施工",
            "risk_part": "临边防护",
            "risk_level": "一般风险",
            "evaluation_condition": "临边防护缺失",
        },
    ]
    normalization_id = _create_ready_initialization_normalization(
        db,
        context,
        payload,
        ["risks"],
    )

    started, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_draft",
        {
            "normalization_id": normalization_id,
            "expected_sections": ["risks"],
            "source_files": ["工程风险清单.xlsx"],
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    wbs_page, _ = execute_tool_operation(
        db,
        context,
        "get_project_initialization_draft",
        {"section": "wbs", "start": 1, "limit": 1},
    )
    assert wbs_page["draft"]["id"] == first.id
    assert wbs_page["total"] == 2
    assert wbs_page["next_start"] == 2
    assert [item["wbs_code"] for item in wbs_page["data"]] == ["1"]

    written, _ = execute_tool_operation(
        db,
        context,
        "write_project_initialization_draft_section",
        {
            "draft_id": started["draft"]["id"],
            "source_files": ["工程风险清单.xlsx"],
            "data": [
                {
                    "serial_no": 2,
                    "related_process_name": "基础施工",
                    "risk_part": "临边防护",
                    "risk_level": "一般风险",
                    "evaluation_condition": "临边防护缺失",
                },
            ],
        },
        actor_agent_id="risk-specialist",
        initialization_role="risks",
    )
    assert written["workflow"]["stage"] == "reviewing"
    finalized, _ = execute_tool_operation(
        db,
        context,
        "finalize_project_initialization_draft",
        {
            "draft_id": first.id,
            "semantic_issues": [],
        },
        actor_agent_id="validator",
        initialization_role="validator",
    )
    assert finalized["summary"]["wbs"] == 2
    assert finalized["summary"]["risks"] == 1
    assert finalized["source_files"] == ["工程风险清单.xlsx"]

    draft = db.get(ProjectInitializationDraft, first.id)
    assert draft is not None
    assert len(draft.payload["wbs"]) == 2
    assert len(draft.payload["personnel"]) == 1
    assert draft.payload["project"]["engineering_type_description"] == (
        "社区卫生服务中心扩建工程"
    )
    assert draft.payload["risks"][0]["serial_no"] == 2
    assert len(draft.payload["quality_requirements"]) == 1


def test_specialists_write_independent_draft_sections_before_review(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="sectioned-draft",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    normalization_id = _create_ready_initialization_normalization(
        db,
        context,
        _initialization_payload(),
        ["project", "personnel"],
    )
    started, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_draft",
        {
            "normalization_id": normalization_id,
            "expected_sections": ["project", "personnel"],
            "source_files": ["工程描述.txt", "人员名单.xlsx"],
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )
    draft_id = started["draft"]["id"]
    assert started["workflow"]["pending_sections"] == [
        "project",
        "personnel",
    ]

    project_result, _ = execute_tool_operation(
        db,
        context,
        "write_project_initialization_draft_section",
        {
            "draft_id": draft_id,
            "data": {
                "engineering_type_description": "社区医院扩建工程",
                "construction_unit_name": "建设单位",
            },
            "source_files": ["工程描述.txt"],
            "extraction_notes": ["工程描述.txt 第 1 段"],
        },
        actor_agent_id="project-specialist",
        initialization_role="project",
    )
    assert project_result["workflow"]["completed_sections"] == ["project"]
    assert project_result["workflow"]["pending_sections"] == ["personnel"]

    with pytest.raises(HTTPException) as wrong_scope:
        execute_tool_operation(
            db,
            context,
            "write_project_initialization_draft_section",
            {
                "draft_id": draft_id,
                "data": [],
            },
            actor_agent_id="risk-specialist",
            initialization_role="risks",
        )
    assert wrong_scope.value.status_code == 409

    personnel_result, _ = execute_tool_operation(
        db,
        context,
        "write_project_initialization_draft_section",
        {
            "draft_id": draft_id,
            "data": _initialization_payload()["personnel"],
            "source_files": ["人员名单.xlsx"],
        },
        actor_agent_id="personnel-specialist",
        initialization_role="personnel",
    )
    assert personnel_result["workflow"]["stage"] == "reviewing"
    assert personnel_result["workflow"]["pending_sections"] == []

    rows = db.scalars(
        select(ProjectInitializationDraftSection)
        .where(ProjectInitializationDraftSection.draft_id == draft_id),
    ).all()
    assert {row.section for row in rows} == {"project", "personnel"}
    draft = db.get(ProjectInitializationDraft, draft_id)
    assert draft is not None
    # The parent snapshot is intentionally not rewritten by concurrent
    # specialists; it becomes authoritative only after independent review.
    assert draft.payload["personnel"] == []

    finalized, _ = execute_tool_operation(
        db,
        context,
        "finalize_project_initialization_draft",
        {
            "draft_id": draft_id,
            "semantic_issues": [
                {
                    "level": "warning",
                    "path": "project",
                    "message": "工程说明中的范围需要用户核对",
                },
            ],
            "review_summary": "两个分区已完成独立核验。",
        },
        actor_agent_id="validator",
        initialization_role="validator",
    )
    assert finalized["status"] == "ready"
    assert finalized["workflow"]["stage"] == "completed"
    assert finalized["payload"]["project"]["construction_unit_name"] == "建设单位"
    assert len(finalized["payload"]["personnel"]) == 1
    assert any(
        issue["message"] == "工程说明中的范围需要用户核对"
        for issue in finalized["validation_issues"]
    )


def test_validator_cannot_finalize_before_all_expected_sections(
    db: Session,
) -> None:
    _, _, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="incomplete-review",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    normalization_id = _create_ready_initialization_normalization(
        db,
        context,
        _initialization_payload(),
        ["wbs", "risks"],
    )
    started, _ = execute_tool_operation(
        db,
        context,
        "begin_project_initialization_draft",
        {
            "normalization_id": normalization_id,
            "expected_sections": ["wbs", "risks"],
        },
        actor_agent_id="initializer",
        initialization_role="orchestrator",
    )

    with pytest.raises(HTTPException) as incomplete:
        execute_tool_operation(
            db,
            context,
            "finalize_project_initialization_draft",
            {
                "draft_id": started["draft"]["id"],
                "semantic_issues": [],
            },
            actor_agent_id="validator",
            initialization_role="validator",
        )
    assert incomplete.value.status_code == 409
    assert "wbs" in incomplete.value.detail
    assert "risks" in incomplete.value.detail


def test_initialization_file_is_bound_to_its_agent_session(
    db: Session,
    tmp_path,
) -> None:
    user, project, conversation = _seed_context(
        db,
        conversation_type="initialization",
    )
    file_path = tmp_path / "人员名单.xlsx"
    file_path.write_bytes(b"raw-xlsx-content")
    row = ProjectInitializationFile(
        project_id=project.id,
        conversation_id=conversation.id,
        uploaded_by_user_id=user.id,
        file_name=file_path.name,
        storage_path=str(file_path),
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        file_size=file_path.stat().st_size,
        file_hash="hash-1",
    )
    db.add(row)
    db.commit()

    response = get_initialization_file_content(
        row.id,
        conversation.agentscope_session_id,
        db,
    )
    assert Path(response.path) == file_path
    assert response.headers["x-dobby-file-extension"] == ".xlsx"

    _, _, other_conversation = _seed_context(
        db,
        conversation_type="initialization",
        session_id="other-session",
    )
    with pytest.raises(HTTPException) as error:
        get_initialization_file_content(
            row.id,
            other_conversation.agentscope_session_id,
            db,
        )
    assert error.value.status_code == 404


def test_confirmed_draft_is_applied_in_one_transaction(db: Session) -> None:
    _, project, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    draft = _create_finalized_initialization_draft(db, context)

    applied = apply_initialization_draft(
        db,
        draft,
        ApplyInitializationDraftInput(
            allow_partial=True,
            personnel_credentials=[
                PersonnelCredentialInput(
                    identity_card_no="310000000000000001",
                    username="zhangxiangmu",
                    initial_password="TempPass123!",
                ),
            ],
        ),
    )
    db.commit()

    assert applied["counts"] == {
        "personnel": 1,
        "positions": 1,
        "position_assignments": 1,
        "wbs": 2,
        "risks": 1,
        "quality_requirements": 1,
    }
    assert db.get(Project, project.id).engineering_type_description == (
        "社区卫生服务中心扩建工程"
    )
    assert db.scalar(
        select(User).where(User.username == "zhangxiangmu"),
    ) is not None


def test_existing_platform_account_is_added_to_project_without_recreation(
    db: Session,
) -> None:
    _, project, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="reuse-account",
    )
    existing_user = User(
        username="existing-zhang",
        password_hash="keep-this-password",
        real_name="平台已有姓名",
        identity_card_no="310000000000000001",
        role="user",
    )
    db.add(existing_user)
    db.commit()
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    draft = _create_finalized_initialization_draft(db, context)

    applied = apply_initialization_draft(
        db,
        draft,
        ApplyInitializationDraftInput(
            allow_partial=True,
            personnel_credentials=[],
        ),
    )
    db.commit()

    db.refresh(existing_user)
    memberships = db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project.id),
    ).all()
    assert applied["created_usernames"] == []
    assert existing_user.password_hash == "keep-this-password"
    assert existing_user.real_name == "平台已有姓名"
    assert len(memberships) == 1
    assert memberships[0].user_id == existing_user.id


def test_one_project_member_can_hold_multiple_positions(
    db: Session,
) -> None:
    _, project, conversation = _seed_context(
        db,
        role="admin",
        conversation_type="initialization",
        session_id="multiple-positions",
    )
    payload = _initialization_payload()
    payload["personnel"].append(
        {
            "serial_no": 2,
            "real_name": "张项目",
            "identity_card_no": "310000000000000001",
            "position_name": "劳务员",
            "certificate_no": "CERT-002",
            "responsibility_description": "负责劳务管理",
        },
    )
    context = resolve_tool_context(db, conversation.agentscope_session_id)
    draft = _create_finalized_initialization_draft(db, context, payload)

    applied = apply_initialization_draft(
        db,
        draft,
        ApplyInitializationDraftInput(
            allow_partial=True,
            personnel_credentials=[
                PersonnelCredentialInput(
                    identity_card_no="310000000000000001",
                    username="zhangxiangmu",
                    initial_password="TempPass123!",
                ),
            ],
        ),
    )
    db.commit()

    members = db.scalars(
        select(ProjectMember).where(ProjectMember.project_id == project.id),
    ).all()
    positions = db.scalars(
        select(ProjectPosition).where(ProjectPosition.project_id == project.id),
    ).all()
    assignments = db.scalars(
        select(ProjectMemberPosition).where(
            ProjectMemberPosition.project_id == project.id,
        ),
    ).all()
    assert applied["counts"]["personnel"] == 1
    assert applied["counts"]["positions"] == 2
    assert applied["counts"]["position_assignments"] == 2
    assert len(members) == 1
    assert len(positions) == 2
    assert len(assignments) == 2
    assert {item.project_member_id for item in assignments} == {members[0].id}
