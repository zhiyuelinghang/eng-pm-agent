"""Exercise reviewed selections through validation, persistence and confirmation."""
from datetime import UTC, date, datetime, timedelta
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.initialization_change_contracts import ApplyInitializationChangesInput, PreviewInitializationChangesInput
from backend.app.initialization_change_models import AppliedInitializationChange, InitializationChangePreview
from backend.app.initialization_change_service import apply_change_preview, create_change_preview
from backend.app.initialization_changes import build_change_plan
from backend.app.models import ProjectInitializationDraftSection, QualityMetric, User
from backend.app.project_initialization import ApplyInitializationDraftInput, InitializationApplyError, apply_initialization_draft
from backend.tests.test_initialization_changes import db, _draft, _wbs, _risk  # noqa: F401

spec = importlib.util.spec_from_file_location("change_validator", Path(__file__).resolve().parents[2] / "mcp-packages/project-initialization-validator/initialization_validator.py")
validator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator_module)


class Validator:
    def get_initialization_validation_binding(self):
        return {"package_id": "project-initialization-validator", "package_version": "2.0.0"}

    def validate_project_initialization(self, payload):
        return {"package_id": "project-initialization-validator", "package_version": "2.0.0", "duration_ms": 1,
                "result": validator_module.validate_project_initialization(payload)}


def preview(db, draft, user, **kwargs):
    return create_change_preview(db, draft, user, PreviewInitializationChangesInput(**kwargs), client=Validator())


def apply(db, draft, user, review, **kwargs):
    client = kwargs.pop("client", None) or Validator()
    result = apply_change_preview(db, draft, user, ApplyInitializationChangesInput(preview_id=review["preview_id"], **kwargs), client=client)
    db.commit()
    return result


def test_independent_project_fields_can_be_confirmed_in_two_batches(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新建设单位", "engineering_type_description": "新工程"}})
    keys = [row["key"] for row in build_change_plan(db, draft)["changes"]]
    first = preview(db, draft, user, selected_keys=keys[:1])
    assert first["can_apply"] and first["issues"] == []
    saved = apply(db, draft, user, first)
    assert saved["status"] == "partially_applied" and saved["remaining"] == 1
    assert draft.status == "ready"
    second = preview(db, draft, user)
    assert second["summary"]["applied"] == 1 and second["summary"]["selected"] == 1
    final = apply(db, draft, user, second)
    assert final["status"] == "applied" and draft.applied_at is not None
    assert project.construction_unit_name == "新建设单位" and project.engineering_type_description == "新工程"
    assert len(list(db.scalars(select(AppliedInitializationChange)))) == 2


def test_unselected_incomplete_record_does_not_gate_valid_field(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}, "personnel": [{"identity_card_no": "NEW", "position_name": "安全员"}]})
    key = next(row["key"] for row in build_change_plan(db, draft)["changes"] if row["section"] == "project")
    selected = preview(db, draft, user, selected_keys=[key])
    assert selected["can_apply"]
    apply(db, draft, user, selected)
    assert project.construction_unit_name == "新单位"
    remainder = preview(db, draft, user)
    # The platform cannot add a required-field rule absent from the active MCP.
    assert remainder["can_apply"] is True
    assert not any(issue["rule_id"].startswith("platform.") for issue in remainder["issues"])


def test_first_initialization_adds_empty_project_fields_without_old_data(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "建设单位", "contract_duration_days": 0}})
    project.engineering_type_description = None
    project.construction_unit_name = None
    review = preview(db, draft, user)
    assert review["mode"] == "initialization"
    assert review["summary"]["update"] == 0
    assert all(row["operation"] == "add" and row["before"] is None for row in review["changes"])
    key = next(row["key"] for row in review["changes"] if "construction_unit_name" in row["key"])
    apply(db, draft, user, preview(db, draft, user, selected_keys=[key]))
    assert project.construction_unit_name == "建设单位"
    assert preview(db, draft, user)["mode"] == "update"


