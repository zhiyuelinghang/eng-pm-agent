from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.engineering_document_catalog import (
    reconcile_name_based_catalogue_permissions,
    sync_document_catalogue,
)
from backend.app.initialization_integrity import validate_initialization_integrity
from backend.app.models import (
    AgentConversation,
    EngineeringDocumentNode,
    EngineeringDocumentPermission,
    EngineeringDocumentSyncState,
    Project,
    ProjectInitializationDraft,
    ProjectInitializationDraftSection,
    ProjectInitializationValidationRun,
    ProjectMember,
    ProjectMemberPosition,
    ProjectPosition,
    User,
)
from backend.app.personnel_policy import (
    PROJECT_POSITION_NAMES,
    reconcile_user_management_role,
)
from backend.app.project_initialization import (
    ApplyInitializationDraftInput,
    PersonnelCredentialInput,
    ProjectInitializationPayload,
    apply_initialization_draft,
)


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _user(username: str, card: str, *, role: str = "user") -> User:
    return User(
        username=username,
        password_hash="test",
        role=role,
        real_name=username,
        identity_card_no=card,
    )


def _assign(
    db: Session,
    project: Project,
    user: User,
    position_name: str,
    serial_no: int,
) -> ProjectPosition:
    member = ProjectMember(project_id=project.id, user_id=user.id)
    position = ProjectPosition(
        project_id=project.id,
        position_name=position_name,
    )
    db.add_all([member, position])
    db.flush()
    db.add(
        ProjectMemberPosition(
            project_id=project.id,
            project_member_id=member.id,
            position_id=position.id,
            serial_no=serial_no,
            certificate_no="无",
            responsibility_description="测试职责",
        ),
    )
    db.flush()
    return position


def test_unknown_initialization_position_is_a_targeted_error() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "personnel": [
                {
                    "record_id": 7,
                    "serial_no": 1,
                    "real_name": "测试人员",
                    "identity_card_no": "CARD-UNKNOWN",
                    "position_name": "技术负责人",
                    "certificate_no": "无",
                    "responsibility_description": "技术工作",
                },
            ],
        },
    )

    issues = validate_initialization_integrity(payload)

    issue = next(
        item
        for item in issues
        if item["rule_id"] == "platform.integrity.personnel.unsupported_position"
    )
    assert issue["target_record_id"] == 7
    assert issue["field_name"] == "position_name"
    assert "技术负责人" in issue["message"]
    assert all(name in issue["message"] for name in PROJECT_POSITION_NAMES)


def test_account_role_is_derived_from_admin_username_or_project_manager() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="岗位角色测试")
        initial_admin = _user("admin", "SYSTEM-ADMIN", role="user")
        manager = _user("manager", "CARD-PM")
        ordinary = _user("ordinary", "CARD-SAFETY", role="admin")
        db.add_all([project, initial_admin, manager, ordinary])
        db.flush()
        _assign(db, project, manager, "项目经理", 1)
        _assign(db, project, ordinary, "安全员", 2)

        assert reconcile_user_management_role(db, initial_admin) == "admin"
        assert reconcile_user_management_role(db, manager) == "admin"
        assert reconcile_user_management_role(db, ordinary) == "user"


def test_name_based_catalogue_policy_assigns_default_and_manager_access() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="知识库权限测试")
        manager = _user("manager", "POLICY-PM")
        safety = _user("safety", "POLICY-SAFETY")
        db.add_all([project, manager, safety])
        db.flush()
        manager_position = _assign(db, project, manager, "项目经理", 1)
        safety_position = _assign(db, project, safety, "安全员", 2)
        common_root = EngineeringDocumentNode(
            project_id=project.id,
            node_type="knowledge_base",
            node_key="common-v1",
            knowledge_base_id="mutable-common-id-v1",
            external_id="mutable-common-id-v1",
            name="B_工程知识库",
            folder_path="",
        )
        private_root = EngineeringDocumentNode(
            project_id=project.id,
            node_type="knowledge_base",
            node_key="private-v1",
            knowledge_base_id="mutable-private-id-v1",
            external_id="mutable-private-id-v1",
            name="项目专属资料库",
            folder_path="",
        )
        db.add_all([common_root, private_root])
        db.flush()

        result = reconcile_name_based_catalogue_permissions(
            db,
            project.id,
            enable_restricted=True,
        )

        state = db.get(EngineeringDocumentSyncState, project.id)
        assert state is not None and state.access_mode == "restricted"
        assert result["default_knowledge_base_found"] is True
        grants = list(
            db.scalars(
                select(EngineeringDocumentPermission).where(
                    EngineeringDocumentPermission.project_id == project.id,
                ),
            ).all(),
        )
        by_target = {
            (grant.node_id, grant.subject_id): grant for grant in grants
        }
        safety_default = by_target[(common_root.id, safety_position.id)]
        assert safety_default.can_read is True
        assert safety_default.can_manage is False
        assert (private_root.id, safety_position.id) not in by_target
        for root in (common_root, private_root):
            manager_grant = by_target[(root.id, manager_position.id)]
            assert manager_grant.can_read is True
            assert manager_grant.can_manage is True


