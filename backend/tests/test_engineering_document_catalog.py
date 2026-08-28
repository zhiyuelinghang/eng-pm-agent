from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import Base
from backend.app.engineering_document_catalog import (
    authorized_qa_payload,
    catalogue_node_key,
    compare_document_catalogue,
    local_folder_tree_view,
    local_knowledge_page,
    local_workspace_view,
    permission_configuration_view,
    set_catalogue_access_mode,
    sync_document_catalogue,
    update_local_folder_path,
    upsert_catalogue_permission,
)
from backend.app.models import (
    EngineeringDocumentNode,
    EngineeringDocumentPermission,
    EngineeringDocumentSyncState,
    Project,
    ProjectMember,
    ProjectMemberPosition,
    ProjectPosition,
    User,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


class FakeWeKnoraClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_weknora_knowledge_bases(self, agent_id: str) -> dict:
        self.calls.append(("bases", agent_id))
        return {
            "knowledge_bases": [
                {
                    "id": "kb-1",
                    "name": "项目资料库",
                    "description": "项目工程资料",
                    "created_at": "2026-08-26T08:00:00+08:00",
                },
            ],
            "total": 1,
        }

    def get_weknora_folder_tree(self, agent_id: str, knowledge_base_id: str) -> dict:
        self.calls.append(("folders", agent_id, knowledge_base_id))
        return {
            "root_document_count": 1,
            "total_document_count": 3,
            "folders": [
                {
                    "path": "技术资料",
                    "name": "技术资料",
                    "document_count": 1,
                    "total_count": 2,
                    "children": [
                        {
                            "path": "技术资料/图纸",
                            "name": "图纸",
                            "document_count": 1,
                            "total_count": 1,
                        },
                    ],
                },
            ],
        }

    def list_weknora_knowledge(
        self,
        agent_id: str,
        knowledge_base_id: str,
        **kwargs,
    ) -> dict:
        self.calls.append(("knowledge", agent_id, knowledge_base_id, kwargs))
        return {
            "knowledge": [
                {
                    "id": "doc-root",
                    "knowledge_base_id": knowledge_base_id,
                    "title": "项目说明.txt",
                    "file_name": "项目说明.txt",
                    "folder_path": "",
                    "file_type": "txt",
                    "file_size": 100,
                    "parse_status": "completed",
                },
                {
                    "id": "doc-tech",
                    "knowledge_base_id": knowledge_base_id,
                    "title": "施工方案.pdf",
                    "file_name": "施工方案.pdf",
                    "folder_path": "技术资料",
                    "description": "施工组织与技术措施摘要",
                    "file_type": "pdf",
                    "file_size": 200,
                    "parse_status": "completed",
                },
                {
                    "id": "doc-drawing",
                    "knowledge_base_id": knowledge_base_id,
                    "title": "总平面图.dwg",
                    "file_name": "总平面图.dwg",
                    "folder_path": "技术资料/图纸",
                    "file_type": "dwg",
                    "file_size": 300,
                    "parse_status": "completed",
                },
            ],
            "total": 3,
            "page": kwargs.get("page", 1),
            "page_size": kwargs.get("page_size", 100),
        }


class MultiBaseFakeWeKnoraClient(FakeWeKnoraClient):
    def list_weknora_knowledge_bases(self, agent_id: str) -> dict:
        self.calls.append(("bases", agent_id))
        return {
            "knowledge_bases": [
                {"id": "kb-1", "name": "项目资料库"},
                {"id": "kb-2", "name": "企业标准库"},
                {"id": "kb-3", "name": "历史归档库"},
            ],
            "total": 3,
        }


def _project_user(db: Session) -> tuple[Project, User, ProjectMember]:
    project = Project(name="目录镜像测试项目")
    user = User(
        username="catalog-member",
        password_hash="not-visible",
        role="user",
        real_name="资料成员",
        identity_card_no="CATALOG-USER-1",
    )
    db.add_all([project, user])
    db.flush()
    member = ProjectMember(project_id=project.id, user_id=user.id)
    db.add(member)
    db.commit()
    return project, user, member


def test_sync_builds_local_catalogue_and_normal_reads_do_not_call_remote(
    db: Session,
) -> None:
    project, user, _ = _project_user(db)
    client = FakeWeKnoraClient()

    result = sync_document_catalogue(
        db,
        project.id,
        "robot-1",
        client,
    )

    assert result["status"] == "ready"
    assert result["knowledge_base_count"] == 1
    assert result["folder_count"] == 2
    assert result["file_count"] == 3
    assert db.get(EngineeringDocumentSyncState, project.id).revision == 1

    call_count = len(client.calls)
    workspace = local_workspace_view(db, project.id, user)
    tree = local_folder_tree_view(db, project.id, "kb-1", user)
    page = local_knowledge_page(
        db,
        project.id,
        "kb-1",
        user,
        page=1,
        page_size=20,
        folder_path="技术资料",
        folder_recursive=True,
        keyword="",
    )
    direct_page = local_knowledge_page(
        db,
        project.id,
        "kb-1",
        user,
        page=1,
        page_size=20,
        folder_path="技术资料",
        folder_recursive=False,
        keyword="",
    )

    assert workspace["knowledge_bases"][0]["name"] == "项目资料库"
    assert tree["root_document_count"] == 1
    assert tree["total_document_count"] == 3
    assert tree["folders"][0]["children"][0]["path"] == "技术资料/图纸"
    assert {row["id"] for row in page["knowledge"]} == {
        "doc-tech",
        "doc-drawing",
    }
    assert [row["id"] for row in direct_page["knowledge"]] == ["doc-tech"]
    assert direct_page["knowledge"][0]["file_size"] == 200
    assert direct_page["knowledge"][0]["description"] == "施工组织与技术措施摘要"
    assert len(client.calls) == call_count


def test_sync_mirrors_every_selected_knowledge_base_and_no_others(
    db: Session,
) -> None:
    project, _, _ = _project_user(db)
    client = MultiBaseFakeWeKnoraClient()

    result = sync_document_catalogue(
        db,
        project.id,
        "robot-1",
        client,
        knowledge_base_ids=["kb-1", "kb-3", "kb-1"],
    )

    assert result["knowledge_base_ids"] == ["kb-1", "kb-3"]
    assert result["knowledge_base_count"] == 2
    mirrored = set(
        db.scalars(
            select(EngineeringDocumentNode.knowledge_base_id).where(
                EngineeringDocumentNode.project_id == project.id,
                EngineeringDocumentNode.node_type == "knowledge_base",
            ),
        ).all(),
    )
    assert mirrored == {"kb-1", "kb-3"}
    assert ("folders", "robot-1", "kb-2") not in client.calls

    updated = sync_document_catalogue(
        db,
        project.id,
        "robot-1",
        client,
        knowledge_base_ids=["kb-2", "kb-3"],
    )
    assert updated["knowledge_base_count"] == 2
    assert set(updated["knowledge_base_ids"]) == {"kb-2", "kb-3"}
    mirrored = set(
        db.scalars(
            select(EngineeringDocumentNode.knowledge_base_id).where(
                EngineeringDocumentNode.project_id == project.id,
                EngineeringDocumentNode.node_type == "knowledge_base",
            ),
        ).all(),
    )
    assert mirrored == {"kb-2", "kb-3"}


def test_sync_rejects_a_knowledge_base_outside_the_bound_robot(db: Session) -> None:
    project, _, _ = _project_user(db)
    with pytest.raises(ValueError, match="不属于当前项目绑定的机器人"):
        sync_document_catalogue(
            db,
            project.id,
            "robot-1",
            MultiBaseFakeWeKnoraClient(),
            knowledge_base_ids=["kb-missing"],
        )


def test_catalogue_diff_is_read_only_and_reports_local_drift(db: Session) -> None:
    project, _, _ = _project_user(db)
    client = FakeWeKnoraClient()
    sync_document_catalogue(db, project.id, "robot-1", client)

    matching = compare_document_catalogue(db, project.id, "robot-1", client)
    assert matching["matches"] is True
    assert matching["added_count"] == 0
    assert matching["changed_count"] == 0
    assert matching["removed_count"] == 0

    row = db.scalar(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project.id,
            EngineeringDocumentNode.external_id == "doc-tech",
        ),
    )
    assert row is not None
    row.name = "本地被改动的名称.pdf"
    db.commit()

    drift = compare_document_catalogue(db, project.id, "robot-1", client)
    assert drift["matches"] is False
    assert drift["changed_count"] == 1
    assert drift["changed"][0]["node_key"] == row.node_key
    assert "name" in drift["changed"][0]["changed_fields"]
    db.refresh(row)
    assert row.name == "本地被改动的名称.pdf"