def test_invalid_fields_do_not_skip_mcp_checks_of_other_records(db):
    _project, user, draft = _draft(db, {
        "wbs": [{"wbs_code": "1", "name": "任务名称", "level": 1}],
        "quality_requirements": [{"wbs_code": "1"}],
    })
    review = preview(db, draft, user)
    assert review["can_apply"]
    assert review["validation"]["package_version"] == "2.0.0"
    assert not any(issue["rule_id"].endswith("invalid_record") for issue in review["issues"])
    assert any(issue["rule_id"] == "wbs.placeholder_name" for issue in review["issues"])
    assert not any("Input should" in issue["message"] for issue in review["issues"])
    identities = [(issue["rule_id"], issue.get("change_key"), issue.get("field_name"), issue["message"]) for issue in review["issues"]]
    assert len(identities) == len(set(identities))


def test_quality_only_import_validates_against_existing_wbs(db):
    project, user, draft = _draft(db, {"quality_requirements": [{"wbs_code": "1", "quality_acceptance_item": "混凝土验收", "control_indicator": "C35", "inspection_frequency": "每批", "related_documents": "试验报告"}]})
    wbs = _wbs(db, project)
    review = preview(db, draft, user)
    assert review["can_apply"], review
    apply(db, draft, user, review, allow_warnings=True)
    assert db.scalar(select(QualityMetric)).wbs_code == wbs.wbs_code


def test_missing_wbs_dependency_blocks_selected_quality(db):
    project, user, draft = _draft(db, {"quality_requirements": [{"wbs_code": "1", "quality_acceptance_item": "验收", "control_indicator": "C35", "inspection_frequency": "每批", "related_documents": "报告"}]})
    review = preview(db, draft, user)
    assert not review["can_apply"]
    assert any(issue["rule_id"].endswith("missing_wbs") for issue in review["issues"])


def test_contract_start_change_is_checked_against_existing_end(db):
    project, user, draft = _draft(db, {"project": {"contract_start_date": "2027-01-01"}})
    project.contract_end_date = date(2026, 12, 31)
    review = preview(db, draft, user)
    assert not review["can_apply"]
    assert any(issue["rule_id"].endswith("contract_date_order") for issue in review["issues"])


def test_duplicate_identity_is_a_mcp_issue_and_other_data_can_still_be_submitted(db):
    project, user, draft = _draft(db, {
        "project": {"construction_unit_name": "新单位"},
        "risks": [{"related_process_name": "土方开挖", "risk_part": "基坑边坡", "risk_level": "中"}],
    })
    first, second = _risk(db, project), _risk(db, project, serial_no=2)
    checked = preview(db, draft, user)
    assert not checked["can_apply"] and checked["operation_issues"] == []
    assert any(issue["rule_id"] == "matching.duplicate_identity" for issue in checked["issues"])
    key = next(row["key"] for row in checked["changes"] if row["section"] == "project")
    checked = preview(db, draft, user, selected_keys=[key])
    assert checked["can_apply"]
    apply(db, draft, user, checked)
    assert first.risk_level == second.risk_level == "高"


def test_draft_card_counts_only_remaining_material_and_retains_audit_rows(db):
    from backend.app.initialization_draft_view import build_initialization_draft_review
    _, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位", "engineering_type_description": "新工程"}})
    checked = preview(db, draft, user)
    first = preview(db, draft, user, selected_keys=checked["selected_keys"][:1])
    apply(db, draft, user, first)
    remaining = build_initialization_draft_review(db, draft)
    assert remaining["pending_change_count"] == remaining["summary"]["project_fields"] == 1
    apply(db, draft, user, preview(db, draft, user))
    finished = build_initialization_draft_review(db, draft)
    assert finished["status"] == "applied" and finished["pending_change_count"] == 0
    assert all(count == 0 for count in finished["summary"].values())
    assert len(list(db.scalars(select(AppliedInitializationChange)))) == 2


@pytest.mark.parametrize("kind", ["formal", "draft", "expired"])
def test_stale_review_is_rejected_without_writing(db, kind):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    review = preview(db, draft, user)
    if kind == "formal":
        project.engineering_type_description = "其他人已修改"
    elif kind == "draft":
        draft.revision += 1
    else:
        db.get(InitializationChangePreview, review["preview_id"]).created_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    with pytest.raises(InitializationApplyError):
        apply(db, draft, user, review)
    db.rollback()
    assert project.construction_unit_name == "原建设单位"
    assert db.scalar(select(AppliedInitializationChange)) is None


