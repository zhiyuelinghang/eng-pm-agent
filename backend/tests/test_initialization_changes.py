"""Integration checks for reviewed imports against an isolated SQLite database."""
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.initialization_change_models import AppliedInitializationChange
from backend.app.initialization_changes import apply_change_plan, build_change_plan
from backend.app.models import (
    AgentConversation, EngineeringDocumentNode, EngineeringDocumentPermission, EngineeringDocumentSyncState,
    Project, ProjectInitializationDraft, ProjectInitializationDraftSection,
    ProjectMember, ProjectMemberPosition, ProjectPosition, QualityMetric,
    RiskSource, Task, User, WbsItem, WbsPredecessor, WbsRiskLink,
)
from backend.app.project_initialization import InitializationApplyError


@pytest.fixture
def db():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _draft(db, sections):
    project = Project(name="分批导入项目", engineering_type_description="原工程",
                      construction_unit_name="原建设单位")
    user = User(username="admin", password_hash="existing-password", role="admin",
                real_name="管理员", identity_card_no="ADMIN-CARD")
    db.add_all([project, user])
    db.flush()
    conversation = AgentConversation(project_id=project.id, user_id=user.id,
                                     agent_id="initializer", agent_name="资料助手",
                                     conversation_type="initialization", title="资料更新",
                                     agentscope_session_id="changes-test")
    db.add(conversation)
    db.flush()
    draft = ProjectInitializationDraft(project_id=project.id, conversation_id=conversation.id,
                                       created_by_user_id=user.id, status="ready", payload={})
    db.add(draft)
    db.flush()
    for section, payload in sections.items():
        db.add(ProjectInitializationDraftSection(
            draft_id=draft.id, project_id=project.id, conversation_id=conversation.id,
            section=section, writer_agent_id="specialist", payload=payload,
        ))
    db.flush()
    return project, user, draft


def _wbs(db, project, **values):
    row = WbsItem(project_id=project.id, wbs_code="1", name="原工序", level=1,
                  sort_order=9, progress_percent=35, duration_hours=80,
                  planned_start_at=datetime(2026, 1, 1), status_text="施工中",
                  raw_data={"kept": True}, **values)
    db.add(row)
    db.flush()
    return row


def _risk(db, project, **values):
    data = dict(serial_no=1, related_process_name="土方开挖", risk_part="基坑边坡",
                risk_level="高", evaluation_condition="深基坑", status="active",
                material_requirements=["专项方案"])
    data.update(values)
    row = RiskSource(project_id=project.id, **data)
    db.add(row)
    db.flush()
    return row


def _person(**values):
    data = dict(serial_no=1, real_name="张三", identity_card_no="PERSON-CARD",
                position_name="安全员", certificate_no="CERT", responsibility_description="现场安全")
    data.update(values)
    return data


def test_single_project_field_can_apply_while_other_draft_row_is_incomplete(db):
    project, _user, draft = _draft(db, {
        "project": {"construction_unit_name": "新建设单位", "engineering_type_description": None},
        "personnel": [{"real_name": "待补充人员"}],
    })
    preview = build_change_plan(db, draft)
    project_change = next(change for change in preview["changes"] if change["section"] == "project")
    plan = build_change_plan(db, draft, [project_change["key"]])
    assert plan["issues"] == []
    result = apply_change_plan(db, draft, plan, [])
    assert result["applied_keys"] == [project_change["key"]]
    assert project.construction_unit_name == "新建设单位"
    assert project.engineering_type_description == "原工程"
    assert len(list(db.scalars(select(AppliedInitializationChange)))) == 1
    remaining = build_change_plan(db, draft)
    assert next(change for change in remaining["changes"] if change["key"] == project_change["key"])["operation"] == "applied"


