from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, TypeVar

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    OperationLog,
    Project,
    ProjectConnectorConfig,
    ProjectMember,
    User,
    UserConnectorConfig,
)
from .security import decode_access_token
from .wecom_notification_gateway import (
    is_wecom_webhook_url,
    project_wecom_configured,
)


bearer = HTTPBearer(auto_error=False)
ModelType = TypeVar("ModelType")


def ok(data: Any, message: str = "ok") -> dict[str, Any]:
    return {"success": True, "data": data, "message": message}


def serialize(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in row.__table__.columns:
        if column.name == "password_hash":
            continue
        value = getattr(row, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return result


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    payload = decode_access_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def project_for_user_or_403(
    db: Session,
    project_id: int,
    user: User,
) -> Project:
    """Resolve a project while enforcing current platform membership."""
    project = project_or_404(db, project_id)
    if user.role == "admin":
        return project
    membership = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        ),
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你不是该项目的有效成员",
        )
    return project


def entity_or_404(db: Session, model: type[ModelType], item_id: int, message: str) -> ModelType:
    entity = db.get(model, item_id)
    if not entity:
        raise HTTPException(status_code=404, detail=message)
    return entity


TASK_FLOW_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "条件核查": [("发起核查", "核查清单"), ("现场复核", "现场记录与照片"), ("负责人确认", "复核意见"), ("资料归档", "闭环资料")],
    "隐患整改": [("发现隐患", "隐患记录"), ("派单整改", "整改方案与照片"), ("安全员复核", "复核记录"), ("闭环归档", "闭环证明")],
    "资料补全": [("识别缺失", "缺失项清单"), ("补齐资料", "待补资料"), ("复核资料", "复核意见"), ("资料归档", "完整资料包")],
    "风险处置": [("风险触发", "风险依据"), ("数据复核", "监测或核验数据"), ("处置确认", "处置记录"), ("风险关闭", "关闭依据")],
    "报告审核": [("提交报告", "报告文件"), ("依据审核", "审核意见"), ("问题修订", "修订稿"), ("审核通过", "定稿文件")],
    "自定义": [("发起任务", "任务依据"), ("执行处理", "过程资料"), ("复核确认", "复核意见"), ("闭环归档", "闭环资料")],
}


def infer_task_flow_type(requirement: str, requested_type: str | None = None) -> str:
    if requested_type in TASK_FLOW_TEMPLATES:
        return requested_type
    if any(word in requirement for word in ("资料", "文件", "上传", "补全", "缺失")):
        return "资料补全"
    if any(word in requirement for word in ("整改", "隐患", "安全")):
        return "隐患整改"
    if any(word in requirement for word in ("风险", "监测", "预警")):
        return "风险处置"
    if any(word in requirement for word in ("报告", "审核", "审查")):
        return "报告审核"
    return "条件核查"


def build_fallback_task_flow(requirement: str, requested_type: str | None, member_ids: list[int]) -> dict[str, Any]:
    template_type = infer_task_flow_type(requirement, requested_type)
    task_type = {
        "资料补全": "material_missing",
        "报告审核": "draft_review",
        "条件核查": "risk_alert",
        "隐患整改": "risk_alert",
        "风险处置": "risk_alert",
        "自定义": "risk_alert",
    }[template_type]
    interval_match = re.search(r"每(?P<value>\d+|[一二三四五六七八九十两]+)?(?:个)?(?P<unit>小时|天|日|周|月)", requirement)
    run_mode = "scheduled" if interval_match or "定时" in requirement else "single"
    trigger_rule = "手动发起"
    trigger_interval_value = 1
    trigger_interval_unit = "week"
    if interval_match:
        raw_value = interval_match.group("value") or "1"
        chinese_numbers = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        trigger_interval_value = int(raw_value) if raw_value.isdigit() else chinese_numbers.get(raw_value, 1)
        unit = interval_match.group("unit")
        trigger_interval_unit = {"小时": "hour", "天": "day", "日": "day", "周": "week", "月": "month"}[unit]
        trigger_rule = f"每{trigger_interval_value}{unit}按设定时间执行"
    elif "监测" in requirement or "预警" in requirement:
        trigger_rule = "监测数据达到触发条件时执行"
    title = re.sub(r"[。；;\n].*$", "", requirement).strip()[:40] or f"{template_type}任务"
    steps = []
    for index, (name, material) in enumerate(TASK_FLOW_TEMPLATES[template_type]):
        owner_user_id = member_ids[index % len(member_ids)] if member_ids else None
        steps.append({
            "name": name,
            "owner_user_id": owner_user_id,
            "due_at": (date.today() + timedelta(days=index + 1)).isoformat(),
            "material": material,
        })
    return {
        "title": title,
        "task_type": task_type,
        "risk_level": "high" if any(word in requirement for word in ("重大", "紧急", "高风险")) else "medium",
        "run_mode": run_mode,
        "trigger_date": date.today().isoformat(),
        "trigger_time": "09:00",
        "trigger_rule": trigger_rule,
        "trigger_interval_value": trigger_interval_value,
        "trigger_interval_unit": trigger_interval_unit,
        "cc": "",
        "steps": steps,
    }