def test_preview_is_bound_to_reviewing_user(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    review = preview(db, draft, user)
    other = User(username="other-admin", password_hash="test", identity_card_no="OTHER", real_name="另一管理员", role="admin")
    db.add(other)
    db.commit()
    with pytest.raises(InitializationApplyError):
        apply(db, draft, other, review)
    assert project.construction_unit_name == "原建设单位"


def test_repeated_confirmation_returns_same_saved_result(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    review = preview(db, draft, user)
    first = apply(db, draft, user, review)
    second = apply(db, draft, user, review)
    assert first == second
    assert len(list(db.scalars(select(AppliedInitializationChange)))) == 1


def test_validator_failure_preserves_diff_and_disables_apply(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    class FailedValidator:
        def validate_project_initialization(self, payload):
            raise RuntimeError("核验服务不可用")
    review = create_change_preview(db, draft, user, PreviewInitializationChangesInput(), client=FailedValidator())
    assert review["changes"] and not review["can_apply"]
    assert review["validation"]["status"] == "failed"
    with pytest.raises(InitializationApplyError):
        apply(db, draft, user, review)


def test_legacy_confirmation_cannot_bypass_difference_review(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    with pytest.raises(InitializationApplyError, match="差异确认"):
        apply_initialization_draft(db, draft, ApplyInitializationDraftInput(allow_partial=True))
    assert project.construction_unit_name == "原建设单位"


def test_draft_can_be_partly_applied_while_other_specialist_is_running(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    draft.status = "building"
    review = preview(db, draft, user)
    assert review["can_apply"]
    saved = apply(db, draft, user, review)
    assert saved["status"] == "partially_applied" and draft.status == "building"
    db.add(ProjectInitializationDraftSection(draft_id=draft.id, project_id=project.id, conversation_id=draft.conversation_id, section="risks", writer_agent_id="risk", payload=[]))
    db.commit()


def test_preview_api_requires_login_and_rejects_cross_project_draft(db):
    from backend.app.api_common import get_current_user
    from backend.app.db import get_db
    from backend.app.initialization_changes_api import router
    from backend.app.models import Project
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    other = Project(name="另一个项目")
    db.add(other)
    db.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    # TestClient uses a different thread, so authentication and project guards
    # are invoked directly below while the no-credential HTTP path stays DB-free.
    with TestClient(app) as client:
        response = client.post(f"/api/projects/{project.id}/initialization-drafts/{draft.id}/change-preview", json={})
        assert response.status_code == 401
    from fastapi import HTTPException
    from backend.app.api_common import require_admin
    from backend.app.initialization_changes_api import _draft as resolve_draft
    user.role = "user"
    with pytest.raises(HTTPException) as denied:
        require_admin(user)
    assert denied.value.status_code == 403
    user.role = "admin"
    with pytest.raises(HTTPException) as wrong:
        resolve_draft(db, other.id, draft.id, user)
    assert wrong.value.status_code == 404


def test_project_member_can_view_diff_but_cannot_confirm(db, monkeypatch):
    from fastapi import HTTPException
    from backend.app.api_common import require_admin
    from backend.app import initialization_changes_api as api
    from backend.app.models import ProjectMember
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    user.role = "user"
    db.add(ProjectMember(project_id=project.id, user_id=user.id))
    db.commit()
    monkeypatch.setattr(api, "create_change_preview", lambda session, row, actor, request: create_change_preview(session, row, actor, request, client=Validator()))
    result = api.preview_project_changes(project.id, draft.id, PreviewInitializationChangesInput(), db, user)["data"]
    assert result["changes"] and result["can_apply"] is False
    with pytest.raises(HTTPException) as denied:
        require_admin(user)
    assert denied.value.status_code == 403
    db.query(ProjectMember).filter_by(project_id=project.id, user_id=user.id).delete()
    db.commit()
    with pytest.raises(HTTPException) as denied:
        api.preview_project_changes(project.id, draft.id, PreviewInitializationChangesInput(), db, user)
    assert denied.value.status_code == 403


def test_latest_draft_can_be_scoped_to_selected_conversation(db):
    from backend.app.api import get_latest_project_initialization_draft
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    db.commit()
    found = get_latest_project_initialization_draft(project.id, db, user, draft.conversation_id)
    assert found["data"]["id"] == draft.id
    missing = get_latest_project_initialization_draft(project.id, db, user, draft.conversation_id + 1)
    assert missing["data"] is None
