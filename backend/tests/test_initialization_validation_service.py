from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.agentscope_client import AgentScopeGatewayError
from backend.app.db import Base
from backend.app.initialization_validation import (
    InitializationValidationError,
    run_project_initialization_validation,
)
from backend.app.initialization_draft_queries import (
    latest_initialization_validation_issues,
)
from backend.app.models import (
    AgentConversation,
    Project,
    ProjectInitializationDraft,
    ProjectInitializationDraftSection,
    ProjectInitializationValidationIssue,
    ProjectInitializationValidationRun,
    User,
)


class _SuccessfulValidator:
    def validate_project_initialization(self, payload):
        assert payload["project"]["engineering_type_description"] == "测试工程"
        record_id = payload["project"]["record_id"]
        assert isinstance(record_id, int)
        return {
            "package_id": "project-initialization-validator",
            "package_version": "1.2.0",
            "duration_ms": 37,
            "result": {
                "ruleset_version": "rules-12",
                "status": "ready",
                "validation_issues": [
                    {
                        "rule_id": "project.missing_fields",
                        "level": "warning",
                        "section": "project",
                        "target_record_id": record_id,
                        "field_name": "construction_unit_name",
                        "label": "信息缺失",
                        "title": "建设单位未识别",
                        "message": "仍有字段待用户确认",
                        "suggestion": "请对照原始附件核对。",
                        "related_record_ids": [],
                        "details": {"field_name": "construction_unit_name"},
                    },
                ],
            },
        }


class _FailedValidator:
    def validate_project_initialization(self, _payload):
        raise AgentScopeGatewayError("MCP 未启动", status_code=503)


class _RevisionChangingValidator(_SuccessfulValidator):
    def __init__(self, db: Session, draft_id: int):
        self.db = db
        self.draft_id = draft_id

    def validate_project_initialization(self, payload):
        result = super().validate_project_initialization(payload)
        self.db.execute(
            update(ProjectInitializationDraft)
            .where(ProjectInitializationDraft.id == self.draft_id)
            .values(
                revision=ProjectInitializationDraft.revision + 1,
                status="building",
            ),
        )
        self.db.commit()
        return result


def _draft(db: Session) -> ProjectInitializationDraft:
    project = Project(name="待初始化项目")
    user = User(
        username="validator-admin",
        real_name="核验管理员",
        identity_card_no="VALIDATOR_ADMIN",
        password_hash="test",
        role="admin",
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
        agentscope_session_id="validator-session",
    )
    db.add(conversation)
    db.flush()
    draft = ProjectInitializationDraft(
        project_id=project.id,
        conversation_id=conversation.id,
        created_by_user_id=user.id,
        status="building",
        payload={},
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
    db.commit()
    db.refresh(draft)
    return draft


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_direct_mcp_validation_persists_version_result_and_duration() -> None:
    with _session() as db:
        draft = _draft(db)

        result = run_project_initialization_validation(
            db,
            draft,
            client=_SuccessfulValidator(),
        )

        assert result["status"] == "ready"
        assert draft.status == "ready"
        assert draft.validation_issues[0]["rule_id"] == "project.missing_fields"
        run = db.scalar(select(ProjectInitializationValidationRun))
        assert run is not None
        assert run.status == "completed"
        assert run.package_version == "1.2.0"
        assert run.ruleset_version == "rules-12"
        assert run.duration_ms == 37
        issue = db.scalar(select(ProjectInitializationValidationIssue))
        assert issue is not None
        assert issue.target_record_id == draft.payload["project"]["record_id"]
        assert issue.field_name == "construction_unit_name"


def test_failed_mcp_validation_is_recorded_without_faking_draft_completion() -> None:
    with _session() as db:
        draft = _draft(db)

        try:
            run_project_initialization_validation(
                db,
                draft,
                client=_FailedValidator(),
            )
        except InitializationValidationError as exc:
            assert "MCP 未启动" in str(exc)
        else:
            raise AssertionError("核验服务失败时必须抛出异常")

        db.refresh(draft)
        assert draft.status == "building"
        run = db.scalar(select(ProjectInitializationValidationRun))
        assert run is not None
        assert run.status == "failed"
        assert "MCP 未启动" in str(run.error)


def test_failed_latest_run_does_not_expose_stale_issue_annotations() -> None:
    with _session() as db:
        draft = _draft(db)
        run_project_initialization_validation(
            db,
            draft,
            client=_SuccessfulValidator(),
        )
        assert latest_initialization_validation_issues(db, draft.id)

        try:
            run_project_initialization_validation(
                db,
                draft,
                client=_FailedValidator(),
            )
        except InitializationValidationError:
            pass
        else:
            raise AssertionError("核验服务失败时必须抛出异常")

        assert latest_initialization_validation_issues(db, draft.id) == []


def test_validation_result_is_discarded_when_draft_changes_during_run() -> None:
    with _session() as db:
        draft = _draft(db)

        try:
            run_project_initialization_validation(
                db,
                draft,
                client=_RevisionChangingValidator(db, draft.id),
            )
        except InitializationValidationError as exc:
            assert "核验期间已更新" in str(exc)
        else:
            raise AssertionError("过期核验结果不能写回新草稿版本")

        db.refresh(draft)
        run = db.scalar(select(ProjectInitializationValidationRun))
        assert draft.status == "building"
        assert run is not None
        assert run.status == "failed"
        assert db.scalar(select(ProjectInitializationValidationIssue)) is None
