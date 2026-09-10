"""Validate the effective project and attribute only affected issues to changes."""
from types import SimpleNamespace
from typing import Any

from .agentscope_client import AgentScopeClient
from .config import get_settings
from .initialization_integrity import validate_initialization_integrity
from .initialization_validation import (
    InitializationValidationError, InitializationValidatorClient,
    _SECTION_MODELS, _merge_integrity_issues, _normalize_issues,
)


def _integrity_payload(payload: dict[str, Any]) -> SimpleNamespace:
    values: dict[str, Any] = {}
    for section, model in _SECTION_MODELS.items():
        rows = [payload.get(section, {})] if section == "project" else payload.get(section, [])
        # Existing legacy records may predate strict draft requirements. They
        # remain part of the reference graph without inventing missing values.
        records = [model.model_construct(**{**{key: None for key in model.model_fields}, **row}) for row in rows]
        values[section] = records[0] if section == "project" else records
    return SimpleNamespace(**values)


def affected_issues(issues: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Untouched missing sections or historical defects do not gate this batch."""
    targets = plan["record_targets"]
    selected = set(plan["selected_keys"])
    sections = {change["section"] for change in plan["changes"] if change["key"] in selected}
    result: list[dict[str, Any]] = []
    for issue in issues:
        target = targets.get(str(issue.get("target_record_id")), {})
        keys = list(target.get("change_keys") or ([target["change_key"]] if target.get("change_key") else []))
        field = issue.get("field_name")
        if target.get("section") == "project" and field:
            dependent_fields = ("contract_start_date", "contract_end_date") if issue["rule_id"].endswith("contract_date_order") else (field,)
            keys = [target.get("field_changes", {}).get(name) for name in dependent_fields]
        for related_id in issue.get("related_record_ids", []):
            related = targets.get(str(related_id), {})
            keys.extend(related.get("change_keys") or ([related["change_key"]] if related.get("change_key") else []))
        affected = list(dict.fromkeys(key for key in keys if key in selected))
        if not affected:
            if issue.get("target_record_id") is not None or issue["section"] not in sections:
                continue
            if issue["rule_id"].endswith(".empty"):
                continue
        for key in affected or [None]:
            result.append({**issue, "change_key": key})
    return result


def validate_change_plan(
    plan: dict[str, Any], *, client: InitializationValidatorClient | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues = list(plan.get("issues", []))
    if not plan["selected_keys"] or any(issue["level"] == "error" for issue in issues):
        return issues, {"status": "completed", "package_version": None}
    payload = plan["effective_payload"]
    records = {
        int(key): SimpleNamespace(section=value["section"])
        for key, value in plan["record_targets"].items()
    }
    response = (client or AgentScopeClient(get_settings())).validate_project_initialization(payload)
    result = response.get("result")
    if not isinstance(result, dict) or result.get("status") not in {"ready", "invalid"}:
        raise InitializationValidationError("核验服务未返回有效结果，请重新核验。")
    if not response.get("package_id") or not response.get("package_version"):
        raise InitializationValidationError("核验服务未提供规则版本，请重新核验。")
    normalized = _normalize_issues(result.get("validation_issues"), records)
    structural = validate_initialization_integrity(_integrity_payload(payload))
    issues.extend(affected_issues(_merge_integrity_issues(normalized, structural), plan))
    return issues, {
        "status": "completed", "package_id": response["package_id"],
        "package_version": response["package_version"],
        "ruleset_version": result.get("ruleset_version"),
        "duration_ms": response.get("duration_ms"),
    }