def test_wbs_patch_keeps_live_id_runtime_fields_tasks_and_risk_links(db):
    project, user, draft = _draft(db, {"wbs": [{"wbs_code": "1", "name": "调整后工序"}]})
    wbs = _wbs(db, project, responsible_user_id=user.id)
    risk = _risk(db, project)
    link = WbsRiskLink(project_id=project.id, wbs_item_id=wbs.id, risk_source_id=risk.id,
                       notify_methods=["in_app"])
    task = Task(project_id=project.id, title="在办任务", task_type="risk", wbs_item_id=wbs.id,
                risk_source_id=risk.id)
    db.add_all([link, task])
    db.flush()
    old_id = wbs.id
    plan = build_change_plan(db, draft)
    assert plan["issues"] == []
    assert plan["changes"][0]["fields"] == [{"name": "name", "before": "原工序", "after": "调整后工序"}]
    apply_change_plan(db, draft, plan, [])
    db.flush()
    db.expire_all()
    saved = db.get(WbsItem, old_id)
    assert saved.name == "调整后工序"
    assert saved.progress_percent == 35 and saved.duration_hours == 80 and saved.sort_order == 9
    assert saved.responsible_user_id == user.id and saved.raw_data == {"kept": True}
    assert task.wbs_item_id == old_id and link.wbs_item_id == old_id
    assert db.get(RiskSource, risk.id).material_requirements == ["专项方案"]


def test_quality_add_can_reference_formal_wbs_without_wbs_in_upload(db):
    project, _user, draft = _draft(db, {"quality_requirements": [{
        "wbs_code": "1", "quality_acceptance_item": "钢筋验收", "control_indicator": "间距合格",
        "inspection_frequency": "每批", "related_documents": "验收记录",
    }]})
    wbs = _wbs(db, project)
    plan = build_change_plan(db, draft)
    assert plan["issues"] == []
    assert len(plan["effective_payload"]["wbs"]) == 1
    existing_map = plan["record_targets"][str(plan["effective_payload"]["wbs"][0]["record_id"])]
    assert existing_map["is_existing"] and existing_map["target_id"] == wbs.id
    apply_change_plan(db, draft, plan, [])
    assert db.scalar(select(QualityMetric)).wbs_code == "1"


def test_risk_serial_does_not_silently_match_unrelated_old_risk(db):
    project, _user, draft = _draft(db, {"risks": [{
        "serial_no": 1, "related_process_name": "模板施工", "risk_part": "高支模",
        "risk_level": "高", "evaluation_condition": "高度超限",
    }]})
    old = _risk(db, project)
    plan = build_change_plan(db, draft)
    change = plan["changes"][0]
    assert change["operation"] == "add" and change["candidates"] == []
    assert plan["selected_keys"] == [change["key"]]
    assert plan["issues"] == []
    assert plan["changes"][0]["after"]["serial_no"] == 1
    assert [row["serial_no"] for row in plan["effective_payload"]["risks"]] == [1, 1]
    assert len(list(db.scalars(select(RiskSource)))) == 1
    assert db.get(RiskSource, old.id).risk_part == "基坑边坡"


def test_same_wbs_name_with_different_code_is_new_without_manual_matching(db):
    project, _user, draft = _draft(db, {"wbs": [{"wbs_code": "2", "name": "原工序", "level": 1}]})
    old = _wbs(db, project)
    plan = build_change_plan(db, draft)
    change = plan["changes"][0]
    assert change["operation"] == "add" and change["target_id"] is None and not change["candidates"]
    assert old.wbs_code == "1"


def test_risk_natural_match_updates_and_keeps_operational_fields(db):
    project, user, draft = _draft(db, {"risks": [{
        "related_process_name": "土方开挖", "risk_part": "基坑边坡", "risk_level": "中",
    }]})
    risk = _risk(db, project, responsible_user_id=user.id, confirmer_user_id=user.id)
    plan = build_change_plan(db, draft)
    assert plan["changes"][0]["target_id"] == risk.id
    apply_change_plan(db, draft, plan, [])
    assert risk.risk_level == "中" and risk.evaluation_condition == "深基坑"
    assert risk.material_requirements == ["专项方案"] and risk.responsible_user_id == user.id