def test_position_permission_is_inherited_and_qa_is_limited_to_readable_files(
    db: Session,
) -> None:
    project, user, member = _project_user(db)
    sync_document_catalogue(db, project.id, "robot-1", FakeWeKnoraClient())
    position = ProjectPosition(project_id=project.id, position_name="技术负责人")
    db.add(position)
    db.flush()
    db.add(
        ProjectMemberPosition(
            project_id=project.id,
            project_member_id=member.id,
            position_id=position.id,
            serial_no=1,
            certificate_no="POSITION-1",
            responsibility_description="负责技术资料",
        ),
    )
    folder = db.scalar(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project.id,
            EngineeringDocumentNode.node_key
            == catalogue_node_key("folder", "kb-1", "技术资料"),
        ),
    )
    assert folder is not None
    set_catalogue_access_mode(db, project.id, "restricted")
    upsert_catalogue_permission(
        db,
        project.id,
        node_id=folder.id,
        subject_type="position",
        subject_id=position.id,
        values={
            "can_read": True,
            "can_create": False,
            "can_update": False,
            "can_delete": False,
            "can_manage": False,
            "inherit_to_children": True,
        },
        granted_by_user_id=user.id,
    )
    db.commit()

    workspace = local_workspace_view(db, project.id, user)
    tree = local_folder_tree_view(db, project.id, "kb-1", user)
    qa_payload = authorized_qa_payload(
        db,
        project.id,
        user,
        {"query": "有哪些技术资料？", "knowledge_base_ids": ["kb-1"]},
    )

    assert workspace["total"] == 1  # root remains a navigation ancestor
    assert tree["root_document_count"] == 0
    assert tree["total_document_count"] == 2
    assert set(qa_payload["knowledge_ids"]) == {"doc-tech", "doc-drawing"}
    assert qa_payload["knowledge_base_ids"] == ["kb-1"]
    document_payload = authorized_qa_payload(
        db,
        project.id,
        user,
        {"query": "读取图纸", "knowledge_ids": ["doc-drawing"]},
    )
    assert document_payload["knowledge_base_ids"] == ["kb-1"]
    assert document_payload["knowledge_ids"] == ["doc-drawing"]
    with pytest.raises(Exception) as exc_info:
        authorized_qa_payload(
            db,
            project.id,
            user,
            {"query": "读取根文件", "knowledge_ids": ["doc-root"]},
        )
    assert getattr(exc_info.value, "status_code", None) == 403


