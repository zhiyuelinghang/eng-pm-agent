from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.agentscope_client import AgentScopeGatewayError
from backend.app.db import Base
from backend.app.initialization_validation import (
    InitializationValidationError,
    run_project_initialization_validation,
)
from backend.app.models import (
    AgentConversation,
    Project,
    ProjectInitializationDraft,
    ProjectInitializationDraftSection,
    ProjectInitializationValidationRun,
    User,
)


class _SuccessfulValidator:
    def validate_project_initialization(self, payload):
        assert payload["project"]["engineering_type_description"] == "测试工程"
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
                        "path": "project",
                        "message": "仍有字段待用户确认",
                    },
                ],
            },
        }


class _FailedValidator:
    def validate_project_initialization(self, _payload):
        raise AgentScopeGatewayError("MCP 未启动", status_code=503)


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
