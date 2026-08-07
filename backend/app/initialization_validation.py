"""Direct platform execution and persistence for initialization validation."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agentscope_client import AgentScopeClient, AgentScopeGatewayError
from .config import get_settings
from .initialization_draft_queries import compose_initialization_draft_payload
from .initialization_integrity import validate_initialization_integrity
from .models import (
    ProjectInitializationDraft,
    ProjectInitializationValidationRun,
)


class InitializationValidatorClient(Protocol):
    def validate_project_initialization(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class InitializationValidationError(RuntimeError):
    """Raised when the platform validator cannot produce a trusted result."""


def _normalize_issues(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise InitializationValidationError("核验 MCP 未返回问题数组。")
    issues: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题不是对象。",
            )
        level = raw.get("level")
        path = raw.get("path")
        message = raw.get("message")
        rule_id = raw.get("rule_id")
        if (
            level not in {"error", "warning"}
            or not isinstance(path, str)
            or not path.strip()
            or not isinstance(message, str)
            or not message.strip()
        ):
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题格式无效。",
            )
        item = {
            "level": str(level),
            "path": path.strip(),
            "message": message.strip(),
        }
        if isinstance(rule_id, str) and rule_id.strip():
            item["rule_id"] = rule_id.strip()
        issues.append(item)
    return issues


def _merge_integrity_issues(
    mcp_issues: list[dict[str, str]],
    integrity_issues: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged = list(mcp_issues)
    seen = {
        (item["level"], item["path"], item["message"])
        for item in merged
    }
    for issue in integrity_issues:
        key = (issue["level"], issue["path"], issue["message"])
        if key not in seen:
            seen.add(key)
            merged.append(issue)
    return merged


def latest_initialization_validation_run(
    db: Session,
    draft_id: int,
) -> ProjectInitializationValidationRun | None:
    return db.scalar(
        select(ProjectInitializationValidationRun)
        .where(ProjectInitializationValidationRun.draft_id == draft_id)
        .order_by(ProjectInitializationValidationRun.id.desc()),
    )


def validation_run_view(
    run: ProjectInitializationValidationRun | None,
) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "result_status": run.result_status,
        "package_id": run.package_id,
        "package_version": run.package_version,
        "ruleset_version": run.ruleset_version,
        "duration_ms": run.duration_ms,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def run_project_initialization_validation(
    db: Session,
    draft: ProjectInitializationDraft,
    *,
    client: InitializationValidatorClient | None = None,
) -> dict[str, Any]:
    """Compose, validate and persist one draft without a model round-trip."""
    if draft.status in {"applied", "rejected"}:
        raise InitializationValidationError("已结束的初始化草稿不能重新核验。")
    payload_model = compose_initialization_draft_payload(db, draft)
    payload = payload_model.model_dump(mode="json")
    run = ProjectInitializationValidationRun(
        draft_id=draft.id,
        project_id=draft.project_id,
        conversation_id=draft.conversation_id,
        draft_revision=draft.revision,
        status="running",
        validation_issues=[],
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    validator = client or AgentScopeClient(get_settings())
    try:
        response = validator.validate_project_initialization(payload)
        package_id = response.get("package_id")
        package_version = response.get("package_version")
        duration_ms = response.get("duration_ms")
        result = response.get("result")
        if not isinstance(result, dict):
            raise InitializationValidationError("核验 MCP 返回结果无效。")
        mcp_issues = _normalize_issues(result.get("validation_issues"))
        issues = _merge_integrity_issues(
            mcp_issues,
            validate_initialization_integrity(payload_model),
        )
        result_status = (
            "invalid"
            if any(item["level"] == "error" for item in issues)
            else "ready"
        )
        declared_status = result.get("status")
        if declared_status not in {"ready", "invalid"}:
            raise InitializationValidationError("核验 MCP 未返回有效状态。")
        if not isinstance(package_id, str) or not package_id:
            raise InitializationValidationError("核验 MCP 缺少包标识。")
        if not isinstance(package_version, str) or not package_version:
            raise InitializationValidationError("核验 MCP 缺少版本号。")
        if not isinstance(duration_ms, int) or duration_ms < 0:
            raise InitializationValidationError("核验 MCP 缺少有效耗时。")

        draft.payload = payload
        draft.validation_issues = issues
        draft.status = result_status
        run.status = "completed"
        run.result_status = result_status
        run.package_id = package_id
        run.package_version = package_version
        ruleset_version = result.get("ruleset_version")
        run.ruleset_version = (
            str(ruleset_version) if ruleset_version is not None else None
        )
        run.validation_issues = issues
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        db.refresh(draft)
        return {
            "draft_id": draft.id,
            "draft_revision": draft.revision,
            "status": result_status,
            "validation_issues": issues,
            "validation": validation_run_view(run),
        }
    except (AgentScopeGatewayError, InitializationValidationError) as exc:
        db.rollback()
        failed_run = db.get(ProjectInitializationValidationRun, run.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.error = str(exc)
            failed_run.finished_at = datetime.now(UTC)
            db.commit()
        raise InitializationValidationError(str(exc)) from exc
    except Exception as exc:
        db.rollback()
        failed_run = db.get(ProjectInitializationValidationRun, run.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.error = str(exc)
            failed_run.finished_at = datetime.now(UTC)
            db.commit()
        raise InitializationValidationError(
            f"项目初始化核验失败：{exc}",
        ) from exc