def test_permission_configuration_exposes_project_positions_and_local_tree(
    db: Session,
) -> None:
    project, user, member = _project_user(db)
    sync_document_catalogue(db, project.id, "robot-1", FakeWeKnoraClient())
    position = ProjectPosition(project_id=project.id, position_name="资料员")
    db.add(position)
    db.flush()
    db.add(
        ProjectMemberPosition(
            project_id=project.id,
            project_member_id=member.id,
            position_id=position.id,
            serial_no=1,
            certificate_no="",
            responsibility_description="管理项目资料",
        ),
    )
    folder = db.scalar(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project.id,
            EngineeringDocumentNode.node_type == "folder",
        ),
    )
    assert folder is not None
    grant = upsert_catalogue_permission(
        db,
        project.id,
        node_id=folder.id,
        subject_type="position",
        subject_id=position.id,
        values={"can_read": True, "inherit_to_children": True},
        granted_by_user_id=user.id,
    )
    db.commit()

    configuration = permission_configuration_view(db, project.id)

    assert configuration["access_mode"] == "project"
    assert configuration["subjects"]["positions"] == [
        {"id": position.id, "name": "资料员"},
    ]
    assert any(node["id"] == folder.id for node in configuration["nodes"])
    assert configuration["permissions"] == [
        {
            "id": grant.id,
            "node_id": folder.id,
            "subject_type": "position",
            "subject_id": position.id,
            "can_read": True,
            "can_create": False,
            "can_update": False,
            "can_delete": False,
            "can_manage": False,
            "inherit_to_children": True,
        },
    ]

    summary = permission_configuration_view(
        db,
        project.id,
        include_nodes=False,
    )
    assert summary["nodes"] == []
    assert summary["subjects"] == configuration["subjects"]
    assert summary["permissions"] == configuration["permissions"]


