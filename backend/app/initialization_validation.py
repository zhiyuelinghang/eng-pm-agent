"""Direct platform execution and persistence for initialization validation."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .agentscope_client import AgentScopeClient, AgentScopeGatewayError
from .config import get_settings
from .initialization_draft_queries import (
    compose_initialization_draft_payload,
    serialize_initialization_validation_issue,
)
from .initialization_integrity import validate_initialization_integrity
from .models import (
    ProjectInitializationDraft,
    ProjectInitializationDraftRecord,
    ProjectInitializationValidationIssue,
    ProjectInitializationValidationRun,
)
from .project_initialization import (
    PersonnelDraft,
    ProjectDetailsDraft,
    QualityRequirementDraft,
    RiskDraftItem,
    WbsDraft,
)


class InitializationValidatorClient(Protocol):
    def validate_project_initialization(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...


class InitializationValidationError(RuntimeError):
    """Raised when the platform validator cannot produce a trusted result."""


_SECTION_MODELS = {
    "project": ProjectDetailsDraft,
    "personnel": PersonnelDraft,
    "wbs": WbsDraft,
    "risks": RiskDraftItem,
    "quality_requirements": QualityRequirementDraft,
}
_SECTION_FIELDS = {
    section: set(model.model_fields) - {"record_id"}
    for section, model in _SECTION_MODELS.items()
}


def _required_text(raw: dict[str, Any], name: str, index: int) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InitializationValidationError(
            f"核验 MCP 的第 {index + 1} 个问题缺少有效的 {name}。",
        )
    return value.strip()


def _normalize_issues(
    value: Any,
    records_by_id: dict[int, ProjectInitializationDraftRecord],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InitializationValidationError("核验 MCP 未返回问题数组。")
    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题不是对象。",
            )
        level = raw.get("level")
        if level not in {"error", "warning"}:
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题级别无效。",
            )
        section = _required_text(raw, "section", index)
        if section not in _SECTION_FIELDS:
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题分区无效。",
            )
        target_record_id = raw.get("target_record_id")
        if target_record_id is not None and (
            not isinstance(target_record_id, int)
            or isinstance(target_record_id, bool)
            or target_record_id not in records_by_id
        ):
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题指向了无效数据 ID。",
            )
        if target_record_id is not None:
            target = records_by_id[target_record_id]
            if target.section != section:
                raise InitializationValidationError(
                    f"核验 MCP 的第 {index + 1} 个问题分区与数据 ID 不一致。",
                )
        field_name = raw.get("field_name")
        if field_name is not None:
            if (
                not isinstance(field_name, str)
                or field_name not in _SECTION_FIELDS[section]
                or target_record_id is None
            ):
                raise InitializationValidationError(
                    f"核验 MCP 的第 {index + 1} 个问题字段定位无效。",
                )
        related_record_ids = raw.get("related_record_ids", [])
        if not isinstance(related_record_ids, list) or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or item not in records_by_id
            for item in related_record_ids
        ):
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题关联数据 ID 无效。",
            )
        details = raw.get("details", {})
        if not isinstance(details, dict):
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题详情必须是对象。",
            )
        suggestion = raw.get("suggestion")
        if suggestion is not None and not isinstance(suggestion, str):
            raise InitializationValidationError(
                f"核验 MCP 的第 {index + 1} 个问题处理建议必须是文本。",
            )
        issues.append(
            {
                "rule_id": _required_text(raw, "rule_id", index),
                "level": level,
                "section": section,
                "target_record_id": target_record_id,
                "field_name": field_name,
                "label": _required_text(raw, "label", index),
                "title": _required_text(raw, "title", index),
                "message": _required_text(raw, "message", index),
                "suggestion": suggestion.strip() if suggestion else None,
                "related_record_ids": list(dict.fromkeys(related_record_ids)),
                "details": details,
            },
        )
    return issues


def _merge_integrity_issues(
    mcp_issues: list[dict[str, Any]],
    integrity_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(mcp_issues)
    seen = {
        (
            item["rule_id"],
            item["target_record_id"],
            item["field_name"],
            item["message"],
        )
        for item in merged
    }
    for issue in integrity_issues:
        key = (
            issue["rule_id"],
            issue["target_record_id"],
            issue["field_name"],
            issue["message"],
        )
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
        "draft_revision": run.draft_revision,
        "result_status": run.result_status,
        "package_id": run.package_id,
        "package_version": run.package_version,
        "ruleset_version": run.ruleset_version,
        "duration_ms": run.duration_ms,
        "issue_count": len(run.validation_issues or []),
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
    records = list(
        db.scalars(
            select(ProjectInitializationDraftRecord).where(
                ProjectInitializationDraftRecord.draft_id == draft.id,
                ProjectInitializationDraftRecord.active.is_(True),
            ),
        ).all(),
    )
    records_by_id = {record.id: record for record in records}
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
        db.refresh(draft)
        if draft.revision != run.draft_revision:
            raise InitializationValidationError(
                "草稿在核验期间已更新，本次结果已作废，请重新核验。",
            )
        package_id = response.get("package_id")
        package_version = response.get("package_version")
        duration_ms = response.get("duration_ms")
        result = response.get("result")
        if not isinstance(result, dict):
            raise InitializationValidationError("核验 MCP 返回结果无效。")
        mcp_issues = _normalize_issues(
            result.get("validation_issues"),
            records_by_id,
        )
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

        issue_rows: list[ProjectInitializationValidationIssue] = []
        for issue in issues:
            row = ProjectInitializationValidationIssue(
                validation_run_id=run.id,
                draft_id=draft.id,
                project_id=draft.project_id,
                draft_revision=draft.revision,
                section=issue["section"],
                target_record_id=issue["target_record_id"],
                field_name=issue["field_name"],
                rule_id=issue["rule_id"],
                level=issue["level"],
                label=issue["label"],
                title=issue["title"],
                message=issue["message"],
                suggestion=issue["suggestion"],
                related_record_ids=issue["related_record_ids"],
                details=issue["details"],
            )
            db.add(row)
            issue_rows.append(row)
        db.flush()
        serialized_issues = [
            serialize_initialization_validation_issue(row)
            for row in issue_rows
        ]
        run.status = "completed"
        run.result_status = result_status
        run.package_id = package_id
        run.package_version = package_version
        ruleset_version = result.get("ruleset_version")
        run.ruleset_version = (
            str(ruleset_version) if ruleset_version is not None else None
        )
        run.validation_issues = serialized_issues
        run.duration_ms = duration_ms
        run.finished_at = datetime.now(UTC)
        update_result = db.execute(
            update(ProjectInitializationDraft)
            .where(
                ProjectInitializationDraft.id == draft.id,
                ProjectInitializationDraft.revision == run.draft_revision,
            )
            .values(
                payload=payload,
                validation_issues=serialized_issues,
                status=result_status,
            ),
        )
        if update_result.rowcount != 1:
            raise InitializationValidationError(
                "草稿在核验期间已更新，本次结果已作废，请重新核验。",
            )
        db.commit()
        db.refresh(run)
        db.refresh(draft)
        return {
            "draft_id": draft.id,
            "draft_revision": draft.revision,
            "status": result_status,
            "validation_issues": serialized_issues,
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