def test_new_personnel_credentials_and_partial_second_submission_are_independent(db):
    project, _user, draft = _draft(db, {
        "project": {"construction_unit_name": "新单位"},
        "personnel": [_person()],
    })
    initial = build_change_plan(db, draft)
    project_key = next(change["key"] for change in initial["changes"] if change["section"] == "project")
    personnel_key = next(change["key"] for change in initial["changes"] if change["section"] == "personnel")
    project_plan = build_change_plan(db, draft, [project_key])
    assert project_plan["required_personnel_credentials"] == []
    apply_change_plan(db, draft, project_plan, [])
    personnel_plan = build_change_plan(db, draft, [personnel_key])
    assert personnel_plan["required_personnel_credentials"][0]["identity_card_no"] == "PERSON-CARD"
    with pytest.raises(InitializationApplyError, match="缺少登录账号"):
        apply_change_plan(db, draft, personnel_plan, [])
    apply_change_plan(db, draft, personnel_plan, [{
        "identity_card_no": "PERSON-CARD", "username": "zhangsan", "initial_password": "safe-password",
    }])
    assignment = db.scalar(select(ProjectMemberPosition))
    assert assignment.serial_no == 1
    assert len(list(db.scalars(select(AppliedInitializationChange)))) == 2
    assert all(change["operation"] == "applied" for change in build_change_plan(db, draft)["changes"])


def test_existing_personnel_assignment_preserves_password_position_and_permissions(db):
    project, user, draft = _draft(db, {"personnel": [_person(
        identity_card_no="ADMIN-CARD", real_name="管理员", position_name="项目经理",
        responsibility_description="更新职责",
    )]})
    member = ProjectMember(project_id=project.id, user_id=user.id)
    position = ProjectPosition(project_id=project.id, position_name="项目经理")
    db.add_all([member, position])
    db.flush()
    assignment = ProjectMemberPosition(project_id=project.id, project_member_id=member.id,
                                       position_id=position.id, serial_no=1, certificate_no="CERT",
                                       responsibility_description="原职责")
    db.add(assignment)
    db.flush()
    node = EngineeringDocumentNode(project_id=project.id, node_type="knowledge_base",
                                   node_key="custom-grant", knowledge_base_id="private-base", name="专项资料")
    db.add(node)
    db.flush()
    permission = EngineeringDocumentPermission(project_id=project.id, node_id=node.id,
                                                subject_type="position", subject_id=position.id,
                                                can_read=True, can_update=True)
    db.add(permission)
    db.flush()
    plan = build_change_plan(db, draft)
    assert not plan["required_personnel_credentials"]
    original_id, original_position_id = assignment.id, position.id
    apply_change_plan(db, draft, plan, [])
    assert assignment.id == original_id and assignment.position_id == original_position_id
    assert assignment.responsibility_description == "更新职责"
    assert user.password_hash == "existing-password" and user.username == "admin"
    assert db.get(EngineeringDocumentPermission, permission.id).can_update
    assert permission.subject_id == original_position_id


def test_changed_formal_runtime_value_invalidates_review(db):
    project, _user, draft = _draft(db, {"wbs": [{"wbs_code": "1", "name": "新工序"}]})
    wbs = _wbs(db, project)
    plan = build_change_plan(db, draft)
    wbs.raw_data = {"concurrent_change": True}
    db.flush()
    with pytest.raises(InitializationApplyError, match="正式数据已更新"):
        apply_change_plan(db, draft, plan, [])
    assert wbs.name == "原工序"


def test_incomplete_selected_new_record_is_preserved_for_mcp_validation(db):
    _project, _user, draft = _draft(db, {"personnel": [{"real_name": "仅姓名"}]})
    plan = build_change_plan(db, draft)
    assert plan["issues"] == []
    assert len(plan["effective_payload"]["personnel"]) == 1
    assert plan["effective_payload"]["personnel"][0]["identity_card_no"] is None
    assert plan["effective_payload"]["personnel"][0]["real_name"] == "仅姓名"


def test_existing_legacy_empty_fields_do_not_block_unrelated_new_project_field(db):
    project, _user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    _risk(db, project, evaluation_condition="")
    plan = build_change_plan(db, draft)
    assert plan["issues"] == []
    assert plan["effective_payload"]["risks"][0]["evaluation_condition"] == ""
    apply_change_plan(db, draft, plan, [])
    assert project.construction_unit_name == "新单位"


