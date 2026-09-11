"""The versioned MCP owns current position and numeric rules."""
from copy import deepcopy

import pytest

from backend.app.personnel_policy import PROJECT_POSITION_NAMES
from backend.app.initialization_changes import build_change_plan
from backend.tests.test_initialization_changes import db, _draft, _person  # noqa: F401
from backend.tests.test_initialization_change_service import Validator, apply, preview, validator_module


def findings(section, row):
    item = {"record_id": 1, **row}
    payload = {section: item if section == "project" else [item]}
    before = deepcopy(payload)
    result = validator_module.validate_project_initialization(payload)
    assert payload == before
    return result["validation_issues"]


def test_versioned_mcp_position_catalogue_matches_current_product_catalogue():
    assert len(validator_module.PERSONNEL_POSITIONS) == 15
    assert validator_module.PERSONNEL_POSITIONS == PROJECT_POSITION_NAMES


@pytest.mark.parametrize("position", PROJECT_POSITION_NAMES)
def test_all_fifteen_fixed_positions_pass_without_changing_source(position):
    assert not [issue for issue in findings("personnel", _person(position_name=position)) if issue["level"] == "error"]


@pytest.mark.parametrize("position", ["技术负责人", "项目副经理", "自定义岗位", "项目经理/安全员", "", None, ["安全员"], {"name": "安全员"}])
def test_unsupported_position_is_a_single_targeted_mcp_error(position):
    issues = findings("personnel", _person(position_name=position))
    positions = [issue for issue in issues if issue["rule_id"] == "personnel.unsupported_position"]
    assert len(positions) == 1
    issue = positions[0]
    assert issue["target_record_id"] == 1 and issue["field_name"] == "position_name"
    assert issue["level"] == "error"
    assert issue["details"]["allowed_positions"] == list(PROJECT_POSITION_NAMES)
    assert "重新上传" in issue["suggestion"]


NUMERIC_FIELDS = [(section, field, rule) for section, fields in validator_module.PROJECT_RULES["numeric_fields"].items() for field, rule in fields.items()]


@pytest.mark.parametrize("section,field,rule", NUMERIC_FIELDS)
def test_numeric_boundaries_and_types_are_checked_only_in_mcp(section, field, rule):
    minimum = rule["minimum"]
    valid_minimum = minimum + 1 if rule.get("exclusive_minimum") else minimum
    cases = [(minimum - 1, True), (valid_minimum, False), (str(valid_minimum), False),
             (None, False), ("", False), (True, True), ("NaN", True), ("Infinity", True), ("不是数值", True), ({"value": 1}, True)]
    if rule.get("integer"):
        cases.append((valid_minimum + 0.5, True))
    if "maximum" in rule:
        cases.extend([(rule["maximum"], False), (rule["maximum"] + 1, True)])
    if rule.get("exclusive_minimum"):
        cases.append((minimum, True))
    for value, rejected in cases:
        row = {"wbs_code": "1", "level": 1, "position_name": "安全员", field: value}
        matches = [issue for issue in findings(section, row) if issue["rule_id"] == f"{section}.{field}.value"]
        assert bool(matches) == rejected, (section, field, value)
        assert all(issue["field_name"] == field and issue["target_record_id"] == 1 for issue in matches)


def test_position_error_blocks_its_record_but_not_an_independent_selected_section(db):
    _, user, draft = _draft(db, {"project": {"construction_unit_name": "建设单位"}, "personnel": [_person(position_name="技术负责人")]})
    plan = build_change_plan(db, draft)
    person = next(row for row in plan["changes"] if row["section"] == "personnel")
    assert person["after"]["position_name"] == "技术负责人" and not plan["issues"]
    all_rows = preview(db, draft, user)
    assert not all_rows["can_apply"]
    issue = next(issue for issue in all_rows["issues"] if issue["rule_id"] == "personnel.unsupported_position")
    assert issue["change_key"] == person["key"] and issue["field_name"] == "position_name"
    project_keys = [row["key"] for row in plan["changes"] if row["section"] == "project"]
    selected = preview(db, draft, user, selected_keys=project_keys)
    assert selected["can_apply"] and not selected["issues"]
    result = apply(db, draft, user, selected)
    assert result["remaining"] == 1


def test_platform_does_not_repeat_position_rule_after_custom_mcp_decision(db):
    from backend.app.initialization_change_contracts import PreviewInitializationChangesInput
    from backend.app.initialization_change_service import create_change_preview
    _, user, draft = _draft(db, {"personnel": [_person(position_name="技术负责人")]})
    class CustomMcp(Validator):
        def validate_project_initialization(self, payload):
            assert payload["personnel"][0]["position_name"] == "技术负责人"
            return {"package_id": "custom-validator", "package_version": "1.0.0", "result": {"status": "ready", "validation_issues": []}}
    accepted = create_change_preview(db, draft, user, PreviewInitializationChangesInput(), client=CustomMcp())
    assert accepted["can_apply"] and accepted["issues"] == []


@pytest.mark.parametrize("binding", [
    {"package_id": "project-initialization-validator", "package_version": "2.4.0"},
    {"package_id": "different-validator", "package_version": "2.0.0"},
    None,
])
def test_rule_upgrade_or_package_switch_rejects_old_unsubmitted_confirmation(db, binding):
    from backend.app.project_initialization import InitializationApplyError
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新建设单位"}})
    checked = preview(db, draft, user)
    class Switched(Validator):
        def get_initialization_validation_binding(self):
            return binding
    with pytest.raises(InitializationApplyError, match="规则版本已更新"):
        apply(db, draft, user, checked, client=Switched())
    assert project.construction_unit_name == "原建设单位"


def test_temporary_binding_failure_does_not_allow_unverified_old_confirmation(db):
    from backend.app.project_initialization import InitializationApplyError
    project, user, draft = _draft(db, {"project": {"construction_unit_name": "新建设单位"}})
    checked = preview(db, draft, user)
    class Unavailable(Validator):
        def get_initialization_validation_binding(self):
            raise RuntimeError("service unavailable")
    with pytest.raises(InitializationApplyError, match="暂时无法确认"):
        apply(db, draft, user, checked, client=Unavailable())
    assert project.construction_unit_name == "原建设单位"
