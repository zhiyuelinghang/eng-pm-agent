"""项目状态的资料完整性、今日新增与安全记录汇总。"""
from datetime import UTC, datetime, timedelta, timezone
from collections.abc import Iterator, Sequence
from typing import Any
import re

from sqlalchemy import select
from sqlalchemy.orm import Session
from task_engine.engine import TaskEngine
from task_engine.domain.models import TaskInstance

from .engineering_document_catalog import readable_external_ids
from .models import EngineeringDocumentNode, User, RiskSource, QualityMetric


def meeting_status_details(db: Session, project_id: int, user: User, risks: Sequence[RiskSource],
                           quality_requirements: Sequence[QualityMetric], *, now: datetime | None = None) -> dict[str, Any]:
    readable_ids = readable_external_ids(db, project_id, user)
    files = db.scalars(select(EngineeringDocumentNode).where(
        EngineeringDocumentNode.project_id == project_id, EngineeringDocumentNode.node_type == "file",
        EngineeringDocumentNode.external_id.in_(readable_ids),
    )).all() if readable_ids else []
    local_zone = timezone(timedelta(hours=8))
    today = (now or datetime.now(UTC)).astimezone(local_zone).date()

    def created_today(row: EngineeringDocumentNode) -> bool:
        value = row.external_created_at or row.created_at
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            if stamp is None:
                return False
            return (stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)).astimezone(local_zone).date() == today
        except (ValueError, TypeError):
            return False

    today_files = sorted((row for row in files if created_today(row)), key=lambda row: row.id, reverse=True)
    requirements = set()
    for row in [*risks, *quality_requirements]:
        values = (getattr(row, "material_requirements", None) or getattr(row, "required_materials", None)
                  or re.split(r"[、，,；;\n]", getattr(row, "related_documents", "") or ""))
        requirements.update(str(value).strip() for value in values if str(value).strip())
    names = [row.name.casefold() for row in files]
    missing = sorted(name for name in requirements if not any(name.casefold() in filename for filename in names))
    safety = [risk for risk in risks if risk.status not in {"closed", "resolved", "completed", "已关闭", "已消除"}
              and any(word in " ".join(str(value or "") for value in (risk.related_process_name, risk.risk_part, risk.summary, risk.evaluation_condition))
                      for word in ("安全", "隐患", "坍塌", "高处坠落", "触电", "火灾", "物体打击", "机械伤害", "起重", "基坑", "有限空间"))]
    return {
        "safety": {"total": len(safety), "items": [{"id": risk.id, "name": risk.risk_part, "level": risk.risk_level,
                    "requirement": risk.evaluation_condition, "status": risk.status} for risk in safety]},
        "documents": {"today_count": len(today_files), "today_files": [{"id": row.external_id, "name": row.name, "folder_path": row.folder_path} for row in today_files],
                      "required_count": len(requirements), "missing_materials": missing, "complete": not missing if requirements else None},
    }


def project_status_tasks(engine: TaskEngine, project_id: int) -> Iterator[TaskInstance]:
    offset = 0
    while True:
        page = engine.list_tasks(project_id=project_id, open_only=True, limit=500, offset=offset)
        yield from page
        if len(page) < 500:
            return
        offset += len(page)
