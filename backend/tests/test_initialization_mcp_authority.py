"""Only the selected MCP owns material verdicts; completed results are durable."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from backend.app.initialization_change_contracts import PreviewInitializationChangesInput
from backend.app.initialization_change_models import InitializationChangePreview
from backend.app.initialization_change_service import create_change_preview
from backend.app.initialization_incremental_validation import run_incremental_validation
from backend.app.models import QualityMetric
from backend.tests.test_initialization_changes import db, _draft, _wbs  # noqa: F401
from backend.tests.test_initialization_change_service import Validator, apply, validator_module


class CountingValidator(Validator):
    def __init__(self):
        self.calls = 0
        self.version = "2.0.0"
        self.reject_blank = False

    def get_initialization_validation_binding(self):
        return {"package_id": "project-initialization-validator", "package_version": self.version}

    def validate_project_initialization(self, payload):
        self.calls += 1
        response = super().validate_project_initialization(payload)
        response["package_version"] = self.version
        if self.reject_blank:
            item = payload["quality_requirements"][0]
            response["result"]["validation_issues"].append({
                "rule_id": "quality.custom_required", "level": "error", "section": "quality_requirements",
                "target_record_id": item["record_id"], "field_name": "control_indicator",
                "label": "需修正", "title": "MCP 自定义规则", "message": "本规则要求填写控制指标。",
            })
            response["result"]["status"] = "invalid"
        return response


def review(db, draft, user, validator, **kwargs):
    return create_change_preview(db, draft, user, PreviewInitializationChangesInput(**kwargs), client=validator)


def test_same_material_uses_persisted_snapshot_and_expired_ticket_does_not_rerun_mcp(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    validator = CountingValidator()
    first = review(db, draft, user, validator)
    for saved in db.scalars(select(InitializationChangePreview)):
        saved.created_at = datetime.now(UTC) - timedelta(days=2)
    db.commit()
    second = review(db, draft, user, validator)
    assert validator.calls == 1
    assert second["validation"]["reused"] is True
    assert second["validation"]["validated_at"] == first["validation"]["validated_at"]
    assert second["preview_id"] != first["preview_id"]
    apply(db, draft, user, second)
    assert project.construction_unit_name == "新单位"


def test_explicit_revalidation_revision_baseline_selection_and_mcp_version_invalidate_snapshot(db):
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位", "engineering_type_description": "新工程"}})
    validator = CountingValidator()
    first = review(db, draft, user, validator)
    review(db, draft, user, validator, force_validation=True)
    assert validator.calls == 2
    draft.revision += 1
    review(db, draft, user, validator)
    assert validator.calls == 3
    project.design_unit_name = "正式数据变动"
    review(db, draft, user, validator)
    assert validator.calls == 4
    review(db, draft, user, validator, selected_keys=first["selected_keys"][:1])
    assert validator.calls == 5
    validator.version = "2.1.0"
    review(db, draft, user, validator)
    assert validator.calls == 6


def test_expert_validation_creates_snapshot_for_first_review(db):
    _, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    validator = CountingValidator()
    run_incremental_validation(db, draft, client=validator)
    opened = review(db, draft, user, validator)
    assert validator.calls == 1
    assert opened["validation"]["reused"] is True


def test_same_blank_quality_is_accepted_or_rejected_only_by_mcp_rule(db):
    project, user, draft = _draft(db, {"quality_requirements": [{"wbs_code": "1"}]})
    _wbs(db, project)
    validator = CountingValidator()
    accepted = review(db, draft, user, validator)
    assert accepted["can_apply"] and accepted["issues"] == []
    validator.reject_blank = True
    rejected = review(db, draft, user, validator, force_validation=True)
    assert not rejected["can_apply"]
    assert [issue["rule_id"] for issue in rejected["issues"]] == ["quality.custom_required"]
    cached = review(db, draft, user, validator)
    assert cached["issues"] == rejected["issues"] and validator.calls == 2
    validator.reject_blank = False
    accepted = review(db, draft, user, validator, force_validation=True)
    apply(db, draft, user, accepted)
    saved = db.scalar(select(QualityMetric))
    assert saved.control_indicator == "" and saved.inspection_frequency == ""


def test_backend_does_not_append_a_second_structural_verdict(db):
    _, user, draft = _draft(db, {"wbs": [{"wbs_code": "1.1", "name": "原文工序", "level": 1}]})
    class AllowsMaterial:
        def validate_project_initialization(self, payload):
            assert payload["wbs"][0]["level"] == 1
            return {"package_id": "custom", "package_version": "1", "result": {
                "status": "ready", "validation_issues": [], "ruleset_version": "1",
            }}
    result = review(db, draft, user, AllowsMaterial())
    assert result["issues"] == [] and result["can_apply"]


def test_backend_does_not_filter_mcp_section_verdict_or_override_invalid_status(db):
    _, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    class SectionValidator:
        def validate_project_initialization(self, payload):
            return {"package_id": "custom", "package_version": "1", "result": {
                "status": "invalid", "validation_issues": [{
                    "rule_id": "personnel.empty", "level": "error", "section": "personnel",
                    "target_record_id": None, "field_name": None, "label": "需修正",
                    "title": "MCP 要求补充人员", "message": "当前规则要求先提供人员分区。",
                }],
            }}
    result = review(db, draft, user, SectionValidator())
    assert not result["can_apply"]
    assert [issue["rule_id"] for issue in result["issues"]] == ["personnel.empty"]


def test_version_change_during_execution_does_not_cache_under_old_version(db):
    _, user, draft = _draft(db, {"project": {"construction_unit_name": "新单位"}})
    class SwitchingValidator(CountingValidator):
        def validate_project_initialization(self, payload):
            self.version = "2.1.0"
            return super().validate_project_initialization(payload)
    validator = SwitchingValidator()
    review(db, draft, user, validator)
    assert not any(row.request.get("snapshot_key") for row in db.scalars(select(InitializationChangePreview)))
    review(db, draft, user, validator)
    cached = review(db, draft, user, validator)
    assert validator.calls == 2 and cached["validation"]["reused"]


def test_mcp_scopes_related_findings_once_per_change():
    finding = {
        "rule_id": "wbs.sibling_start_order", "target_record_id": 1,
        "related_record_ids": [2], "section": "wbs", "field_name": "planned_start_at",
        "message": "原文日期需核对", "details": {},
    }
    mirrored = {**finding, "target_record_id": 2, "related_record_ids": [1]}
    scope = {
        "record_targets": {str(i): {"section": "wbs", "change_keys": [f"wbs:{i}"]} for i in (1, 2)},
        "selected_keys": ["wbs:1", "wbs:2"], "sections": ["wbs"],
    }
    scoped = validator_module._batch_issues([finding, mirrored], scope)
    assert [issue["details"]["change_keys"] for issue in scoped] == [["wbs:1"], ["wbs:2"]]


def test_duplicate_target_is_decided_by_mcp_and_all_source_proposals_are_delivered(db):
    from backend.app.initialization_changes import build_change_plan
    project, user, draft = _draft(db, {"wbs": [
        {"wbs_code": "1", "name": "资料甲"}, {"wbs_code": "1", "name": "资料乙"},
    ]})
    _wbs(db, project)
    plan = build_change_plan(db, draft)
    assert plan["issues"] == []
    checked = review(db, draft, user, Validator())
    assert not checked["can_apply"]
    errors = [issue for issue in checked["issues"] if issue["rule_id"] == "matching.duplicate_target"]
    assert {issue["change_key"] for issue in errors} == set(checked["selected_keys"])
    class Accepts(Validator):
        def validate_project_initialization(self, payload):
            mapping = next(row for row in payload["validation_scope"]["record_targets"].values() if row["section"] == "wbs")
            assert [row["values"]["name"] for row in mapping["observations"]] == ["资料甲", "资料乙"]
            result = super().validate_project_initialization(payload)
            result["result"].update(status="ready", validation_issues=[])
            return result
    accepted = review(db, draft, user, Accepts(), force_validation=True)
    assert accepted["can_apply"] and accepted["issues"] == []


def test_source_serials_positions_names_and_dependencies_reach_mcp_without_correction(db):
    from backend.tests.test_initialization_changes import _person
    _, user, draft = _draft(db, {
        "personnel": [_person(identity_card_no="ADMIN-CARD", real_name="资料姓名", position_name="原文自定义岗位", serial_no=0)],
        "wbs": [{"wbs_code": "1", "name": "任务", "level": 1, "predecessor_wbs_codes": ["2", "2"]}],
    })
    class Captures(Validator):
        def validate_project_initialization(self, payload):
            person = payload["personnel"][0]
            assert person["real_name"] == "资料姓名" and person["position_name"] == "原文自定义岗位"
            assert person["serial_no"] == 0
            assert payload["wbs"][0]["predecessor_wbs_codes"] == ["2", "2"]
            return super().validate_project_initialization(payload)
    checked = review(db, draft, user, Captures())
    assert any(issue["rule_id"] == "personnel.existing_account_name" for issue in checked["issues"])


def test_mcp_produces_location_specific_dependency_annotations():
    rows = [
        {"record_id": 1, "wbs_code": "1.1", "name": "前置", "level": 1, "planned_start_at": "2026-01-02", "planned_finish_at": "2026-01-10"},
        {"record_id": 2, "wbs_code": "1.2", "name": "后续", "level": 1, "planned_start_at": "2026-01-01", "planned_finish_at": "2026-01-11", "predecessor_wbs_codes": ["1.1"]},
    ]
    result = validator_module.validate_project_initialization({"wbs": rows, "validation_scope": {
        "record_targets": {str(row["record_id"]): {"section": "wbs", "change_keys": [str(row["record_id"])]} for row in rows},
        "selected_keys": ["1", "2"], "sections": ["wbs"],
    }})
    overlaps = {issue["target_record_id"]: issue for issue in result["validation_issues"] if issue["rule_id"] == "wbs.predecessor_overlap"}
    assert overlaps[1]["field_name"] == "planned_finish_at" and "作为前置工序" in overlaps[1]["message"]
    assert overlaps[2]["field_name"] == "planned_start_at"


def test_composing_incomplete_observations_has_no_business_model_validation(db):
    from backend.app.initialization_draft_queries import compose_initialization_draft_payload
    _, _, draft = _draft(db, {"quality_requirements": [{"wbs_code": "1", "control_indicator": ""}], "wbs": [{"wbs_code": "1", "level": -2}]})
    payload = compose_initialization_draft_payload(db, draft)
    assert payload.quality_requirements[0].control_indicator == ""
    assert payload.wbs[0].level == -2


def test_external_identity_change_invalidates_previously_reviewed_mcp_facts(db):
    import pytest
    from backend.app.project_initialization import InitializationApplyError
    from backend.tests.test_initialization_changes import _person
    _, user, draft = _draft(db, {"personnel": [_person(identity_card_no="ADMIN-CARD", real_name="管理员")]})
    checked = review(db, draft, user, Validator())
    assert checked["can_apply"]
    user.real_name = "账号已由其他操作更名"
    db.commit()
    with pytest.raises(InitializationApplyError, match="项目数据已经变化"):
        apply(db, draft, user, checked)