def test_create_only_folder_remains_visible_for_navigation(db: Session) -> None:
    project, user, _ = _project_user(db)
    sync_document_catalogue(db, project.id, "robot-1", FakeWeKnoraClient())
    folder = db.scalar(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project.id,
            EngineeringDocumentNode.node_key
            == catalogue_node_key("folder", "kb-1", "技术资料"),
        ),
    )
    assert folder is not None
    set_catalogue_access_mode(db, project.id, "restricted")
    upsert_catalogue_permission(
        db,
        project.id,
        node_id=folder.id,
        subject_type="user",
        subject_id=user.id,
        values={
            "can_read": False,
            "can_create": True,
            "can_update": False,
            "can_delete": False,
            "can_manage": False,
            "inherit_to_children": False,
        },
        granted_by_user_id=user.id,
    )
    db.commit()

    workspace = local_workspace_view(db, project.id, user)
    tree = local_folder_tree_view(db, project.id, "kb-1", user)

    assert workspace["total"] == 1
    assert [item["path"] for item in tree["folders"]] == ["技术资料"]
    assert tree["folders"][0]["capabilities"]["can_create"] is True
    assert tree["folders"][0]["total_count"] == 0


def test_folder_rename_preserves_node_and_permission_identity(db: Session) -> None:
    project, user, _ = _project_user(db)
    sync_document_catalogue(db, project.id, "robot-1", FakeWeKnoraClient())
    folder = db.scalar(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.project_id == project.id,
            EngineeringDocumentNode.node_type == "folder",
            EngineeringDocumentNode.folder_path == "技术资料",
        ),
    )
    assert folder is not None
    permission = EngineeringDocumentPermission(
        project_id=project.id,
        node_id=folder.id,
        subject_type="user",
        subject_id=user.id,
        can_read=True,
        inherit_to_children=True,
        granted_by_user_id=user.id,
    )
    db.add(permission)
    db.commit()
    original_id = folder.id
    permission_id = permission.id

    updated = update_local_folder_path(
        db,
        project.id,
        "kb-1",
        "技术资料",
        "技术文件",
    )
    db.commit()

    assert updated.id == original_id
    assert updated.folder_path == "技术文件"
    assert db.get(EngineeringDocumentPermission, permission_id).node_id == original_id
    moved_file = db.scalar(
        select(EngineeringDocumentNode).where(
            EngineeringDocumentNode.external_id == "doc-drawing",
        ),
    )
    assert moved_file.folder_path == "技术文件/图纸"


def test_sync_failure_keeps_same_source_snapshot_but_clears_changed_source(
    db: Session,
) -> None:
    project, _, _ = _project_user(db)
    sync_document_catalogue(db, project.id, "robot-1", FakeWeKnoraClient())
    original_ids = set(
        db.scalars(
            select(EngineeringDocumentNode.id).where(
                EngineeringDocumentNode.project_id == project.id,
            ),
        ).all(),
    )

    class FailingClient:
        def list_weknora_knowledge_bases(self, _agent_id: str) -> dict:
            raise RuntimeError("source unavailable")

    with pytest.raises(RuntimeError, match="source unavailable"):
        sync_document_catalogue(db, project.id, "robot-1", FailingClient())
    assert set(
        db.scalars(
            select(EngineeringDocumentNode.id).where(
                EngineeringDocumentNode.project_id == project.id,
            ),
        ).all(),
    ) == original_ids
    assert db.get(EngineeringDocumentSyncState, project.id).status == "error"

    with pytest.raises(RuntimeError, match="source unavailable"):
        sync_document_catalogue(db, project.id, "robot-2", FailingClient())
    assert not db.scalars(
        select(EngineeringDocumentNode.id).where(
            EngineeringDocumentNode.project_id == project.id,
        ),
    ).first()
    changed_state = db.get(EngineeringDocumentSyncState, project.id)
    assert changed_state.status == "error"
    assert changed_state.weknora_agent_id == "robot-2"