def test_multiple_proposals_targeting_one_formal_row_require_user_selection(db):
    project, _user, draft = _draft(db, {"wbs": [
        {"wbs_code": "1", "name": "候选甲"}, {"wbs_code": "1", "name": "候选乙"},
    ]})
    _wbs(db, project)
    plan = build_change_plan(db, draft)
    assert plan["issues"] == []
    mapping = next(value for value in plan["record_targets"].values() if value["section"] == "wbs")
    assert [item["values"]["name"] for item in mapping["observations"]] == ["候选甲", "候选乙"]
    selected = build_change_plan(db, draft, [plan["changes"][0]["key"]])
    assert selected["issues"] == []
    apply_change_plan(db, draft, selected, [])
    assert db.scalar(select(WbsItem)).name == "候选甲"


def test_effective_ids_never_overlap_imported_draft_record_ids(db):
    project, _user, draft = _draft(db, {
        "project": {"construction_unit_name": "新单位", "design_unit_name": "设计院"},
        "risks": [{"serial_no": 2, "related_process_name": "施工", "risk_part": "部位",
                   "risk_level": "低", "evaluation_condition": "一般"}],
    })
    _wbs(db, project)
    plan = build_change_plan(db, draft)
    draft_ids = {change["record_id"] for change in plan["changes"]}
    assert not draft_ids.intersection(map(int, plan["record_targets"]))
    project_map = plan["record_targets"][str(plan["effective_payload"]["project"]["record_id"])]
    assert len(project_map["change_keys"]) == 2
    assert set(project_map["field_changes"]) == {"construction_unit_name", "design_unit_name"}


def test_new_parent_and_child_are_both_created_before_parent_links(db):
    project, _user, draft = _draft(db, {"wbs": [
        {"wbs_code": "1.1", "name": "子工序", "parent_wbs_code": "1", "level": 2},
        {"wbs_code": "1", "name": "父工序", "level": 1},
    ]})
    plan = build_change_plan(db, draft)
    assert plan["issues"] == []
    apply_change_plan(db, draft, plan, [])
    rows = {row.wbs_code: row for row in db.scalars(select(WbsItem))}
    assert rows["1.1"].parent_id == rows["1"].id


def test_one_new_account_can_receive_two_positions_with_distinct_serials(db):
    _project, _user, draft = _draft(db, {"personnel": [
        _person(position_name="安全员"), _person(serial_no=2, position_name="质量员"),
    ]})
    plan = build_change_plan(db, draft)
    assert len(plan["required_personnel_credentials"]) == 1
    assert {change["after"]["serial_no"] for change in plan["changes"]} == {1, 2}
    apply_change_plan(db, draft, plan, [{
        "identity_card_no": "PERSON-CARD", "username": "zhangsan", "initial_password": "safe-password",
    }])
    assert len(list(db.scalars(select(ProjectMemberPosition)))) == 2
    assert len(list(db.scalars(select(User).where(User.identity_card_no == "PERSON-CARD")))) == 1


def test_numerically_equivalent_import_is_unchanged(db):
    project, _user, draft = _draft(db, {"wbs": [{"wbs_code": "1", "progress_percent": "35.00"}]})
    _wbs(db, project)
    plan = build_change_plan(db, draft)
    assert plan["changes"][0]["operation"] == "unchanged"
    assert plan["selected_keys"] == []


def test_baseline_hash_survives_numeric_column_reload(db):
    project, _user, draft = _draft(db, {"wbs": [{"wbs_code": "1", "name": "新名称"}]})
    _wbs(db, project)
    before = build_change_plan(db, draft)
    db.expire_all()
    after = build_change_plan(db, draft)
    assert before["baseline_hash"] == after["baseline_hash"]
    assert before["changes"][0]["before"] == after["changes"][0]["before"]
    assert before["changes"][0]["after"] == after["changes"][0]["after"]


def test_name_update_does_not_recreate_unreviewed_predecessor_relation(db):
    project, _user, draft = _draft(db, {"wbs": [{"wbs_code": "1", "name": "新名称"}]})
    row = _wbs(db, project)
    predecessor = WbsItem(project_id=project.id, wbs_code="2", name="前任", level=1)
    db.add(predecessor)
    db.flush()
    relation = WbsPredecessor(wbs_item_id=row.id, predecessor_wbs_item_id=predecessor.id)
    db.add(relation)
    db.flush()
    relation_id = relation.id
    plan = build_change_plan(db, draft)
    assert [field["name"] for field in plan["changes"][0]["fields"]] == ["name"]
    apply_change_plan(db, draft, plan, [])
    assert db.get(WbsPredecessor, relation_id).predecessor_wbs_item_id == predecessor.id