def extract_json_object(content: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content, re.IGNORECASE)
    candidate = fenced.group(1) if fenced else content[content.find("{"):content.rfind("}") + 1]
    if not candidate:
        raise ValueError("模型未返回 JSON")
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("模型返回格式错误")
    return parsed


def normalize_task_flow(data: dict[str, Any], fallback: dict[str, Any], members: list[dict[str, Any]], wbs_ids: set[int], risk_ids: set[int]) -> dict[str, Any]:
    member_map = {member["id"]: member["name"] for member in members}
    valid_task_types = {"risk_alert", "material_missing", "daily_confirm", "draft_review", "fill_platform"}
    valid_risk_levels = {"low", "medium", "high", "critical"}

    def valid_id(value: Any, valid_ids: set[int]) -> int | None:
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            return None
        return item_id if item_id in valid_ids else None

    def interval_value(value: Any) -> int:
        try:
            return max(1, min(int(value), 365))
        except (TypeError, ValueError):
            return int(fallback["trigger_interval_value"])

    raw_steps = data.get("steps") if isinstance(data.get("steps"), list) else fallback["steps"]
    steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps[:8]):
        if not isinstance(raw_step, dict):
            continue
        owner_user_id = valid_id(raw_step.get("owner_user_id"), set(member_map))
        steps.append({
            "name": str(raw_step.get("name") or f"流程节点 {index + 1}")[:60],
            "owner_user_id": owner_user_id,
            "owner": member_map.get(owner_user_id, str(raw_step.get("owner") or "待指定")),
            "due_at": str(raw_step.get("due_at") or (date.today() + timedelta(days=index + 1)).isoformat())[:32],
            "material": str(raw_step.get("material") or "过程记录")[:200],
            "order": index + 1,
            "next_step": index + 2 if index + 1 < len(raw_steps[:8]) else None,
            "status": "pending",
        })
    if len(steps) < 2:
        return normalize_task_flow(fallback, fallback, members, wbs_ids, risk_ids)
    return {
        "title": str(data.get("title") or fallback["title"])[:120],
        "task_type": data.get("task_type") if data.get("task_type") in valid_task_types else fallback["task_type"],
        "risk_level": data.get("risk_level") if data.get("risk_level") in valid_risk_levels else fallback["risk_level"],
        "assignee_user_id": valid_id(data.get("assignee_user_id"), set(member_map)) or steps[0]["owner_user_id"],
        "confirmer_user_id": valid_id(data.get("confirmer_user_id"), set(member_map)),
        "wbs_item_id": valid_id(data.get("wbs_item_id"), wbs_ids),
        "risk_source_id": valid_id(data.get("risk_source_id"), risk_ids),
        "run_mode": data.get("run_mode") if data.get("run_mode") in {"single", "scheduled"} else fallback["run_mode"],
        "trigger_date": str(data.get("trigger_date") or fallback["trigger_date"])[:10],
        "trigger_time": str(data.get("trigger_time") or fallback["trigger_time"])[:5],
        "trigger_rule": str(data.get("trigger_rule") or fallback["trigger_rule"])[:300],
        "trigger_interval_value": interval_value(data.get("trigger_interval_value") or fallback["trigger_interval_value"]),
        "trigger_interval_unit": data.get("trigger_interval_unit") if data.get("trigger_interval_unit") in {"hour", "day", "week", "month"} else fallback["trigger_interval_unit"],
        "cc": str(data.get("cc") or fallback["cc"])[:300],
        "steps": steps,
    }


def audit(db: Session, user: User, action: str, detail: str, project_id: int | None = None, target_type: str | None = None, target_id: int | None = None) -> None:
    db.add(OperationLog(project_id=project_id, operator_id=user.id, action=action, detail=detail, target_type=target_type, target_id=target_id))


def user_connector_view(row: UserConnectorConfig) -> dict[str, Any]:
    """Expose connector metadata without ever returning its credential."""

    return {
        "id": row.id,
        "connector_type": row.connector_type,
        "account_identifier": row.account_identifier,
        "platform_type": row.platform_type,
        "configured": row.configured,
        "has_secret": bool(row.secret_encrypted),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def project_connector_view(row: ProjectConnectorConfig) -> dict[str, Any]:
    """Expose project connector metadata without returning its credential."""

    legacy_wecom_webhook = (
        row.connector_type == "wecom"
        and is_wecom_webhook_url(row.connection_id)
    )
    return {
        "id": row.id,
        "project_id": row.project_id,
        "connector_type": row.connector_type,
        "connection_id": (
            "项目群机器人" if legacy_wecom_webhook else row.connection_id
        ),
        "configured": (
            project_wecom_configured(row)
            if row.connector_type == "wecom"
            else row.configured
        ),
        "has_secret": bool(row.secret_encrypted or legacy_wecom_webhook),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
