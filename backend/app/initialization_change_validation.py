"""Validate the effective project and attribute only affected issues to changes."""
from types import SimpleNamespace
from typing import Any

from .agentscope_client import AgentScopeClient
from .config import get_settings
from .initialization_validation import (
    InitializationValidationError, InitializationValidatorClient,
    _normalize_issues,
)


def locate_issues(issues: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Attach UI locations without suppressing or reclassifying MCP verdicts."""
    targets = plan["record_targets"]
    selected = set(plan["selected_keys"])
    result: list[dict[str, Any]] = []
    for issue in issues:
        target = targets.get(str(issue.get("target_record_id")), {})
        keys = issue.get("details", {}).get("change_keys")
        field = issue.get("field_name")
        if keys is None:
            keys = list(target.get("change_keys", []))
            field_key = target.get("field_changes", {}).get(field)
            if target.get("section") == "project" and field_key:
                keys = [field_key]
        if not isinstance(keys, list) or any(not isinstance(key, str) or key not in selected for key in keys):
            raise InitializationValidationError("核验 MCP 返回了无效的变更定位。")
        affected = list(dict.fromkeys(key for key in keys if key in selected))
        for key in affected or [None]:
            result.append({**issue, "change_key": key})
    return result


def validate_change_plan(
    plan: dict[str, Any], *, client: InitializationValidatorClient | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues = []
    if not plan["selected_keys"]:
        return issues, {"status": "completed", "package_version": None}
    payload = {**plan["effective_payload"], "validation_scope": {
        "record_targets": plan["record_targets"], "selected_keys": plan["selected_keys"],
        "sections": sorted({row["section"] for row in plan["changes"] if row["key"] in plan["selected_keys"]}),
    }}
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
    issues.extend(locate_issues(normalized, plan))
    return issues, {
        "status": "completed", "package_id": response["package_id"],
        "package_version": response["package_version"],
        "ruleset_version": result.get("ruleset_version"),
        "duration_ms": response.get("duration_ms"),
        "source": "mcp",
        "result_status": result["status"],
    }