def test_predecessor_change_invalidates_project_only_review(db):
    project, _user, draft = _draft(db, {"project": {"design_unit_name": "设计院"}})
    row = _wbs(db, project)
    predecessor = WbsItem(project_id=project.id, wbs_code="2", name="前任", level=1)
    db.add(predecessor)
    db.flush()
    plan = build_change_plan(db, draft)
    db.add(WbsPredecessor(wbs_item_id=row.id, predecessor_wbs_item_id=predecessor.id))
    db.flush()
    with pytest.raises(InitializationApplyError, match="正式数据已更新"):
        apply_change_plan(db, draft, plan, [])


@pytest.mark.parametrize("existing_mode,expected_mode", [(None, "restricted"), ("project", "project"), ("restricted", "restricted")])
def test_personnel_import_initializes_missing_permission_mode_and_preserves_existing(db, existing_mode, expected_mode):
    project, _user, draft = _draft(db, {"personnel": [_person()]})
    if existing_mode is not None:
        db.add(EngineeringDocumentSyncState(project_id=project.id, access_mode=existing_mode))
        db.flush()
    plan = build_change_plan(db, draft)
    apply_change_plan(db, draft, plan, [{
        "identity_card_no": "PERSON-CARD", "username": "zhangsan", "initial_password": "safe-password",
    }])
    assert db.get(EngineeringDocumentSyncState, project.id).access_mode == expected_mode


def test_existing_account_is_a_fact_for_mcp_without_replacing_uploaded_name(db):
    project, user, draft = _draft(db, {"personnel": [_person(
        identity_card_no="ADMIN-CARD", real_name="上传中的不同姓名",
    )]})
    other_project = Project(name="账号已经参与的其他项目")
    db.add(other_project)
    db.flush()
    db.add(ProjectMember(project_id=other_project.id, user_id=user.id))
    db.flush()
    plan = build_change_plan(db, draft)
    assert plan["required_personnel_credentials"] == []
    assert plan["issues"] == []
    assert plan["changes"][0]["after"]["real_name"] == "上传中的不同姓名"
    assert next(field for field in plan["changes"][0]["fields"] if field["name"] == "real_name")["after"] == "上传中的不同姓名"
    mapping = next(value for value in plan["record_targets"].values() if value["section"] == "personnel")
    assert mapping["existing_account"] == {"real_name": "管理员"}
    assert not mapping["updates_existing_identity"]
    assert user.real_name == "管理员" and user.password_hash == "existing-password"


def test_review_shows_existing_personnel_username_without_secrets_or_unrelated_accounts(db, monkeypatch):
    from backend.app.initialization_change_contracts import PreviewInitializationChangesInput
    from backend.app.initialization_change_models import InitializationChangePreview
    from backend.app.initialization_change_service import create_change_preview

    _project, user, draft = _draft(db, {"personnel": [
        _person(identity_card_no="ADMIN-CARD", real_name="管理员"),
        _person(serial_no=2),
    ]})
    db.add(User(username="unrelated-account", password_hash="unrelated-secret", role="admin",
                real_name="无关人员", identity_card_no="OTHER-CARD"))
    db.flush()
    monkeypatch.setattr("backend.app.initialization_change_service.validate_change_plan",
                        lambda plan, client=None: ([], {"status": "completed"}))
    # Account identification remains visible even when this row is not selected.
    review = create_change_preview(db, draft, user, PreviewInitializationChangesInput(selected_keys=[]))
    assert review["existing_personnel_accounts"] == [{
        "identity_card_no": "ADMIN-CARD", "username": "admin", "real_name": "管理员",
    }]
    persisted = db.get(InitializationChangePreview, review["preview_id"])
    assert persisted.review["existing_personnel_accounts"] == review["existing_personnel_accounts"]
    assert "existing-password" not in str(review)
    assert "password_hash" not in str(review)
    assert "unrelated-account" not in str(review) and "OTHER-CARD" not in str(review)
