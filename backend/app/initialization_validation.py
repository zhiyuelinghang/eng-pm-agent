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
    def get_initialization_validation_binding(self) -> dict[str, Any] | None: ...

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
    """Validate this draft against the project's current formal records."""
    from .initialization_incremental_validation import run_incremental_validation
    return run_incremental_validation(db, draft, client=client)