class _MutableKnowledgeBaseClient:
    def __init__(self, knowledge_base_id: str) -> None:
        self.knowledge_base_id = knowledge_base_id

    def list_weknora_knowledge_bases(self, _agent_id: str) -> dict:
        return {
            "knowledge_bases": [
                {
                    "id": self.knowledge_base_id,
                    "name": "B_工程知识库",
                },
            ],
        }

    def get_weknora_folder_tree(
        self,
        _agent_id: str,
        _knowledge_base_id: str,
    ) -> dict:
        return {"folders": [], "root_document_count": 0, "total_document_count": 0}

    def list_weknora_knowledge(
        self,
        _agent_id: str,
        _knowledge_base_id: str,
        **_kwargs,
    ) -> dict:
        return {"knowledge": [], "total": 0}


def test_catalogue_sync_rebinds_default_permission_when_remote_id_changes() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="知识库换 ID 测试")
        safety = _user("safety-rebind", "POLICY-REBIND")
        db.add_all([project, safety])
        db.flush()
        safety_position = _assign(db, project, safety, "安全员", 1)
        reconcile_name_based_catalogue_permissions(
            db,
            project.id,
            enable_restricted=True,
        )
        client = _MutableKnowledgeBaseClient("kb-old-id")

        sync_document_catalogue(db, project.id, "agent-1", client)
        old_root = db.scalar(
            select(EngineeringDocumentNode).where(
                EngineeringDocumentNode.knowledge_base_id == "kb-old-id",
            ),
        )
        assert old_root is not None
        assert db.scalar(
            select(EngineeringDocumentPermission).where(
                EngineeringDocumentPermission.node_id == old_root.id,
                EngineeringDocumentPermission.subject_id == safety_position.id,
            ),
        ) is not None

        client.knowledge_base_id = "kb-new-id"
        result = sync_document_catalogue(db, project.id, "agent-1", client)

        assert db.scalar(
            select(EngineeringDocumentNode).where(
                EngineeringDocumentNode.knowledge_base_id == "kb-old-id",
            ),
        ) is None
        new_root = db.scalar(
            select(EngineeringDocumentNode).where(
                EngineeringDocumentNode.knowledge_base_id == "kb-new-id",
            ),
        )
        assert new_root is not None
        rebound = db.scalar(
            select(EngineeringDocumentPermission).where(
                EngineeringDocumentPermission.node_id == new_root.id,
                EngineeringDocumentPermission.subject_id == safety_position.id,
            ),
        )
        assert rebound is not None and rebound.can_read is True
        assert result["permission_policy"]["default_knowledge_base_found"] is True


def test_initialization_derives_roles_and_applies_name_based_permissions() -> None:
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        project = Project(name="初始化权限测试")
        creator = _user("admin", "INIT-CREATOR", role="admin")
        db.add_all([project, creator])
        db.flush()
        conversation = AgentConversation(
            project_id=project.id,
            user_id=creator.id,
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
            created_by_user_id=creator.id,
            status="ready",
            payload={},
        )
        db.add(draft)
        db.flush()
        db.add(
            ProjectInitializationDraftSection(
                draft_id=draft.id,
                project_id=project.id,
                conversation_id=conversation.id,
                section="personnel",
                writer_agent_id="personnel-specialist",
                payload=[
                    {
                        "serial_no": 1,
                        "real_name": "项目经理甲",
                        "identity_card_no": "INIT-PM",
                        "position_name": "项目经理",
                        "certificate_no": "PM-1",
                        "responsibility_description": "总体管理",
                    },
                    {
                        "serial_no": 2,
                        "real_name": "安全员乙",
                        "identity_card_no": "INIT-SAFETY",
                        "position_name": "安全员",
                        "certificate_no": "SAFE-1",
                        "responsibility_description": "安全管理",
                    },
                ],
                source_files=["人员名单.xlsx"],
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
                ruleset_version="test",
                validation_issues=[],
                duration_ms=1,
            ),
        )
        db.add(
            EngineeringDocumentNode(
                project_id=project.id,
                node_type="knowledge_base",
                node_key="default-knowledge-root",
                knowledge_base_id="replaceable-kb-id",
                external_id="replaceable-kb-id",
                name="B_工程知识库",
                folder_path="",
            ),
        )
        db.flush()

        from backend.app.initialization_change_contracts import PreviewInitializationChangesInput
        from backend.app.initialization_change_service import create_change_preview

        class Validator:
            def validate_project_initialization(self, payload):
                return {"package_id": "project-initialization-validator", "package_version": "2.0.0", "duration_ms": 1,
                        "result": {"status": "ready", "validation_issues": []}}

        preview = create_change_preview(db, draft, creator, PreviewInitializationChangesInput(), client=Validator())
        result = apply_initialization_draft(
            db,
            draft,
            ApplyInitializationDraftInput(
                preview_id=preview["preview_id"],
                personnel_credentials=[
                    PersonnelCredentialInput(
                        identity_card_no="INIT-PM",
                        username="init-pm",
                        initial_password="Password123",
                    ),
                    PersonnelCredentialInput(
                        identity_card_no="INIT-SAFETY",
                        username="init-safety",
                        initial_password="Password123",
                    ),
                ],
            ),
        )

        manager = db.scalar(select(User).where(User.username == "init-pm"))
        safety = db.scalar(select(User).where(User.username == "init-safety"))
        assert manager is not None and manager.role == "admin"
        assert safety is not None and safety.role == "user"
        assert result["permission_policy"]["default_knowledge_base_found"] is True
        assert result["permission_policy"]["grant_count"] == 2
        state = db.get(EngineeringDocumentSyncState, project.id)
        assert state is not None and state.access_mode == "restricted"
