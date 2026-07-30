import asyncio
import hashlib
import io
import json
import re
import shutil
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agentscope_client import (
    AgentScopeClient,
    AgentScopeGatewayError,
    AgentScopeReply,
)
from .config import get_settings
from .db import SessionLocal, get_db
from .models import (AgentConversation, AgentConversationMessage, Attachment, AttachmentText, CollaborationMessage, CollaborationSession, DailyReport, DocumentFolder, DocumentFolderItem, FillPackage, MeetingMinute, Notification, OperationLog, PlatformFieldMapping, Project, ProjectChange, ProjectInformationRecord, ProjectInitializationDraft, ProjectInitializationFile, ProjectMember, ProjectSettings, ProjectStatusSnapshot,
                      QualityMetric, RiskDraft, RiskSource, Task, TaskStatusHistory, User, WbsItem, WbsRiskLink)
from .project_initialization import (
    ApplyInitializationDraftInput,
    InitializationApplyError,
    apply_initialization_draft,
    build_initialization_state,
)
from .schemas import (AttachmentUpdate, DailyReportInput, DailyReportUpdate, DraftInput, DraftReviewInput, FillPackageInput,
                      LoginRequest, MemberInput, PasswordChangeInput, ProfileUpdate, ProjectInput, RiskInput, TaskFlowGenerateInput, TaskInput, TaskTransitionInput,
                      WbsInput, WbsRiskLinkInput, OperationLogInput, PlatformFieldMappingInput, ProjectSettingsInput,
                       AgentConversationConfirmInput, AgentConversationInput, AgentConversationMessageInput, CollaborationMessageInput, CollaborationSessionInput, DocumentFolderInput, ProjectChangeInput, ProjectInformationDispositionInput, QualityMetricInput, TaskNoteInput, TaskReassignInput, TaskStepUpdate)
from .security import create_access_token, decode_access_token, hash_password, verify_password


router = APIRouter(prefix="/api")
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


def _agentscope_client() -> AgentScopeClient:
    return AgentScopeClient(get_settings())


def _raise_agentscope_http_error(exc: AgentScopeGatewayError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _public_agent_catalog_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        key: item.get(key)
        for key in (
            "id",
            "name",
            "description",
            "category",
            "role",
            "enabled",
            "published",
            "invitable",
            "model_ready",
            "sort_order",
            "permission_mode",
            "knowledge_config",
        )
    }


def _catalog_agent_for_conversation(
    catalog: dict[str, Any],
    conversation: AgentConversation,
) -> dict[str, Any]:
    """Resolve a conversation against the latest publication catalogue."""
    if conversation.conversation_type == "general":
        selected = catalog.get("global_main")
        if selected is None or selected.get("id") != conversation.agent_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "平台全局主智能体已停用或发生切换，请刷新页面后开始"
                    "新的主智能体会话"
                ),
            )
    elif conversation.conversation_type == "initialization":
        selected = catalog.get("project_initializer")
        if selected is None or selected.get("id") != conversation.agent_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "项目初始化智能体已停用或发生切换，请刷新工程配置页"
                    "后重新开始初始化会话"
                ),
            )
    else:
        selected = next(
            (
                item
                for item in catalog.get("business_agents", [])
                if item.get("id") == conversation.agent_id
            ),
            None,
        )
        if selected is None:
            raise HTTPException(
                status_code=409,
                detail="该业务智能体已停用或取消发布，请刷新业务工具页面",
            )
    if not selected.get("model_ready"):
        raise HTTPException(
            status_code=409,
            detail=f"智能体「{selected.get('name')}」尚未配置固定模型",
        )
    return selected


def _agent_conversation_or_404(
    db: Session,
    conversation_id: int,
    user: User,
) -> AgentConversation:
    conversation = db.get(AgentConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="智能体会话不存在")
    if conversation.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该智能体会话")
    project_for_user_or_403(db, conversation.project_id, user)
    return conversation


INITIALIZATION_FILE_SUFFIXES = {
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
    ".docx",
    ".pdf",
}
INITIALIZATION_FILE_MAX_BYTES = 30 * 1024 * 1024


def _public_initialization_file(
    row: ProjectInitializationFile,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "conversation_id": row.conversation_id,
        "uploaded_by_user_id": row.uploaded_by_user_id,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "file_size": row.file_size,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _initialization_files_for_message(
    db: Session,
    conversation: AgentConversation,
    file_ids: list[int],
) -> list[ProjectInitializationFile]:
    unique_ids = list(dict.fromkeys(file_ids))
    if not unique_ids:
        return []
    if conversation.conversation_type != "initialization":
        raise HTTPException(
            status_code=422,
            detail="只有项目初始化会话可以携带初始化附件",
        )
    rows = db.scalars(
        select(ProjectInitializationFile).where(
            ProjectInitializationFile.id.in_(unique_ids),
            ProjectInitializationFile.project_id == conversation.project_id,
            ProjectInitializationFile.conversation_id == conversation.id,
        ),
    ).all()
    by_id = {row.id: row for row in rows}
    if any(file_id not in by_id for file_id in unique_ids):
        raise HTTPException(
            status_code=422,
            detail="初始化附件不存在或不属于当前会话",
        )
    return [by_id[file_id] for file_id in unique_ids]


def _initialization_file_context(
    files: list[ProjectInitializationFile],
) -> str:
    if not files:
        return ""
    items = [
        {
            "file_id": item.id,
            "file_name": item.file_name,
            "content_type": item.content_type,
            "file_size": item.file_size,
        }
        for item in files
    ]
    return (
        "\n<initialization-files>\n"
        "以下附件只在本项目初始化会话中可用。必须调用 "
        "dobby_read_project_initialization_file 按 file_id 读取，"
        "不得根据文件名猜测内容：\n"
        f"{json.dumps(items, ensure_ascii=False)}\n"
        "</initialization-files>"
    )


def _initialization_agent_instruction(
    conversation: AgentConversation,
) -> str:
    if conversation.conversation_type != "initialization":
        return ""
    return (
        "\n<project-initialization-role>\n"
        "你是当前项目的专用初始化助手。项目名称已经由用户创建，不得修改。"
        "你的任务是通过问答和原始附件补全工程基本信息、人员、WBS、风险源"
        "与质量指标。\n"
        "工作规则：\n"
        "1. 先调用 dobby_get_project_initialization_state，确认正式业务数据、"
        "最新草稿摘要和当前会话可读取的附件。必须明确区分正式业务数据与"
        "尚未确认的草稿数据；正式表为空不代表草稿为空。\n"
        "2. 如果 latest_draft 不为空，回答草稿内容或继续补充数据前，必须"
        "调用 dobby_get_project_initialization_draft 按需读取相关分区。"
        "新增风险或质量指标时，应读取草稿 WBS 并使用其中编码完成匹配，"
        "不得因为正式 WBS 尚未入库就重新解析全部旧附件。\n"
        "3. 已有草稿的日常补充必须调用 "
        "dobby_update_project_initialization_draft 增量更新，只提交本次"
        "改变的分区，并使用读取草稿返回的最新 revision。只有尚无草稿，"
        "或用户明确要求从全部原始资料整体重建时，才调用 "
        "dobby_submit_project_initialization_draft。\n"
        "4. 新附件或用户要求重新核验原文时，必须调用 "
        "dobby_read_project_initialization_file 读取；"
        "平台不会把解析文本直接塞进提示词。大文件应按工作表或分页分段读取。\n"
        "5. 只使用用户明确提供、附件实际包含、正式业务工具或草稿读取工具"
        "返回的信息；缺失字段应询问用户，不得猜测。\n"
        "6. 读取表格时必须区分数值 0 与空单元格：0 是真实数据，必须原样"
        "提交；只有原始单元格为空时才使用 null。每条 WBS 都要明确提交"
        "上级编码、计划开始、计划完成、进度、状态和优先级，缺失项填 null。\n"
        "7. WBS 编码表示层级和同级自然顺序，但不表示前置依赖。上级编码只能"
        "由点分编码的直接前缀确定，根节点上级必须为 null；层级等于编码段数。"
        "不得把空值改写成“顶级 WBS”“未提供”等文本。predecessor_wbs_codes "
        "只能来自附件或用户明确给出的前置关系；没有明确前置关系时必须传空"
        "数组，禁止根据相邻编码、名称或日期自行推断前置关系。\n"
        "8. WBS、风险和质量指标必须使用 WBS 编码建立关系，并在提交前检查"
        "父子编码、明确给出的前置工序和关联编码是否真实存在。同一上级下，"
        "按 WBS 编码自然顺序排列的工序，其计划开始时间不得倒退。附件中每一"
        "条带 WBS 编码的记录都必须提交，不得因为名称像占位符而静默丢弃。"
        "发现时间线、前置日期、父子关系或占位内容异常时必须保留原值并交给"
        "用户核对，不得自行解释、补造依赖或改写原始计划。\n"
        "9. 提交和增量更新工具都只保存待确认草稿，不会写入正式业务表；"
        "不得声称已经入库。\n"
        "10. 必须检查草稿工具返回的校验结果。只要存在错误或警告，就要在回复"
        "中简要说明发现了哪些问题，并明确提示用户点击 Dobby 平台中的“核对"
        "草稿”查看、修正或确认；不得只说整理完成，也不得把问题隐藏在工具"
        "结果中。\n"
        "11. 用户必须在 Dobby 平台核对并确认草稿后，平台才会执行正式写入；"
        "你不能绕过这一确认步骤，也不能创建登录账号或设置初始密码。\n"
        "</project-initialization-role>"
    )


def _build_agent_project_context(
    db: Session,
    project: Project,
    user: User,
) -> str:
    """Build a bounded, read-only project snapshot for one agent turn."""
    wbs_items = db.scalars(
        select(WbsItem)
        .where(WbsItem.project_id == project.id)
        .order_by(WbsItem.sort_order, WbsItem.wbs_code)
        .limit(30),
    ).all()
    risks = db.scalars(
        select(RiskSource)
        .where(RiskSource.project_id == project.id)
        .order_by(RiskSource.updated_at.desc())
        .limit(20),
    ).all()
    tasks = db.scalars(
        select(Task)
        .where(Task.project_id == project.id)
        .order_by(Task.updated_at.desc())
        .limit(30),
    ).all()
    documents = db.execute(
        select(Attachment, AttachmentText.content)
        .outerjoin(
            AttachmentText,
            AttachmentText.attachment_id == Attachment.id,
        )
        .where(Attachment.project_id == project.id)
        .order_by(Attachment.updated_at.desc())
        .limit(12),
    ).all()
    document_summaries: list[str] = []
    for attachment, extracted_text in documents:
        summary = f"{attachment.file_name}（{attachment.category}）"
        compact_text = " ".join((extracted_text or "").split())
        if compact_text:
            summary += f"：{compact_text[:1200]}"
        document_summaries.append(summary)
    return (
        "<platform-context>\n"
        "以下内容由工程管理平台后端按当前登录用户和项目权限注入，只能作为"
        "本次任务的项目事实；不得假设用户拥有未列出的项目或权限。\n"
        f"当前用户：{user.real_name}（用户ID {user.id}，系统角色 {user.role}）\n"
        f"当前项目：{project.name}（项目ID {project.id}）\n"
        "工程类型说明："
        f"{(project.engineering_type_description or '未填写')[:500]}\n"
        "参建单位："
        f"建设单位={project.construction_unit_name or '未填写'}；"
        f"总包单位={project.general_contractor_unit_name or '未填写'}；"
        f"监理单位={project.supervision_unit_name or '未填写'}；"
        f"设计单位={project.design_unit_name or '未填写'}；"
        f"勘察单位={project.survey_unit_name or '未填写'}\n"
        "WBS："
        + (
            "；".join(
                f"{item.wbs_code} {item.name}"
                f"（进度{item.progress_percent or 0}%／"
                f"{item.status_text or '未设置'}）"
                for item in wbs_items
            )
            or "暂无"
        )
        + "\n风险源："
        + (
            "；".join(
                f"{item.serial_no} {item.risk_part}"
                f"（{item.risk_level}／{item.related_process_name}）"
                for item in risks
            )
            or "暂无"
        )
        + "\n近期任务："
        + (
            "；".join(
                f"{item.title}（{item.status}，截止{item.due_at or '未设置'}）"
                for item in tasks
            )
            or "暂无"
        )
        + "\n工程资料："
        + (
            "；".join(
                item
                for item in document_summaries
            )
            or "暂无"
        )
        + "\n</platform-context>"
    )


def _agent_reply_extra_data(
    reply: AgentScopeReply,
    trace_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the durable, UI-facing runtime payload for one platform reply."""
    runtime_messages = reply.raw_messages or (
        [reply.raw_message] if reply.raw_message else []
    )
    result: dict[str, Any] = {
        "status": reply.status,
        "agentscope_message": reply.raw_message,
        "agentscope_messages": runtime_messages,
    }
    if trace_summary:
        result["runtime_trace"] = trace_summary
    return result


def _persist_agent_reply(
    conversation_id: int,
    reply: AgentScopeReply,
    trace_summary: dict[str, Any] | None = None,
    *,
    audit_new: bool = True,
) -> dict[str, Any] | None:
    """Persist a streamed AgentScope reply using a fresh DB session.

    Streaming responses outlive the request-scoped SQLAlchemy session.  A
    fresh session also lets completion continue after the browser disconnects.
    The AgentScope message id is used as an idempotency key so a resumed
    permission request updates its parked message instead of duplicating it.
    """
    with SessionLocal() as db:
        conversation = db.get(AgentConversation, conversation_id)
        if conversation is None:
            return None
        assistant: AgentConversationMessage | None = None
        if reply.message_id:
            assistant = db.scalar(
                select(AgentConversationMessage).where(
                    AgentConversationMessage.conversation_id
                    == conversation_id,
                    AgentConversationMessage.agentscope_message_id
                    == reply.message_id,
                ),
            )
        is_new = assistant is None
        if assistant is None:
            assistant = AgentConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=reply.content,
                agentscope_message_id=reply.message_id,
                extra_data={},
            )
            db.add(assistant)
        assistant.content = reply.content
        assistant.extra_data = {
            **(assistant.extra_data or {}),
            **_agent_reply_extra_data(reply, trace_summary),
        }
        conversation.status = reply.status
        conversation.last_error = None
        conversation.updated_at = datetime.now(UTC)
        user = db.get(User, conversation.user_id)
        if is_new and user is not None and audit_new:
            audit(
                db,
                user,
                "调用智能体",
                f"调用「{conversation.agent_name}」处理平台消息",
                conversation.project_id,
                "agent_conversation",
                conversation.id,
            )
        db.commit()
        db.refresh(assistant)
        return serialize(assistant)


def _agentscope_assistant_groups(
    messages: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Group assistant replies belonging to each AgentScope user turn."""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        if role == "user":
            if current:
                groups.append(current)
                current = []
        elif role == "assistant":
            current.append(message)
    if current:
        groups.append(current)
    return groups


def _agentscope_reply_from_group(
    messages: list[dict[str, Any]],
    live_status: str,
) -> AgentScopeReply:
    """Project one AgentScope turn into the platform's durable reply shape."""
    last = messages[-1]
    finished_reason = str(last.get("finished_reason") or "")
    if last.get("error") or finished_reason == "error":
        status_value = "error"
    elif finished_reason == "interrupted":
        status_value = "interrupted"
    elif last.get("finished_at") is not None:
        status_value = "completed"
    else:
        status_value = live_status
    content = AgentScopeClient._message_text(last)
    if not content:
        content = (
            "智能体执行已中断，未产生可显示的文本。"
            if status_value == "interrupted"
            else "智能体尚未产生可显示的文本。"
        )
    return AgentScopeReply(
        status=status_value,
        content=content,
        message_id=(
            str(last.get("id"))
            if last.get("id") is not None
            else None
        ),
        raw_message=last,
        raw_messages=messages,
    )


def _reconcile_agent_conversation_messages(
    conversation: AgentConversation,
) -> None:
    """Recover finished/parked AgentScope replies missing from platform DB."""
    if not conversation.agentscope_session_id:
        return
    client = _agentscope_client()
    live_status = client.session_status(
        conversation.agentscope_session_id,
        conversation.agent_id,
    )
    # The active SSE request owns persistence while a turn is running.
    # Reconciliation is for interrupted/disconnected/parked/finished turns.
    # Parked statuses are intentionally included by the caller: an interrupt
    # can race with the original SSE persistence and temporarily restore
    # ``awaiting_permission`` after the interrupt endpoint set
    # ``interrupting``. Re-reading history must still reconcile the eventual
    # interrupted AgentScope message.
    if live_status == "running":
        return
    payload = client.list_messages(
        conversation.agentscope_session_id,
        conversation.agent_id,
    )
    messages = [
        item
        for item in payload.get("messages", [])
        if isinstance(item, dict)
    ]
    for group in _agentscope_assistant_groups(messages):
        _persist_agent_reply(
            conversation.id,
            _agentscope_reply_from_group(group, live_status),
            audit_new=False,
        )


def _record_agent_turn_error(conversation_id: int, detail: str) -> None:
    """Persist a transport/runtime failure after an SSE response has begun."""
    with SessionLocal() as db:
        conversation = db.get(AgentConversation, conversation_id)
        if conversation is None:
            return
        conversation.status = "error"
        conversation.last_error = detail
        conversation.updated_at = datetime.now(UTC)
        db.commit()


def _mark_agent_turn_running(conversation_id: int) -> None:
    """Persist that AgentScope accepted a resumed confirmation turn."""
    with SessionLocal() as db:
        conversation = db.get(AgentConversation, conversation_id)
        if conversation is None:
            return
        conversation.status = "running"
        conversation.last_error = None
        conversation.updated_at = datetime.now(UTC)
        db.commit()


def _sse_frame(event: str, data: Any) -> str:
    """Serialize one named Server-Sent Event frame."""
    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


async def _persist_agent_reply_after_disconnect(
    chat_task: asyncio.Task[AgentScopeReply],
    conversation_id: int,
    trace_summary: dict[str, Any],
) -> None:
    """Finish persistence when the browser closes an in-flight stream."""
    try:
        reply = await asyncio.shield(chat_task)
        if reply.projected:
            return
        await asyncio.to_thread(
            _persist_agent_reply,
            conversation_id,
            reply,
            trace_summary,
        )
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(
            _record_agent_turn_error,
            conversation_id,
            str(exc),
        )


@router.post("/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    return ok({"access_token": create_access_token(user.id, user.role), "token_type": "bearer", "user": serialize(user)})


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(serialize(user))


@router.patch("/me")
def update_me(payload: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    user.real_name = payload.real_name.strip()
    user.phone = payload.phone.strip() if payload.phone and payload.phone.strip() else None
    user.email = payload.email.strip() if payload.email and payload.email.strip() else None
    user.title = payload.title.strip() if payload.title and payload.title.strip() else None
    user.org_name = payload.org_name.strip() if payload.org_name and payload.org_name.strip() else None
    db.commit()
    db.refresh(user)
    return ok(serialize(user), "个人资料已保存")


@router.post("/me/password")
def change_my_password(payload: PasswordChangeInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与当前密码相同")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return ok(None, "登录密码已更新")


@router.get("/agents/catalog")
def get_agent_catalog(
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Expose AgentScope's safe publication catalogue to the platform UI."""
    try:
        catalog = _agentscope_client().get_catalog()
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    business_agents = [
        _public_agent_catalog_item(item)
        for item in catalog.get("business_agents", [])
    ]
    return ok(
        {
            "global_main": _public_agent_catalog_item(
                catalog.get("global_main"),
            ),
            "project_initializer": _public_agent_catalog_item(
                catalog.get("project_initializer"),
            ),
            "business_agents": business_agents,
            "total": len(business_agents),
        },
    )


@router.get("/projects/{project_id}/agent-conversations")
def list_agent_conversations(
    project_id: int,
    conversation_type: str | None = Query(
        default=None,
        pattern="^(general|business|initialization)$",
    ),
    agent_id: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    statement = select(AgentConversation).where(
        AgentConversation.project_id == project_id,
        AgentConversation.user_id == user.id,
    )
    if conversation_type:
        statement = statement.where(
            AgentConversation.conversation_type == conversation_type,
        )
    if conversation_type == "general" and not agent_id:
        try:
            selected_agent = _agentscope_client().get_catalog().get(
                "global_main",
            )
        except AgentScopeGatewayError as exc:
            _raise_agentscope_http_error(exc)
        if selected_agent is None:
            return ok([])
        statement = statement.where(
            AgentConversation.agent_id == str(selected_agent["id"]),
        )
    if agent_id:
        statement = statement.where(AgentConversation.agent_id == agent_id)
    if conversation_type == "initialization":
        statement = statement.order_by(AgentConversation.id.asc()).limit(1)
    else:
        statement = statement.order_by(AgentConversation.updated_at.desc())
    rows = db.scalars(statement).all()
    return ok([serialize(row) for row in rows])


@router.post("/projects/{project_id}/agent-conversations")
def create_agent_conversation(
    project_id: int,
    payload: AgentConversationInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    if payload.conversation_type == "initialization":
        existing = db.scalar(
            select(AgentConversation)
            .where(
                AgentConversation.project_id == project.id,
                AgentConversation.user_id == user.id,
                AgentConversation.conversation_type == "initialization",
            )
            .order_by(AgentConversation.id.asc()),
        )
        if existing is not None:
            return ok(serialize(existing), "已复用现有项目初始化会话")

    client = _agentscope_client()
    try:
        catalog = client.get_catalog()
        if payload.conversation_type == "general":
            selected_agent = catalog.get("global_main")
            if selected_agent is None:
                raise HTTPException(
                    status_code=409,
                    detail="AgentScope 尚未配置已启用的全局主智能体",
                )
        elif payload.conversation_type == "initialization":
            selected_agent = catalog.get("project_initializer")
            if selected_agent is None:
                raise HTTPException(
                    status_code=409,
                    detail="AgentScope 尚未配置已启用的项目初始化智能体",
                )
        else:
            if not payload.agent_id:
                raise HTTPException(
                    status_code=422,
                    detail="业务智能体会话必须提供 agent_id",
                )
            selected_agent = next(
                (
                    item
                    for item in catalog.get("business_agents", [])
                    if item.get("id") == payload.agent_id
                ),
                None,
            )
            if selected_agent is None:
                raise HTTPException(
                    status_code=404,
                    detail="该业务智能体未发布、已停用或不存在",
                )

        row = AgentConversation(
            project_id=project.id,
            user_id=user.id,
            agent_id=str(selected_agent["id"]),
            agent_name=str(selected_agent["name"]),
            conversation_type=payload.conversation_type,
            title=payload.title
            or (
                f"{selected_agent['name']} · {project.name}"
                if payload.conversation_type == "business"
                else (
                    f"{project.name} · 项目初始化"
                    if payload.conversation_type == "initialization"
                    else f"{project.name} · 智能协同"
                )
            ),
            status="creating",
        )
        db.add(row)
        db.flush()
        row.agentscope_session_id = client.create_session(
            agent=selected_agent,
            workspace_id=(
                f"platform-u{user.id}-p{project.id}-conversation-{row.id}"
            ),
            name=row.title,
        )
        row.status = "active"
        audit(
            db,
            user,
            "创建智能体会话",
            f"创建「{row.agent_name}」平台会话",
            project.id,
            "agent_conversation",
            row.id,
        )
        db.commit()
        db.refresh(row)
        return ok(serialize(row), "智能体会话已创建")
    except AgentScopeGatewayError as exc:
        db.rollback()
        _raise_agentscope_http_error(exc)


@router.get(
    "/projects/{project_id}/agent-conversations/{conversation_id}"
    "/initialization-files",
)
def list_project_initialization_files(
    project_id: int,
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if (
        conversation.project_id != project_id
        or conversation.conversation_type != "initialization"
    ):
        raise HTTPException(status_code=404, detail="项目初始化会话不存在")
    rows = db.scalars(
        select(ProjectInitializationFile)
        .where(
            ProjectInitializationFile.project_id == project_id,
            ProjectInitializationFile.conversation_id == conversation_id,
        )
        .order_by(ProjectInitializationFile.created_at),
    ).all()
    return ok([serialize(row) for row in rows])


@router.post(
    "/projects/{project_id}/agent-conversations/{conversation_id}"
    "/initialization-files",
)
def upload_project_initialization_file(
    project_id: int,
    conversation_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if (
        conversation.project_id != project_id
        or conversation.conversation_type != "initialization"
    ):
        raise HTTPException(status_code=404, detail="项目初始化会话不存在")
    safe_name = Path(file.filename or "attachment").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in INITIALIZATION_FILE_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=(
                "初始化附件仅支持 TXT、Markdown、CSV、XLSX、DOCX 和 PDF"
            ),
        )
    content = file.file.read(INITIALIZATION_FILE_MAX_BYTES + 1)
    if len(content) > INITIALIZATION_FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="单个初始化附件不能超过 30MB")
    digest = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(
        select(ProjectInitializationFile).where(
            ProjectInitializationFile.conversation_id == conversation.id,
            ProjectInitializationFile.file_name == safe_name,
            ProjectInitializationFile.file_hash == digest,
        ),
    )
    if duplicate is not None:
        return ok(
            _public_initialization_file(duplicate),
            "相同初始化附件已存在",
        )

    settings = get_settings()
    folder = (
        settings.upload_dir
        / "project-initialization"
        / str(project_id)
        / str(conversation_id)
    )
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (
        f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    )
    target.write_bytes(content)
    row = ProjectInitializationFile(
        project_id=project_id,
        conversation_id=conversation.id,
        uploaded_by_user_id=user.id,
        file_name=safe_name,
        storage_path=str(target),
        content_type=file.content_type,
        file_size=len(content),
        file_hash=digest,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        user,
        "上传项目初始化附件",
        f"上传初始化附件「{safe_name}」",
        project_id,
        "project_initialization_file",
        row.id,
    )
    db.commit()
    db.refresh(row)
    return ok(_public_initialization_file(row), "初始化附件已上传")


@router.delete("/project-initialization-files/{file_id}")
def delete_project_initialization_file(
    file_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.get(ProjectInitializationFile, file_id)
    if row is None:
        raise HTTPException(status_code=404, detail="初始化附件不存在")
    conversation = _agent_conversation_or_404(
        db,
        row.conversation_id,
        user,
    )
    if conversation.conversation_type != "initialization":
        raise HTTPException(status_code=404, detail="初始化附件不存在")
    path = Path(row.storage_path)
    db.delete(row)
    audit(
        db,
        user,
        "删除项目初始化附件",
        f"删除初始化附件「{row.file_name}」",
        row.project_id,
        "project_initialization_file",
        row.id,
    )
    db.commit()
    with suppress(OSError):
        path.unlink()
    return ok({}, "初始化附件已删除")


@router.get("/agent-conversations/{conversation_id}/messages")
def list_agent_conversation_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    reconciled = False
    if conversation.status in {
        "creating",
        "running",
        "interrupting",
        "awaiting_permission",
        "awaiting_external_result",
        "error",
    } or conversation.last_error:
        try:
            _reconcile_agent_conversation_messages(conversation)
            reconciled = True
        except AgentScopeGatewayError:
            # Local history must remain readable while AgentScope is
            # temporarily unavailable.
            pass
    if reconciled:
        # Reconciliation persists through a separate session so it can also
        # finish after an SSE client disconnects. End this request session's
        # earlier read transaction before selecting rows, otherwise SQLite
        # may return the pre-reconciliation message snapshot.
        db.rollback()
    rows = db.scalars(
        select(AgentConversationMessage)
        .where(AgentConversationMessage.conversation_id == conversation_id)
        .order_by(AgentConversationMessage.created_at),
    ).all()
    return ok([serialize(row) for row in rows])


@router.post("/agent-conversations/{conversation_id}/messages")
def create_agent_conversation_message(
    conversation_id: int,
    payload: AgentConversationMessageInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    project = project_for_user_or_403(db, conversation.project_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(
            status_code=409,
            detail="智能体会话尚未完成初始化",
        )

    client = _agentscope_client()
    try:
        catalog = client.get_catalog()
        selected_agent = _catalog_agent_for_conversation(
            catalog,
            conversation,
        )
        client.sync_session(
            agent=selected_agent,
            session_id=conversation.agentscope_session_id,
        )
    except AgentScopeGatewayError as exc:
        conversation.status = "error"
        conversation.last_error = str(exc)
        db.commit()
        _raise_agentscope_http_error(exc)

    initialization_files = _initialization_files_for_message(
        db,
        conversation,
        payload.initialization_file_ids,
    )
    user_message = AgentConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=payload.content,
        extra_data={
            "initialization_files": [
                {
                    "id": item.id,
                    "name": item.file_name,
                    "size": item.file_size,
                }
                for item in initialization_files
            ],
        },
    )
    db.add(user_message)
    db.flush()
    injected_content = (
        _build_agent_project_context(db, project, user)
        + _initialization_agent_instruction(conversation)
        + _initialization_file_context(initialization_files)
        + "\n<user-request>\n"
        + payload.content
        + "\n</user-request>"
    )
    try:
        reply = client.chat(
            agent_id=conversation.agent_id,
            session_id=conversation.agentscope_session_id,
            content=injected_content,
            sender_name=user.real_name,
            metadata={
                "source": "engineering_platform",
                "platform_user_id": user.id,
                "project_id": project.id,
                "conversation_id": conversation.id,
            },
        )
    except AgentScopeGatewayError as exc:
        conversation.status = "error"
        conversation.last_error = str(exc)
        db.commit()
        _raise_agentscope_http_error(exc)

    assistant = AgentConversationMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=reply.content,
        agentscope_message_id=reply.message_id,
        extra_data=_agent_reply_extra_data(reply),
    )
    db.add(assistant)
    conversation.status = reply.status
    conversation.last_error = None
    conversation.updated_at = datetime.now(UTC)
    audit(
        db,
        user,
        "调用智能体",
        f"调用「{conversation.agent_name}」处理平台消息",
        project.id,
        "agent_conversation",
        conversation.id,
    )
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant)
    db.refresh(conversation)
    return ok(
        {
            "conversation": serialize(conversation),
            "user_message": serialize(user_message),
            "message": serialize(assistant),
            "runtime_status": reply.status,
        },
        (
            "智能体处理完成"
            if reply.status == "completed"
            else "智能体等待进一步处理"
        ),
    )


@router.post("/agent-conversations/{conversation_id}/messages/stream")
def stream_agent_conversation_message(
    conversation_id: int,
    payload: AgentConversationMessageInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Relay one authorized AgentScope turn as structured SSE events."""
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    project = project_for_user_or_403(db, conversation.project_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(
            status_code=409,
            detail="智能体会话尚未完成初始化",
        )

    client = _agentscope_client()
    try:
        catalog = client.get_catalog()
        selected_agent = _catalog_agent_for_conversation(
            catalog,
            conversation,
        )
        client.sync_session(
            agent=selected_agent,
            session_id=conversation.agentscope_session_id,
        )
    except AgentScopeGatewayError as exc:
        conversation.status = "error"
        conversation.last_error = str(exc)
        db.commit()
        _raise_agentscope_http_error(exc)

    initialization_files = _initialization_files_for_message(
        db,
        conversation,
        payload.initialization_file_ids,
    )
    user_message = AgentConversationMessage(
        conversation_id=conversation.id,
        role="user",
        content=payload.content,
        extra_data={
            "initialization_files": [
                {
                    "id": item.id,
                    "name": item.file_name,
                    "size": item.file_size,
                }
                for item in initialization_files
            ],
        },
    )
    db.add(user_message)
    conversation.status = "running"
    conversation.last_error = None
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(user_message)

    injected_content = (
        _build_agent_project_context(db, project, user)
        + _initialization_agent_instruction(conversation)
        + _initialization_file_context(initialization_files)
        + "\n<user-request>\n"
        + payload.content
        + "\n</user-request>"
    )
    agent_id = conversation.agent_id
    session_id = conversation.agentscope_session_id
    sender_name = user.real_name
    metadata = {
        "source": "engineering_platform",
        "platform_user_id": user.id,
        "project_id": project.id,
        "conversation_id": conversation.id,
        "platform_message_id": user_message.id,
    }
    accepted_payload = {
        "conversation_id": conversation.id,
        "user_message": serialize(user_message),
        "runtime_status": "running",
    }

    async def relay() -> Any:
        chat_task: asyncio.Task[AgentScopeReply] | None = None
        event_task: asyncio.Task[dict[str, Any]] | None = None
        trace_summary: dict[str, Any] = {
            "model_names": [],
            "tasks_context": None,
            "team_update_count": 0,
            "subagent_hitl": [],
        }
        yield _sse_frame("accepted", accepted_payload)
        try:
            async with client.event_stream(session_id, agent_id) as events:
                event_task = asyncio.create_task(anext(events))
                await asyncio.sleep(0)
                chat_task = asyncio.create_task(
                    asyncio.to_thread(
                        client.chat,
                        agent_id=agent_id,
                        session_id=session_id,
                        content=injected_content,
                        sender_name=sender_name,
                        metadata=metadata,
                    ),
                )

                while True:
                    waiting: set[asyncio.Task[Any]] = {chat_task}
                    if event_task is not None:
                        waiting.add(event_task)
                    completed, _ = await asyncio.wait(
                        waiting,
                        timeout=15.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not completed:
                        # Keep browsers and reverse proxies from treating a
                        # quiet but still-running agent turn as a dead
                        # connection. SSE comments are ignored by the client.
                        yield ": dobby-agent-heartbeat\n\n"
                        continue

                    if event_task is not None and event_task in completed:
                        try:
                            runtime_event = event_task.result()
                        except StopAsyncIteration:
                            event_task = None
                        else:
                            event_type = str(runtime_event.get("type") or "")
                            if event_type == "MODEL_CALL_START":
                                model_name = str(
                                    runtime_event.get("model_name") or "",
                                )
                                if (
                                    model_name
                                    and model_name
                                    not in trace_summary["model_names"]
                                ):
                                    trace_summary["model_names"].append(
                                        model_name,
                                    )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "state_updated"
                            ):
                                value = runtime_event.get("value") or {}
                                trace_summary["tasks_context"] = value.get(
                                    "tasks_context",
                                )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "team_updated"
                            ):
                                trace_summary["team_update_count"] += 1
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "subagent_require_user_confirm"
                            ):
                                value = runtime_event.get("value") or {}
                                key = (
                                    str(value.get("worker_session_id") or ""),
                                    str(value.get("reply_id") or ""),
                                )
                                trace_summary["subagent_hitl"] = [
                                    entry
                                    for entry in trace_summary["subagent_hitl"]
                                    if (
                                        str(
                                            entry.get(
                                                "worker_session_id",
                                            )
                                            or "",
                                        ),
                                        str(entry.get("reply_id") or ""),
                                    )
                                    != key
                                ]
                                trace_summary["subagent_hitl"].append(value)
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "subagent_user_confirm_result"
                            ):
                                value = runtime_event.get("value") or {}
                                key = (
                                    str(value.get("worker_session_id") or ""),
                                    str(value.get("reply_id") or ""),
                                )
                                trace_summary["subagent_hitl"] = [
                                    entry
                                    for entry in trace_summary["subagent_hitl"]
                                    if (
                                        str(
                                            entry.get(
                                                "worker_session_id",
                                            )
                                            or "",
                                        ),
                                        str(entry.get("reply_id") or ""),
                                    )
                                    != key
                                ]
                            yield _sse_frame("agent_event", runtime_event)
                            event_task = asyncio.create_task(anext(events))

                    if chat_task in completed:
                        reply = chat_task.result()
                        break

                if event_task is not None and not event_task.done():
                    event_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await event_task

            persisted = await asyncio.to_thread(
                _persist_agent_reply,
                conversation_id,
                reply,
                trace_summary,
            )
            if persisted is None:
                raise AgentScopeGatewayError(
                    "平台会话已被删除，无法保存智能体回复。",
                    status_code=409,
                )
            yield _sse_frame(
                "done",
                {
                    "message": persisted,
                    "runtime_status": reply.status,
                },
            )
        except asyncio.CancelledError:
            if chat_task is not None:
                asyncio.create_task(
                    _persist_agent_reply_after_disconnect(
                        chat_task,
                        conversation_id,
                        trace_summary,
                    ),
                )
            raise
        except Exception as exc:  # noqa: BLE001
            if event_task is not None and not event_task.done():
                event_task.cancel()
            if chat_task is not None and not chat_task.done():
                asyncio.create_task(
                    _persist_agent_reply_after_disconnect(
                        chat_task,
                        conversation_id,
                        trace_summary,
                    ),
                )
            else:
                await asyncio.to_thread(
                    _record_agent_turn_error,
                    conversation_id,
                    str(exc),
                )
            status_code = (
                exc.status_code
                if isinstance(exc, AgentScopeGatewayError)
                else 500
            )
            yield _sse_frame(
                "error",
                {
                    "detail": str(exc),
                    "status_code": status_code,
                },
            )

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent-conversations/{conversation_id}/interrupt")
def interrupt_agent_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(status_code=409, detail="智能体会话尚未完成初始化")
    try:
        result = _agentscope_client().interrupt(
            agent_id=conversation.agent_id,
            session_id=conversation.agentscope_session_id,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    conversation.status = "interrupting"
    db.commit()
    return ok(result, "已请求停止智能体")


@router.post("/agent-conversations/{conversation_id}/confirm")
def confirm_agent_conversation_tool(
    conversation_id: int,
    payload: AgentConversationConfirmInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(status_code=409, detail="智能体会话尚未完成初始化")
    try:
        client = _agentscope_client()
        catalog = client.get_catalog()
        _catalog_agent_for_conversation(catalog, conversation)
        reply = client.confirm_tool_call(
            agent_id=conversation.agent_id,
            session_id=conversation.agentscope_session_id,
            reply_id=payload.reply_id,
            tool_call=payload.tool_call,
            confirmed=payload.confirmed,
            rules=payload.rules,
        )
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)
    if reply.projected:
        return ok(
            {
                "message": None,
                "runtime_status": reply.status,
            },
            reply.content,
        )
    persisted = _persist_agent_reply(conversation.id, reply)
    if persisted is None:
        raise HTTPException(status_code=409, detail="平台智能体会话已被删除")
    return ok(
        {
            "message": persisted,
            "runtime_status": reply.status,
        },
        "人工确认结果已处理",
    )


@router.post("/agent-conversations/{conversation_id}/confirm/stream")
def stream_agent_conversation_tool_confirmation(
    conversation_id: int,
    payload: AgentConversationConfirmInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Submit a HITL decision and relay the resumed AgentScope turn."""
    conversation = _agent_conversation_or_404(db, conversation_id, user)
    if not conversation.agentscope_session_id:
        raise HTTPException(status_code=409, detail="智能体会话尚未完成初始化")

    client = _agentscope_client()
    try:
        catalog = client.get_catalog()
        _catalog_agent_for_conversation(catalog, conversation)
    except AgentScopeGatewayError as exc:
        _raise_agentscope_http_error(exc)

    agent_id = conversation.agent_id
    session_id = conversation.agentscope_session_id

    accepted_payload = {
        "conversation_id": conversation.id,
        "runtime_status": "running",
        "message": (
            f"已允许「{payload.tool_call.get('name', '工具')}」，"
            "智能体正在继续执行。"
            if payload.confirmed
            else f"已拒绝「{payload.tool_call.get('name', '工具')}」，"
            "智能体正在处理确认结果。"
        ),
    }

    async def relay() -> Any:
        confirm_task: asyncio.Task[AgentScopeReply] | None = None
        event_task: asyncio.Task[dict[str, Any]] | None = None
        reply_handed_off = False
        trace_summary: dict[str, Any] = {
            "model_names": [],
            "tasks_context": None,
            "team_update_count": 0,
            "subagent_hitl": [],
        }
        try:
            async with client.event_stream(session_id, agent_id) as events:
                submission = await asyncio.to_thread(
                    client.submit_tool_confirmation,
                    agent_id=agent_id,
                    session_id=session_id,
                    reply_id=payload.reply_id,
                    tool_call=payload.tool_call,
                    confirmed=payload.confirmed,
                    rules=payload.rules,
                )
                await asyncio.to_thread(
                    _mark_agent_turn_running,
                    conversation_id,
                )
                confirm_task = asyncio.create_task(
                    asyncio.to_thread(
                        client.wait_for_tool_confirmation,
                        agent_id=agent_id,
                        session_id=session_id,
                        reply_id=payload.reply_id,
                        tool_call=payload.tool_call,
                        submission=submission,
                    ),
                )
                event_task = asyncio.create_task(anext(events))
                # Do not acknowledge until AgentScope has validated that this
                # exact tool call is still waiting and accepted the decision.
                yield _sse_frame("accepted", accepted_payload)

                while True:
                    waiting: set[asyncio.Task[Any]] = {confirm_task}
                    if event_task is not None:
                        waiting.add(event_task)
                    completed, _ = await asyncio.wait(
                        waiting,
                        timeout=15.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not completed:
                        yield ": dobby-agent-heartbeat\n\n"
                        continue

                    if event_task is not None and event_task in completed:
                        try:
                            runtime_event = event_task.result()
                        except StopAsyncIteration:
                            event_task = None
                        else:
                            event_type = str(runtime_event.get("type") or "")
                            if event_type == "MODEL_CALL_START":
                                model_name = str(
                                    runtime_event.get("model_name") or "",
                                )
                                if (
                                    model_name
                                    and model_name
                                    not in trace_summary["model_names"]
                                ):
                                    trace_summary["model_names"].append(
                                        model_name,
                                    )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "state_updated"
                            ):
                                value = runtime_event.get("value") or {}
                                trace_summary["tasks_context"] = value.get(
                                    "tasks_context",
                                )
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "team_updated"
                            ):
                                trace_summary["team_update_count"] += 1
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "subagent_require_user_confirm"
                            ):
                                value = runtime_event.get("value") or {}
                                key = (
                                    str(value.get("worker_session_id") or ""),
                                    str(value.get("reply_id") or ""),
                                )
                                trace_summary["subagent_hitl"] = [
                                    entry
                                    for entry in trace_summary[
                                        "subagent_hitl"
                                    ]
                                    if (
                                        str(
                                            entry.get("worker_session_id")
                                            or "",
                                        ),
                                        str(entry.get("reply_id") or ""),
                                    )
                                    != key
                                ]
                                trace_summary["subagent_hitl"].append(value)
                            elif (
                                event_type == "CUSTOM"
                                and runtime_event.get("name")
                                == "subagent_user_confirm_result"
                            ):
                                value = runtime_event.get("value") or {}
                                key = (
                                    str(value.get("worker_session_id") or ""),
                                    str(value.get("reply_id") or ""),
                                )
                                trace_summary["subagent_hitl"] = [
                                    entry
                                    for entry in trace_summary[
                                        "subagent_hitl"
                                    ]
                                    if (
                                        str(
                                            entry.get("worker_session_id")
                                            or "",
                                        ),
                                        str(entry.get("reply_id") or ""),
                                    )
                                    != key
                                ]
                            yield _sse_frame("agent_event", runtime_event)
                            event_task = asyncio.create_task(anext(events))

                    if confirm_task in completed:
                        reply = confirm_task.result()
                        break

                if event_task is not None and not event_task.done():
                    event_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await event_task

            if reply.projected:
                reply_handed_off = True
                yield _sse_frame(
                    "done",
                    {
                        "message": None,
                        "runtime_status": reply.status,
                    },
                )
                return

            persisted = await asyncio.to_thread(
                _persist_agent_reply,
                conversation_id,
                reply,
                trace_summary,
            )
            if persisted is None:
                raise AgentScopeGatewayError(
                    "平台会话已被删除，无法保存智能体回复。",
                    status_code=409,
                )
            reply_handed_off = True
            yield _sse_frame(
                "done",
                {
                    "message": persisted,
                    "runtime_status": reply.status,
                },
            )
        except asyncio.CancelledError:
            if confirm_task is not None:
                asyncio.create_task(
                    _persist_agent_reply_after_disconnect(
                        confirm_task,
                        conversation_id,
                        trace_summary,
                    ),
                )
                reply_handed_off = True
            raise
        except Exception as exc:  # noqa: BLE001
            if event_task is not None and not event_task.done():
                event_task.cancel()
            if confirm_task is not None and not confirm_task.done():
                asyncio.create_task(
                    _persist_agent_reply_after_disconnect(
                        confirm_task,
                        conversation_id,
                        trace_summary,
                    ),
                )
                reply_handed_off = True
            elif confirm_task is not None:
                await asyncio.to_thread(
                    _record_agent_turn_error,
                    conversation_id,
                    str(exc),
                )
                reply_handed_off = True
            status_code = (
                exc.status_code
                if isinstance(exc, AgentScopeGatewayError)
                else 500
            )
            yield _sse_frame(
                "error",
                {
                    "detail": str(exc),
                    "status_code": status_code,
                },
            )
        finally:
            if event_task is not None and not event_task.done():
                event_task.cancel()
                with suppress(asyncio.CancelledError):
                    await event_task
            if confirm_task is not None and not reply_handed_off:
                asyncio.create_task(
                    _persist_agent_reply_after_disconnect(
                        confirm_task,
                        conversation_id,
                        trace_summary,
                    ),
                )

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok([serialize(row) for row in db.scalars(select(Project).order_by(Project.updated_at.desc())).all()])


@router.post("/projects")
def create_project(payload: ProjectInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_name = payload.name.strip()
    if not project_name:
        raise HTTPException(status_code=422, detail="项目名称不能为空")
    project = Project(name=project_name)
    db.add(project); db.flush()
    audit(db, user, "创建项目", f"创建项目「{project.name}」", project.id, "project", project.id)
    db.commit(); db.refresh(project)
    return ok(serialize(project), "项目已创建")


@router.patch("/projects/{project_id}")
def update_project(project_id: int, payload: ProjectInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    project_name = payload.name.strip()
    if not project_name:
        raise HTTPException(status_code=422, detail="项目名称不能为空")
    project.name = project_name
    audit(db, user, "更新项目", f"更新项目「{project.name}」", project.id, "project", project.id)
    db.commit(); db.refresh(project)
    return ok(serialize(project), "项目已更新")


@router.get("/projects/{project_id}/initialization-state")
def get_project_initialization_state(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    return ok(build_initialization_state(db, project))


def _initialization_draft_review(
    db: Session,
    draft: ProjectInitializationDraft,
) -> dict[str, Any]:
    data = serialize(draft)
    payload = draft.payload if isinstance(draft.payload, dict) else {}
    personnel = (
        payload.get("personnel", [])
        if isinstance(payload.get("personnel", []), list)
        else []
    )
    identity_cards = [
        str(item.get("identity_card_no"))
        for item in personnel
        if isinstance(item, dict) and item.get("identity_card_no")
    ]
    existing_cards = set(
        db.scalars(
            select(User.identity_card_no).where(
                User.identity_card_no.in_(identity_cards),
            ),
        ).all(),
    ) if identity_cards else set()
    data["required_personnel_credentials"] = [
        {
            "identity_card_no": str(item["identity_card_no"]),
            "real_name": str(item.get("real_name") or ""),
            "position_name": str(item.get("position_name") or ""),
        }
        for item in personnel
        if (
            isinstance(item, dict)
            and item.get("identity_card_no")
            and str(item["identity_card_no"]) not in existing_cards
        )
    ]
    data["summary"] = {
        "project_fields": sum(
            value not in (None, "")
            for value in (
                payload.get("project", {}).values()
                if isinstance(payload.get("project"), dict)
                else []
            )
        ),
        "personnel": len(personnel),
        "wbs": len(payload.get("wbs", []))
        if isinstance(payload.get("wbs"), list)
        else 0,
        "risks": len(payload.get("risks", []))
        if isinstance(payload.get("risks"), list)
        else 0,
        "quality_requirements": len(payload.get("quality_requirements", []))
        if isinstance(payload.get("quality_requirements"), list)
        else 0,
    }
    return data


@router.get("/projects/{project_id}/initialization-drafts/latest")
def get_latest_project_initialization_draft(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    draft = db.scalar(
        select(ProjectInitializationDraft)
        .where(ProjectInitializationDraft.project_id == project_id)
        .order_by(ProjectInitializationDraft.updated_at.desc()),
    )
    return ok(_initialization_draft_review(db, draft) if draft else None)


@router.get("/projects/{project_id}/initialization-drafts/{draft_id}")
def get_project_initialization_draft(
    project_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    project_for_user_or_403(db, project_id, user)
    draft = db.get(ProjectInitializationDraft, draft_id)
    if draft is None or draft.project_id != project_id:
        raise HTTPException(status_code=404, detail="初始化草稿不存在")
    return ok(_initialization_draft_review(db, draft))


@router.post("/projects/{project_id}/initialization-drafts/{draft_id}/apply")
def apply_project_initialization_draft(
    project_id: int,
    draft_id: int,
    payload: ApplyInitializationDraftInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict[str, Any]:
    project = project_for_user_or_403(db, project_id, user)
    draft = db.get(ProjectInitializationDraft, draft_id)
    if draft is None or draft.project_id != project_id:
        raise HTTPException(status_code=404, detail="初始化草稿不存在")
    try:
        result = apply_initialization_draft(db, draft, payload)
        audit(
            db,
            user,
            "确认项目初始化草稿",
            f"确认初始化草稿第 {draft.revision} 版并写入项目",
            project.id,
            "project_initialization_draft",
            draft.id,
        )
        db.commit()
        db.refresh(draft)
    except InitializationApplyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "issues": exc.issues},
        ) from exc
    return ok(
        {
            "draft": serialize(draft),
            "result": result,
            "initialization_state": build_initialization_state(db, project),
        },
        "项目初始化数据已确认入库",
    )


@router.get("/projects/{project_id}/settings")
def get_project_settings(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    row = db.get(ProjectSettings, project_id)
    return ok(serialize(row) if row else {"project_id": project_id, "main_dir": "", "archive_dir": "", "temp_dir": "", "failed_dir": "", "backup_dir": "", "scan_interval": 30, "enabled": False, "reminder_rules": []})


@router.put("/projects/{project_id}/settings")
def save_project_settings(project_id: int, payload: ProjectSettingsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    row = db.get(ProjectSettings, project_id)
    if not row:
        row = ProjectSettings(project_id=project_id)
        db.add(row)
    for key, value in payload.model_dump().items(): setattr(row, key, value)
    db.flush(); audit(db, user, "更新目录与预警配置", "更新资料目录监控及预警规则", project_id, "project_settings", project_id)
    db.commit(); db.refresh(row)
    return ok(serialize(row), "目录与预警配置已保存")


def refresh_project_notifications(project_id: int, db: Session) -> None:
    overdue = db.scalars(select(Task).where(Task.project_id == project_id, Task.status == "overdue")).all()
    waiting_dailies = db.scalars(select(DailyReport).where(DailyReport.project_id == project_id, DailyReport.status == "pending_confirm")).all()
    for task in overdue:
        exists = db.scalar(select(Notification).where(Notification.project_id == project_id, Notification.source_type == "task", Notification.source_id == task.id, Notification.notification_type == "overdue"))
        if not exists: db.add(Notification(project_id=project_id, notification_type="overdue", title="任务已逾期", content=task.title, priority="high", source_type="task", source_id=task.id))
    for report in waiting_dailies:
        exists = db.scalar(select(Notification).where(Notification.project_id == project_id, Notification.source_type == "daily_report", Notification.source_id == report.id, Notification.notification_type == "daily_confirm"))
        if not exists: db.add(Notification(project_id=project_id, notification_type="daily_confirm", title="日报待确认", content=report.file_name, priority="normal", source_type="daily_report", source_id=report.id))
    db.commit()


@router.get("/projects/{project_id}/dashboard")
def project_dashboard(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); refresh_project_notifications(project_id, db)
    wbs = db.scalars(select(WbsItem).where(WbsItem.project_id == project_id)).all()
    tasks = db.scalars(select(Task).where(Task.project_id == project_id)).all()
    risks = db.scalars(select(RiskSource).where(RiskSource.project_id == project_id)).all()
    metrics = db.scalars(select(QualityMetric).where(QualityMetric.project_id == project_id)).all()
    changes = db.scalars(select(ProjectChange).where(ProjectChange.project_id == project_id, ProjectChange.status != "closed")).all()
    notifications = db.scalars(select(Notification).where(Notification.project_id == project_id, Notification.is_read.is_(False))).all()
    snapshot = db.get(ProjectStatusSnapshot, project_id)
    if snapshot:
        return ok({"progress_rate": snapshot.progress_rate, "progress_status": snapshot.progress_status, "planned_delta": snapshot.planned_delta,
                   "risk_warnings": snapshot.risk_warnings, "safety_issues": snapshot.safety_issues, "quality_issues": snapshot.quality_issues,
                   "task_completion_rate": snapshot.task_completion_rate, "open_changes": len(changes), "unread_notifications": len(notifications),
                   "main_risk": snapshot.main_risk, "main_safety": snapshot.main_safety, "main_quality": snapshot.main_quality, "overall": snapshot.overall})
    done = sum(1 for task in tasks if task.status == "completed")
    return ok({"progress_rate": round(sum(item.progress for item in wbs) / len(wbs)) if wbs else 0, "progress_status": "正常", "planned_delta": "基本一致", "risk_warnings": sum(1 for risk in risks if risk.level in {"critical", "high"}), "safety_issues": sum(1 for risk in risks if "安全" in risk.risk_type), "quality_issues": sum(1 for metric in metrics if metric.status != "passed"), "task_completion_rate": round(done * 100 / len(tasks)) if tasks else 0, "open_changes": len(changes), "unread_notifications": len(notifications), "main_risk": next((risk.name for risk in risks if risk.level in {"critical", "high"}), "暂无重大风险"), "main_safety": "暂无新增安全隐患", "main_quality": next((metric.name for metric in metrics if metric.status != "passed"), "暂无待核查质量项"), "overall": "项目整体状态待核对"})


@router.get("/projects/{project_id}/information-records")
def list_information_records(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    rows = db.scalars(select(ProjectInformationRecord).where(ProjectInformationRecord.project_id == project_id).order_by(ProjectInformationRecord.recorded_at.desc(), ProjectInformationRecord.id.desc())).all()
    return ok([serialize(row) for row in rows])


@router.post("/information-records/{record_id}/dispose")
def dispose_information_record(record_id: int, payload: ProjectInformationDispositionInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, ProjectInformationRecord, record_id, "信息记录不存在")
    action_status = {"confirm": "已确认", "deny": "已否认", "revise": "已修订"}
    if payload.action == "revise" and not (payload.content or "").strip():
        raise HTTPException(status_code=422, detail="修订信息不能为空")
    row.status = action_status[payload.action]
    if payload.action == "revise":
        row.content = payload.content.strip()
    audit(db, user, f"信息{action_status[payload.action]}", f"处置项目最新信息「{row.source_name}」", row.project_id, "project_information_record", row.id)
    db.commit(); db.refresh(row)
    return ok(serialize(row), f"信息已{action_status[payload.action]}")


@router.get("/projects/{project_id}/changes")
def list_project_changes(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(ProjectChange, project_id, db))


@router.post("/projects/{project_id}/changes")
def create_project_change(project_id: int, payload: ProjectChangeInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); row = ProjectChange(project_id=project_id, **payload.model_dump()); db.add(row); db.flush()
    audit(db, user, "登记工程变更", f"登记变更「{row.title}」", project_id, "project_change", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "工程变更已登记")


@router.get("/projects/{project_id}/notifications")
def list_notifications(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); refresh_project_notifications(project_id, db)
    rows = db.scalars(select(Notification).where(Notification.project_id == project_id).order_by(Notification.created_at.desc())).all()
    return ok([serialize(row) for row in rows])


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, Notification, notification_id, "通知不存在"); row.is_read = True; db.commit(); db.refresh(row)
    return ok(serialize(row), "通知已标记已读")


@router.get("/projects/{project_id}/members")
def list_members(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    members = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)).all()
    data = []
    for member in members:
        item = serialize(member); item["user"] = serialize(entity_or_404(db, User, member.user_id, "用户不存在")); data.append(item)
    return ok(data)


@router.post("/projects/{project_id}/members")
def add_member(project_id: int, payload: MemberInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    account = db.scalar(select(User).where(User.username == payload.username)) if payload.username else None
    if not account:
        username = payload.username or f"user_{int(datetime.now(UTC).timestamp())}"
        account = User(username=username, password_hash=hash_password(payload.password or "ChangeMe123!"), real_name=payload.real_name, phone=payload.phone, email=payload.email, title=payload.title, role=payload.system_role)
        db.add(account); db.flush()
    member = ProjectMember(project_id=project_id, user_id=account.id, member_role=payload.member_role, display_name=payload.real_name, phone=payload.phone, responsibilities=payload.responsibilities)
    db.add(member); db.flush(); audit(db, user, "添加项目成员", f"添加成员「{payload.real_name}」", project_id, "project_member", member.id)
    db.commit(); db.refresh(member)
    return ok(serialize(member), "成员已添加")


@router.patch("/projects/{project_id}/members/{user_id}")
def update_member(project_id: int, user_id: int, payload: MemberInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
    if not member: raise HTTPException(status_code=404, detail="项目成员不存在")
    account = entity_or_404(db, User, user_id, "用户不存在")
    account.real_name = payload.real_name
    account.phone = payload.phone
    account.email = payload.email
    account.title = payload.title
    member.display_name = payload.real_name
    member.phone = payload.phone
    member.member_role = payload.member_role
    member.responsibilities = payload.responsibilities
    audit(db, user, "更新项目成员", f"更新成员「{payload.real_name}」", project_id, "project_member", member.id)
    db.commit(); db.refresh(member)
    return ok(serialize(member), "成员已更新")


def list_for_project(model: type[ModelType], project_id: int, db: Session) -> list[dict[str, Any]]:
    project_or_404(db, project_id)
    return [serialize(row) for row in db.scalars(select(model).where(model.project_id == project_id).order_by(model.id.desc())).all()]


@router.get("/projects/{project_id}/wbs")
def list_wbs(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(WbsItem, project_id, db))


@router.post("/projects/{project_id}/wbs")
def create_wbs(project_id: int, payload: WbsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = WbsItem(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增WBS工序", f"新增工序「{item.name}」", project_id, "wbs", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "WBS工序已添加")


@router.patch("/wbs/{item_id}")
def update_wbs(item_id: int, payload: WbsInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, WbsItem, item_id, "WBS工序不存在")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    audit(db, user, "更新WBS工序", f"更新工序「{item.name}」", item.project_id, "wbs", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "WBS工序已更新")


@router.get("/projects/{project_id}/risks")
def list_risks(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(RiskSource, project_id, db))


@router.post("/projects/{project_id}/risks")
def create_risk(project_id: int, payload: RiskInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = RiskSource(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增风险源", f"新增风险源「{item.name}」", project_id, "risk", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "风险源已添加")


@router.patch("/risks/{risk_id}")
def update_risk(risk_id: int, payload: RiskInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, RiskSource, risk_id, "风险源不存在")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    audit(db, user, "更新风险源", f"更新风险源「{item.name}」", item.project_id, "risk", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "风险源已更新")


@router.get("/projects/{project_id}/quality-metrics")
def list_quality_metrics(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(QualityMetric, project_id, db))


@router.post("/projects/{project_id}/quality-metrics")
def create_quality_metric(project_id: int, payload: QualityMetricInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id)
    if payload.wbs_item_id: entity_or_404(db, WbsItem, payload.wbs_item_id, "WBS工序不存在")
    item = QualityMetric(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增质量指标", f"新增质量指标「{item.name}」", project_id, "quality_metric", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "质量指标已添加")


@router.patch("/quality-metrics/{metric_id}")
def update_quality_metric(metric_id: int, payload: QualityMetricInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, QualityMetric, metric_id, "质量指标不存在")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    audit(db, user, "更新质量指标", f"更新质量指标「{item.name}」", item.project_id, "quality_metric", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "质量指标已更新")


@router.get("/projects/{project_id}/platform-field-mappings")
def list_platform_mappings(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(PlatformFieldMapping, project_id, db))


@router.post("/projects/{project_id}/platform-field-mappings")
def create_platform_mapping(project_id: int, payload: PlatformFieldMappingInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = PlatformFieldMapping(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "新增平台字段映射", f"新增「{item.platform_name}」字段映射", project_id, "platform_mapping", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "字段映射已添加")


@router.patch("/platform-field-mappings/{mapping_id}")
def update_platform_mapping(mapping_id: int, payload: PlatformFieldMappingInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, PlatformFieldMapping, mapping_id, "字段映射不存在")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    audit(db, user, "更新平台字段映射", f"更新「{item.platform_name}」字段映射", item.project_id, "platform_mapping", item.id)
    db.commit(); db.refresh(item)
    return ok(serialize(item), "字段映射已更新")


@router.delete("/platform-field-mappings/{mapping_id}")
def delete_platform_mapping(mapping_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, PlatformFieldMapping, mapping_id, "字段映射不存在"); db.delete(item)
    audit(db, user, "删除平台字段映射", f"删除「{item.platform_name}」字段映射", item.project_id, "platform_mapping", item.id); db.commit()
    return ok({}, "字段映射已删除")


@router.get("/projects/{project_id}/wbs-risk-links")
def list_links(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(WbsRiskLink, project_id, db))


@router.post("/projects/{project_id}/wbs-risk-links")
def create_link(project_id: int, payload: WbsRiskLinkInput, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    project_or_404(db, project_id); item = WbsRiskLink(project_id=project_id, **payload.model_dump()); db.add(item); db.flush()
    audit(db, user, "建立WBS风险关联", "建立工序与风险源关联", project_id, "wbs_risk_link", item.id); db.commit(); db.refresh(item)
    return ok(serialize(item), "关联已建立")


@router.delete("/wbs-risk-links/{link_id}")
def delete_link(link_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)) -> dict[str, Any]:
    item = entity_or_404(db, WbsRiskLink, link_id, "关联不存在"); db.delete(item)
    audit(db, user, "删除WBS风险关联", "删除工序与风险源关联", item.project_id, "wbs_risk_link", item.id); db.commit()
    return ok({}, "关联已删除")


@router.get("/projects/{project_id}/tasks")
def list_tasks(project_id: int, status_filter: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    open_tasks = db.scalars(select(Task).where(Task.project_id == project_id, Task.status.in_(["pending", "processing", "need_more_info", "pending_confirm"]))).all()
    today = date.today().isoformat()
    for task in open_tasks:
        if task.due_at and task.due_at[:10] < today:
            previous = task.status; task.status = "overdue"
            db.add(TaskStatusHistory(task_id=task.id, from_status=previous, to_status="overdue", note="系统根据截止日期自动标记逾期"))
            db.add(OperationLog(project_id=project_id, action="任务逾期提醒", detail=f"任务「{task.title}」已逾期", target_type="task", target_id=task.id))
    if any(task.due_at and task.due_at[:10] < today for task in open_tasks): db.commit()
    stmt = select(Task).where(Task.project_id == project_id)
    if status_filter: stmt = stmt.where(Task.status == status_filter)
    return ok([serialize(row) for row in db.scalars(stmt.order_by(Task.updated_at.desc())).all()])


@router.post("/projects/{project_id}/tasks/generate-flow")
def generate_task_flow(project_id: int, payload: TaskFlowGenerateInput, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    project_members = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.status == "active")).all()
    users = {row.id: row for row in db.scalars(select(User).where(User.id.in_([member.user_id for member in project_members]))).all()} if project_members else {}
    members = [{"id": member.user_id, "name": member.display_name or users.get(member.user_id).real_name if users.get(member.user_id) else member.display_name or f"成员{member.user_id}"} for member in project_members]
    wbs_items = db.scalars(select(WbsItem).where(WbsItem.project_id == project_id)).all()
    risks = db.scalars(select(RiskSource).where(RiskSource.project_id == project_id, RiskSource.status == "active")).all()
    fallback = build_fallback_task_flow(payload.requirement, payload.template_type, [member["id"] for member in members])
    settings = get_settings()
    generated: dict[str, Any] = fallback
    generated_by = "rules"
    model_error = ""

    if settings.ai_api_key:
        context = {
            "project": {"id": project.id, "name": project.project_name, "description": project.description},
            "members": members,
            "wbs_items": [{"id": item.id, "code": item.code, "name": item.name, "progress": item.progress, "status": item.status} for item in wbs_items],
            "risk_sources": [{"id": risk.id, "name": risk.name, "level": risk.level, "type": risk.risk_type} for risk in risks],
        }
        prompt = f"""你是 Dobby 工程项目任务流设计助手。根据用户需求和项目上下文，生成一个可执行、可追溯的任务流。
用户需求：{payload.requirement}
项目上下文：{json.dumps(context, ensure_ascii=False)}

只返回一个 JSON 对象，不要使用 Markdown。字段必须为：
title；task_type（仅 risk_alert/material_missing/daily_confirm/draft_review/fill_platform）；risk_level（仅 low/medium/high/critical）；assignee_user_id；confirmer_user_id；wbs_item_id；risk_source_id；run_mode（single/scheduled）；trigger_date（YYYY-MM-DD）；trigger_time（HH:mm）；trigger_rule；trigger_interval_value（正整数）；trigger_interval_unit（仅 hour/day/week/month）；cc；steps。
steps 必须有 2 至 8 个节点，每个节点字段为 name、owner_user_id、due_at（YYYY-MM-DD）、material。人员、WBS、风险只能使用上下文中存在的 id；不确定时返回 null。节点要按真实流转顺序排列，并包含执行、复核和闭环。"""
        try:
            response = httpx.post(
                f"{settings.ai_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.ai_api_key}"},
                json={"model": settings.ai_model, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": "你负责把工程任务需求转换为结构化任务流。"}, {"role": "user", "content": prompt}]},
                timeout=30,
            )
            response.raise_for_status()
            generated = extract_json_object(response.json()["choices"][0]["message"]["content"])
            generated_by = "ai"
        except Exception as exc:  # 模型连接异常时仍返回可编辑的规则流程，避免中断用户工作。
            model_error = str(exc)[:180]

    normalized = normalize_task_flow(generated, fallback, members, {item.id for item in wbs_items}, {risk.id for risk in risks})
    normalized["generated_by"] = generated_by
    normalized["generation_note"] = "Dobby 已根据需求和当前项目数据生成流程" if generated_by == "ai" else "当前使用规则模板生成，可继续手动调整" + (f"（模型暂不可用：{model_error}）" if model_error else "")
    return ok(normalized, "任务流已生成")


@router.post("/projects/{project_id}/tasks")
def create_task(project_id: int, payload: TaskInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); task = Task(project_id=project_id, **payload.model_dump()); db.add(task); db.flush()
    db.add(TaskStatusHistory(task_id=task.id, to_status="pending", changed_by=user.id, note="创建任务"))
    audit(db, user, "创建任务", f"创建任务「{task.title}」", project_id, "task", task.id); db.commit(); db.refresh(task)
    return ok(serialize(task), "任务已创建")


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    task = entity_or_404(db, Task, task_id, "任务不存在"); data = serialize(task)
    data["history"] = [serialize(row) for row in db.scalars(select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_id).order_by(TaskStatusHistory.created_at)).all()]
    return ok(data)


@router.post("/tasks/{task_id}/transition")
def transition_task(task_id: int, payload: TaskTransitionInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    task = entity_or_404(db, Task, task_id, "任务不存在")
    transitions = {
        "pending": {"processing", "cancelled"}, "processing": {"need_more_info", "pending_confirm", "cancelled"},
        "need_more_info": {"processing", "cancelled"}, "pending_confirm": {"processing", "completed", "cancelled"},
        "overdue": {"processing", "cancelled"}, "completed": set(), "cancelled": set(),
    }
    if payload.status not in transitions.get(task.status, set()): raise HTTPException(status_code=409, detail=f"任务当前为 {task.status}，不能流转到 {payload.status}")
    previous = task.status; task.status = payload.status
    db.add(TaskStatusHistory(task_id=task.id, from_status=previous, to_status=task.status, note=payload.note, changed_by=user.id))
    audit(db, user, "任务状态流转", f"任务「{task.title}」由 {previous} 变更为 {task.status}", task.project_id, "task", task.id); db.commit(); db.refresh(task)
    return ok(serialize(task), "任务状态已更新")


@router.post("/tasks/{task_id}/steps/{step_index}")
def update_task_step(task_id: int, step_index: int, payload: TaskStepUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    task = entity_or_404(db, Task, task_id, "任务不存在")
    steps = list(task.workflow_steps or [])
    if step_index < 0 or step_index >= len(steps): raise HTTPException(status_code=404, detail="任务步骤不存在")
    if payload.status not in {"pending", "processing", "completed", "blocked"}: raise HTTPException(status_code=422, detail="不支持的步骤状态")
    step = {**steps[step_index], "status": payload.status, "note": payload.note, "updated_at": datetime.now(UTC).isoformat(), "updated_by": user.id}
    steps[step_index] = step; task.workflow_steps = steps
    audit(db, user, "更新任务步骤", f"任务「{task.title}」步骤「{step.get('name', step_index + 1)}」更新为 {payload.status}", task.project_id, "task", task.id)
    if steps and all(item.get("status") == "completed" for item in steps) and task.status == "processing":
        previous = task.status; task.status = "pending_confirm"
        db.add(TaskStatusHistory(task_id=task.id, from_status=previous, to_status="pending_confirm", note="全部任务步骤已完成，等待复核", changed_by=user.id))
    db.commit(); db.refresh(task)
    return ok(serialize(task), "任务步骤已更新")


@router.post("/tasks/{task_id}/reassign")
def reassign_task(task_id: int, payload: TaskReassignInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    task = entity_or_404(db, Task, task_id, "任务不存在")
    project_member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == task.project_id, ProjectMember.user_id == payload.assignee_user_id))
    if not project_member:
        raise HTTPException(status_code=422, detail="转交人不属于当前项目")
    previous_assignee = task.assignee_user_id
    task.assignee_user_id = payload.assignee_user_id
    steps = list(task.workflow_steps or [])
    for index, step in enumerate(steps):
        if step.get("status") != "completed":
            steps[index] = {**step, "owner_user_id": str(payload.assignee_user_id)}
            break
    task.workflow_steps = steps
    note = payload.note or f"任务由用户 {previous_assignee or '未指派'} 转交给用户 {payload.assignee_user_id}"
    db.add(TaskStatusHistory(task_id=task.id, from_status=task.status, to_status=task.status, note=note, changed_by=user.id))
    audit(db, user, "转交任务", f"任务「{task.title}」转交给用户 {payload.assignee_user_id}", task.project_id, "task", task.id)
    db.commit(); db.refresh(task)
    return ok(serialize(task), "任务已转交")


@router.post("/tasks/{task_id}/notes")
def add_task_note(task_id: int, payload: TaskNoteInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    task = entity_or_404(db, Task, task_id, "任务不存在")
    note = payload.note.strip()
    if not note:
        raise HTTPException(status_code=422, detail="任务处理说明不能为空")
    db.add(TaskStatusHistory(task_id=task.id, from_status=task.status, to_status=task.status, note=note, changed_by=user.id))
    audit(db, user, "记录任务处置", f"任务「{task.title}」新增处理说明", task.project_id, "task", task.id)
    db.commit()
    return ok({"task_id": task.id}, "任务处理说明已记录")


@router.get("/projects/{project_id}/daily-reports")
def list_daily_reports(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(DailyReport, project_id, db))


@router.post("/projects/{project_id}/daily-reports")
def create_daily_report(project_id: int, payload: DailyReportInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); row = DailyReport(project_id=project_id, parse_status="parsed", **payload.model_dump()); db.add(row); db.flush()
    audit(db, user, "录入日报", f"录入日报「{row.file_name}」", project_id, "daily_report", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "日报已创建")


@router.patch("/daily-reports/{report_id}")
def update_daily_report(report_id: int, payload: DailyReportUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, DailyReport, report_id, "日报不存在")
    for key, value in payload.model_dump(exclude_none=True).items(): setattr(row, key, value)
    audit(db, user, "修正日报", f"修正日报「{row.file_name}」", row.project_id, "daily_report", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "日报已更新")


@router.post("/daily-reports/{report_id}/confirm")
def confirm_daily_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, DailyReport, report_id, "日报不存在"); row.status = "confirmed"
    audit(db, user, "确认日报", f"确认日报「{row.file_name}」", row.project_id, "daily_report", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "日报已确认")


@router.get("/projects/{project_id}/risk-drafts")
def list_drafts(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(RiskDraft, project_id, db))


@router.post("/projects/{project_id}/risk-drafts")
def create_draft(project_id: int, payload: DraftInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); entity_or_404(db, RiskSource, payload.risk_source_id, "风险源不存在")
    row = RiskDraft(project_id=project_id, **payload.model_dump()); db.add(row); db.flush()
    audit(db, user, "生成风险草稿", f"生成草稿「{row.title}」", project_id, "risk_draft", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "草稿已生成")


@router.post("/projects/{project_id}/risk-drafts/assist/{risk_id}")
def assist_risk_draft(project_id: int, risk_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); risk = entity_or_404(db, RiskSource, risk_id, "风险源不存在")
    attachments = db.scalars(select(Attachment).where(Attachment.project_id == project_id)).all()
    names = [attachment.file_name for attachment in attachments]
    missing = [material for material in risk.material_requirements if not any(material.lower() in name.lower() or name.lower() in material.lower() for name in names)]
    source_refs = names[-8:]
    content = f"风险源：{risk.name}\n风险等级：{risk.level}\n控制要求：{risk.control_requirements or '待补充'}\n已关联资料：{'、'.join(source_refs) or '暂无'}\n缺项资料：{'、'.join(missing) or '无'}\n建议：请核对风险现场状态和资料完整性后提交审核。"
    draft = RiskDraft(project_id=project_id, risk_source_id=risk.id, title=f"{risk.name}风险上报草稿", content=content, source_refs=source_refs, missing_items=missing)
    db.add(draft); db.flush()
    task_id = None
    if missing:
        task = Task(project_id=project_id, title=f"补齐风险资料 — {risk.name}", task_type="material_missing", risk_level=risk.level, assignee_user_id=risk.responsible_user_id, confirmer_user_id=risk.confirmer_user_id, risk_source_id=risk.id, trigger_reason="智能草稿生成时发现风险资料缺项", required_materials=missing)
        db.add(task); db.flush(); task_id = task.id
        db.add(TaskStatusHistory(task_id=task.id, to_status="pending", changed_by=user.id, note="智能资料缺项校验自动创建"))
    audit(db, user, "智能生成风险草稿", f"为风险源「{risk.name}」生成草稿" + ("并创建缺项任务" if task_id else ""), project_id, "risk_draft", draft.id)
    db.commit(); db.refresh(draft)
    return ok({"draft": serialize(draft), "task_id": task_id}, "风险草稿与缺项校验已完成")


@router.post("/risk-drafts/{draft_id}/submit-review")
def submit_draft_review(draft_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, RiskDraft, draft_id, "草稿不存在"); row.status = "pending_review"
    audit(db, user, "提交草稿审核", f"草稿「{row.title}」提交审核", row.project_id, "risk_draft", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "草稿已提交审核")


@router.post("/risk-drafts/{draft_id}/confirm")
def confirm_draft(draft_id: int, payload: DraftReviewInput | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, RiskDraft, draft_id, "草稿不存在"); row.status = "confirmed"; row.review_note = payload.note if payload else None
    audit(db, user, "确认风险草稿", f"确认草稿「{row.title}」", row.project_id, "risk_draft", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "草稿已确认")


@router.post("/risk-drafts/{draft_id}/return")
def return_draft(draft_id: int, payload: DraftReviewInput | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, RiskDraft, draft_id, "草稿不存在"); row.status = "rejected"; row.review_note = payload.note if payload else None
    audit(db, user, "退回风险草稿", f"退回草稿「{row.title}」", row.project_id, "risk_draft", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "草稿已退回")


@router.post("/risk-drafts/{draft_id}/fill-package")
def create_fill_package(draft_id: int, payload: FillPackageInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    draft = entity_or_404(db, RiskDraft, draft_id, "草稿不存在")
    if draft.status != "confirmed": raise HTTPException(status_code=409, detail="仅已确认草稿可生成填报包")
    package_data = payload.model_dump()
    if not package_data["fields"]:
        values = {"draft_title": draft.title, "draft_content": draft.content, "source_refs": "；".join(draft.source_refs)}
        mappings = db.scalars(select(PlatformFieldMapping).where(PlatformFieldMapping.project_id == draft.project_id, PlatformFieldMapping.platform_name == payload.platform_name, PlatformFieldMapping.enabled.is_(True))).all()
        package_data["fields"] = [{"name": mapping.target_field, "value": values.get(mapping.source_field, ""), "required": mapping.required, "transform_rule": mapping.transform_rule} for mapping in mappings]
    row = FillPackage(project_id=draft.project_id, draft_id=draft.id, **package_data); draft.status = "packaged"; db.add(row); db.flush()
    audit(db, user, "生成填报包", f"为草稿「{draft.title}」生成填报包", draft.project_id, "fill_package", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "填报包已生成")


@router.get("/projects/{project_id}/fill-packages")
def list_fill_packages(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    return ok(list_for_project(FillPackage, project_id, db))


@router.post("/fill-packages/{package_id}/transition")
def transition_fill_package(package_id: int, payload: TaskTransitionInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = entity_or_404(db, FillPackage, package_id, "填报包不存在")
    if payload.status not in {"pending", "filling", "saved", "submitted", "failed", "cancelled"}: raise HTTPException(status_code=422, detail="不支持的填报状态")
    row.status = payload.status; audit(db, user, "更新填报状态", f"填报包状态变更为 {row.status}", row.project_id, "fill_package", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "填报状态已更新")


def collaboration_reply(project_id: int, content: str, db: Session) -> tuple[str, list[int]]:
    project = project_or_404(db, project_id)
    tasks = db.scalars(select(Task).where(Task.project_id == project_id, Task.status.in_(["overdue", "pending", "processing", "need_more_info", "pending_confirm"])).order_by(Task.updated_at.desc())).all()
    wbs_items = db.scalars(select(WbsItem).where(WbsItem.project_id == project_id).order_by(WbsItem.code).limit(30)).all()
    risk_sources = db.scalars(select(RiskSource).where(RiskSource.project_id == project_id).order_by(RiskSource.updated_at.desc()).limit(30)).all()
    quality_metrics = db.scalars(select(QualityMetric).where(QualityMetric.project_id == project_id).order_by(QualityMetric.updated_at.desc()).limit(30)).all()
    daily_reports = db.scalars(select(DailyReport).where(DailyReport.project_id == project_id).order_by(DailyReport.updated_at.desc()).limit(20)).all()
    field_mappings = db.scalars(select(PlatformFieldMapping).where(PlatformFieldMapping.project_id == project_id).order_by(PlatformFieldMapping.platform_name, PlatformFieldMapping.target_field).limit(30)).all()
    materials = db.execute(
        select(Attachment.file_name, Attachment.category, AttachmentText.content)
        .outerjoin(AttachmentText, AttachmentText.attachment_id == Attachment.id)
        .where(Attachment.project_id == project_id)
        .order_by(Attachment.created_at.desc())
        .limit(12)
    ).all()
    material_context = "；".join(
        f"{file_name}（{category}）" + (f"：{(text or '')[:360]}" if text else "")
        for file_name, category, text in materials
    ) or "暂无已入库资料"
    project_context = (
        f"项目：{project.project_name}；所属单位：{project.owner_unit or '未填写'}；说明：{(project.description or '未填写')[:360]}\n"
        + "WBS：" + ("；".join(f"{item.code} {item.name}（{item.progress}%/{item.status}）" for item in wbs_items) or "暂无") + "\n"
        + "风险源：" + ("；".join(f"{item.name}（{item.level}/{item.status}）" for item in risk_sources) or "暂无") + "\n"
        + "质量指标：" + ("；".join(f"{item.name}（{item.status}）" for item in quality_metrics) or "暂无") + "\n"
        + "日报：" + ("；".join(f"{item.file_name}（{item.report_date or '日期待确认'}/{item.status}）" for item in daily_reports) or "暂无") + "\n"
        + "字段映射：" + ("；".join(f"{item.platform_name}:{item.source_field}→{item.target_field}" for item in field_mappings) or "暂无")
    )
    related = [task.id for task in tasks[:4]]
    settings = get_settings()
    if settings.ai_api_key:
        prompt = (
            "你是工程项目资料智能体。请只依据已入库资料和项目待办给出简洁、可执行、可追溯的建议。"
            "优先说明：资料可归入的类别、可补全的项目字段、仍缺少的资料；未知内容必须明确标注为待确认，不能编造。"
            f"\n用户请求：{content}\n项目当前数据：{project_context}\n已入库资料：{material_context}\n待办任务："
            + "；".join(f"{task.title}（{task.status}，截止{task.due_at or '未设置'}）" for task in tasks[:8])
        )
        try:
            response = httpx.post(f"{settings.ai_base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {settings.ai_api_key}"}, json={"model": settings.ai_model, "messages": [{"role": "system", "content": "给出简洁、可执行、可追溯的工程资料补全建议。"}, {"role": "user", "content": prompt}]}, timeout=30)
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            return answer, related
        except (httpx.HTTPError, KeyError, IndexError, TypeError):
            pass
    overdue = next((task for task in tasks if task.status == "overdue"), None)
    focus = overdue or (tasks[0] if tasks else None)
    if focus:
        return f"已基于当前项目的 {len(materials)} 份已入库资料和待办记录生成建议：优先处理「{focus.title}」，状态为{focus.status}，截止日期{focus.due_at or '未设置'}。请核对资料类别、明确对应 WBS/风险项，再补齐缺少材料后提交复核。", related
    return f"当前项目已入库 {len(materials)} 份资料，暂无未闭环任务。可先让智能体核对资料类别与资料缺口，再补充 WBS、风险源或质量指标。", []


@router.post("/projects/{project_id}/material-assistant")
def material_assistant_reply(project_id: int, payload: CollaborationMessageInput, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project = project_or_404(db, project_id)
    members = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.status == "active")).all()
    wbs_items = db.scalars(select(WbsItem).where(WbsItem.project_id == project_id).order_by(WbsItem.code).limit(50)).all()
    risk_sources = db.scalars(select(RiskSource).where(RiskSource.project_id == project_id).order_by(RiskSource.updated_at.desc()).limit(50)).all()
    quality_metrics = db.scalars(select(QualityMetric).where(QualityMetric.project_id == project_id).order_by(QualityMetric.updated_at.desc()).limit(50)).all()

    attachment_ids = list(dict.fromkeys(payload.attachment_ids))
    attachment_rows: list[tuple[Attachment, str | None]] = []
    if attachment_ids:
        selected_rows = db.execute(
            select(Attachment, AttachmentText.content)
            .outerjoin(AttachmentText, AttachmentText.attachment_id == Attachment.id)
            .where(
                Attachment.project_id == project_id,
                Attachment.id.in_(attachment_ids),
            )
        ).all()
        row_by_id = {attachment.id: (attachment, content) for attachment, content in selected_rows}
        if any(attachment_id not in row_by_id for attachment_id in attachment_ids):
            raise HTTPException(status_code=422, detail="附件不存在或不属于当前项目")
        attachment_rows = [row_by_id[attachment_id] for attachment_id in attachment_ids]

    project_fields = [
        ("工程类型说明", project.engineering_type_description),
        ("合同开工日期", project.contract_start_date),
        ("合同竣工日期", project.contract_end_date),
        ("合同工期", project.contract_duration_days),
        ("合同金额", project.contract_amount_wan_yuan),
        ("建设单位", project.construction_unit_name),
        ("总包单位", project.general_contractor_unit_name),
        ("监理单位", project.supervision_unit_name),
        ("设计单位", project.design_unit_name),
        ("勘察单位", project.survey_unit_name),
    ]
    missing = [label for label, value in project_fields if value is None or value == ""]
    if not members: missing.append("项目成员与岗位")
    if not wbs_items: missing.append("WBS 工序基线")
    if not risk_sources: missing.append("风险源")
    if not quality_metrics: missing.append("质量指标")

    setup_context = (
        f"项目名称：{project.name}\n"
        + "项目基本信息："
        + "；".join(f"{label}：{value if value is not None and value != '' else '未填写'}" for label, value in project_fields)
        + "\n"
        f"项目成员：{len(members)} 人；WBS 工序：{len(wbs_items)} 项；风险源：{len(risk_sources)} 项；"
        f"质量指标：{len(quality_metrics)} 项\n"
        "当前缺失项：" + ("、".join(missing) if missing else "无")
    )
    attachment_context_parts: list[str] = []
    remaining_chars = 50000
    for attachment, extracted_text in attachment_rows:
        clean_text = (extracted_text or "").strip()
        text_limit = min(12000, remaining_chars)
        excerpt = clean_text[:text_limit] if text_limit > 0 else ""
        remaining_chars -= len(excerpt)
        attachment_context_parts.append(
            f"附件：{attachment.file_name}（{attachment.category}）\n"
            + (excerpt if excerpt else "[未提取到可读文本]")
        )
    attachment_context = "\n\n".join(attachment_context_parts) or "本轮未上传附件"

    settings = get_settings()
    if settings.ai_api_key:
        prompt = (
            "你是工程项目初始化助手。你的目标是通过用户问答和本轮上传附件，补全项目基本信息、项目人员、"
            "WBS、风险源以及工序质量指标。项目名称已经创建，除非用户明确要求，否则不要建议修改项目名称。"
            "只能提取附件和用户请求中明确存在的事实；无法确定、存在冲突或缺少依据的内容必须标记为待确认，严禁编造。"
            "不得声称已经把识别结果写入数据库，必须先输出待核对结果，等待用户确认。"
            "请按“已识别信息、待确认信息、建议下一步”组织简洁回答。"
            f"\n\n用户请求：{payload.content}\n\n当前项目数据：\n{setup_context}\n\n本轮附件内容：\n{attachment_context}"
        )
        try:
            response = httpx.post(f"{settings.ai_base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {settings.ai_api_key}"}, json={"model": settings.ai_model, "messages": [{"role": "system", "content": "从问答和附件中提取工程项目初始化数据，先核对，确认后才能入库。"}, {"role": "user", "content": prompt}]}, timeout=30)
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            return ok({
                "content": answer,
                "attachments": [
                    {"id": attachment.id, "name": attachment.file_name, "extracted": bool((text or "").strip())}
                    for attachment, text in attachment_rows
                ],
            }, "Dobby 已生成项目初始化核对结果")
        except (httpx.HTTPError, KeyError, IndexError, TypeError):
            pass

    attachment_names = "、".join(attachment.file_name for attachment, _ in attachment_rows)
    readable_count = sum(1 for _, text in attachment_rows if (text or "").strip())
    if missing:
        answer = (
            (f"已接收本轮附件：{attachment_names}；其中 {readable_count} 份已提取到可读内容。" if attachment_rows else "")
            + f"当前项目仍待完善：{'、'.join(missing)}。"
            + "请继续说明相关信息；识别结果会先交给你核对，确认后才能写入项目。"
        )
    else:
        answer = (
            (f"已接收本轮附件：{attachment_names}；其中 {readable_count} 份已提取到可读内容。" if attachment_rows else "")
            + "当前项目初始化数据已具备，请继续核对人员责任、WBS 编码与日期、风险等级以及工序质量指标是否准确。"
        )
    return ok({
        "content": answer,
        "attachments": [
            {"id": attachment.id, "name": attachment.file_name, "extracted": bool((text or "").strip())}
            for attachment, text in attachment_rows
        ],
    }, "Dobby 已生成项目初始化核对结果")


def extract_attachment_text(content: bytes, suffix: str) -> str:
    try:
        if suffix in {".txt", ".md", ".csv"}:
            return content.decode("utf-8", errors="ignore")[:200000]
        if suffix == ".docx":
            from docx import Document
            return "\n".join(paragraph.text for paragraph in Document(io.BytesIO(content)).paragraphs)[:200000]
        if suffix == ".pdf":
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)[:200000]
    except Exception:
        return ""
    return ""


@router.get("/projects/{project_id}/collaboration-sessions")
def list_collaboration_sessions(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    rows = db.scalars(select(CollaborationSession).where(CollaborationSession.project_id == project_id).order_by(CollaborationSession.updated_at.desc())).all()
    return ok([serialize(row) for row in rows])


@router.post("/projects/{project_id}/collaboration-sessions")
def create_collaboration_session(project_id: int, payload: CollaborationSessionInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    row = CollaborationSession(project_id=project_id, participant_ids=list(set(payload.participant_ids + [user.id])), **payload.model_dump(exclude={"participant_ids"}))
    db.add(row); db.flush(); audit(db, user, "创建协同会话", f"创建会话「{row.title}」", project_id, "collaboration_session", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "协同会话已创建")


def session_or_404(db: Session, session_id: int) -> CollaborationSession:
    return entity_or_404(db, CollaborationSession, session_id, "协同会话不存在")


@router.delete("/collaboration-sessions/{session_id}")
def delete_collaboration_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    session = session_or_404(db, session_id)
    project_id, title = session.project_id, session.title
    db.query(MeetingMinute).filter(MeetingMinute.session_id == session_id).delete(synchronize_session=False)
    db.query(CollaborationMessage).filter(CollaborationMessage.session_id == session_id).delete(synchronize_session=False)
    db.delete(session)
    audit(db, user, "删除协同会话", f"删除会话「{title}」；会话生成的任务保留", project_id, "collaboration_session", session_id)
    db.commit()
    return ok(None, "协同会话已删除")


@router.get("/collaboration-sessions/{session_id}/messages")
def list_collaboration_messages(session_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    session_or_404(db, session_id)
    rows = db.scalars(select(CollaborationMessage).where(CollaborationMessage.session_id == session_id).order_by(CollaborationMessage.created_at)).all()
    return ok([serialize(row) for row in rows])


@router.post("/collaboration-sessions/{session_id}/messages")
def create_collaboration_message(session_id: int, payload: CollaborationMessageInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    session = session_or_404(db, session_id)
    db.add(CollaborationMessage(session_id=session.id, role="user", content=payload.content)); db.flush()
    answer, task_ids = collaboration_reply(session.project_id, payload.content, db)
    if "创建任务" in payload.content or "生成任务" in payload.content:
        title = payload.content.replace("创建任务", "").replace("生成任务", "").strip(" ：:，,。")[:200] or "协同会话待办"
        task = Task(project_id=session.project_id, title=f"协同任务 — {title}", task_type="risk_alert", risk_level="medium", assignee_user_id=user.id, trigger_reason=f"由协同会话「{session.title}」自动创建")
        db.add(task); db.flush(); db.add(TaskStatusHistory(task_id=task.id, to_status="pending", changed_by=user.id, note="协同会话自动创建"))
        task_ids = list(dict.fromkeys([*task_ids, task.id])); session.task_ids = list(dict.fromkeys([*(session.task_ids or []), task.id]))
        answer = f"已创建任务「{task.title}」。\n{answer}"
    assistant = CollaborationMessage(session_id=session.id, role="assistant", content=answer, generated_task_ids=task_ids)
    db.add(assistant); session.summary = payload.content[:120]
    audit(db, user, "协同会话处理", f"会话「{session.title}」处理新消息", session.project_id, "collaboration_session", session.id)
    db.commit(); db.refresh(assistant); db.refresh(session)
    return ok({"session": serialize(session), "message": serialize(assistant)}, "协同建议已生成")


@router.post("/collaboration-sessions/{session_id}/minutes")
def create_meeting_minute(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    session = session_or_404(db, session_id)
    messages = db.scalars(select(CollaborationMessage).where(CollaborationMessage.session_id == session_id).order_by(CollaborationMessage.created_at)).all()
    task_ids = list(dict.fromkeys([*(session.task_ids or []), *(item for message in messages for item in (message.generated_task_ids or []))]))
    tasks = [db.get(Task, task_id) for task_id in task_ids]
    actions = [{"task_id": task.id, "title": task.title, "status": task.status, "assignee_user_id": task.assignee_user_id, "due_at": task.due_at} for task in tasks if task]
    discussion = "；".join(message.content[:120] for message in messages[-6:]) or "暂无会话消息"
    row = MeetingMinute(project_id=session.project_id, session_id=session.id, title=f"会议纪要 — {session.title}", summary=f"会话结论：{discussion}", action_items=actions)
    db.add(row); db.flush(); audit(db, user, "生成会议纪要", f"从会话「{session.title}」生成会议纪要", session.project_id, "meeting_minute", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "会议纪要已生成")


@router.get("/projects/{project_id}/document-folders")
def list_document_folders(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    rows = db.scalars(select(DocumentFolder).where(DocumentFolder.project_id == project_id).order_by(DocumentFolder.created_at, DocumentFolder.id)).all()
    return ok([serialize(row) for row in rows])


@router.post("/projects/{project_id}/document-folders")
def create_document_folder(project_id: int, payload: DocumentFolderInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    name = payload.name.strip()
    if payload.parent_id:
        parent = entity_or_404(db, DocumentFolder, payload.parent_id, "上级文件夹不存在")
        if parent.project_id != project_id:
            raise HTTPException(status_code=422, detail="上级文件夹不属于当前项目")
    stmt = select(DocumentFolder).where(DocumentFolder.project_id == project_id, DocumentFolder.name == name)
    stmt = stmt.where(DocumentFolder.parent_id == payload.parent_id) if payload.parent_id else stmt.where(DocumentFolder.parent_id.is_(None))
    if db.scalar(stmt):
        raise HTTPException(status_code=409, detail="同级目录下已存在同名文件夹")
    row = DocumentFolder(project_id=project_id, parent_id=payload.parent_id, name=name)
    db.add(row); db.flush()
    audit(db, user, "新建资料文件夹", f"新建资料文件夹「{name}」", project_id, "document_folder", row.id)
    db.commit(); db.refresh(row)
    return ok(serialize(row), "文件夹已创建")


@router.post("/projects/{project_id}/attachments")
def upload_attachment(project_id: int, file: UploadFile = File(...), category: str = "未分类", folder_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    if folder_id:
        target_folder = entity_or_404(db, DocumentFolder, folder_id, "目标文件夹不存在")
        if target_folder.project_id != project_id:
            raise HTTPException(status_code=422, detail="目标文件夹不属于当前项目")
    settings = get_settings(); folder = settings.upload_dir / str(project_id); folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "attachment").name; target = folder / f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
    with target.open("wb") as output: shutil.copyfileobj(file.file, output)
    content = target.read_bytes(); digest = hashlib.sha256(content).hexdigest()
    if category == "自动归类":
        normalized = safe_name.lower()
        category = "日报" if "日报" in normalized else "进度计划" if any(key in normalized for key in ["wbs", "计划", "进度"]) else "风险资料" if any(key in normalized for key in ["风险", "监测", "隐患"]) else "工程资料"
    previous_version = db.scalar(select(func.max(Attachment.version)).where(Attachment.project_id == project_id, Attachment.file_name == safe_name)) or 0
    row = Attachment(project_id=project_id, file_name=safe_name, storage_path=str(target), content_type=file.content_type, file_size=len(content), file_hash=digest, category=category, version=previous_version + 1)
    db.add(row); db.flush()
    if folder_id:
        db.add(DocumentFolderItem(attachment_id=row.id, folder_id=folder_id, project_id=project_id))
    db.add(AttachmentText(attachment_id=row.id, project_id=project_id, content=extract_attachment_text(content, target.suffix.lower())))
    audit(db, user, "上传资料", f"上传资料「{safe_name}」", project_id, "attachment", row.id); db.commit(); db.refresh(row)
    return ok(serialize(row), "资料已上传")


@router.get("/projects/{project_id}/attachments")
def list_attachments(project_id: int, keyword: str | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id); stmt = select(Attachment, DocumentFolderItem.folder_id).outerjoin(DocumentFolderItem, DocumentFolderItem.attachment_id == Attachment.id).where(Attachment.project_id == project_id)
    if keyword: stmt = stmt.where(Attachment.file_name.contains(keyword))
    rows = db.execute(stmt.order_by(Attachment.created_at.desc())).all()
    return ok([{**serialize(attachment), "folder_id": folder_id} for attachment, folder_id in rows])


@router.patch("/attachments/{attachment_id}")
def update_attachment(attachment_id: int, payload: AttachmentUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    attachment = entity_or_404(db, Attachment, attachment_id, "资料不存在")
    attachment.category = payload.category.strip()
    audit(db, user, "更新资料分类", f"资料「{attachment.file_name}」分类更新为「{attachment.category}」", attachment.project_id, "attachment", attachment.id)
    db.commit(); db.refresh(attachment)
    return ok(serialize(attachment), "资料分类已更新")


@router.get("/projects/{project_id}/document-search")
def search_documents(project_id: int, keyword: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    if not keyword.strip(): return ok([])
    rows = db.execute(select(Attachment, AttachmentText.content, DocumentFolderItem.folder_id).outerjoin(AttachmentText, AttachmentText.attachment_id == Attachment.id).outerjoin(DocumentFolderItem, DocumentFolderItem.attachment_id == Attachment.id).where(Attachment.project_id == project_id, (Attachment.file_name.contains(keyword) | AttachmentText.content.contains(keyword))).order_by(Attachment.created_at.desc())).all()
    result = []
    for attachment, content, folder_id in rows:
        item = serialize(attachment)
        item["folder_id"] = folder_id
        if content:
            index = content.lower().find(keyword.lower())
            item["snippet"] = content[max(0, index - 40): index + len(keyword) + 80] if index >= 0 else ""
        result.append(item)
    return ok(result)


@router.post("/attachments/{attachment_id}/parse-daily")
def parse_daily_attachment(attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    """将已入库日报登记为待确认记录，并生成对应的确认任务。"""
    attachment = entity_or_404(db, Attachment, attachment_id, "资料不存在")
    duplicate = db.scalar(select(DailyReport).where(
        DailyReport.project_id == attachment.project_id,
        DailyReport.file_name == attachment.file_name,
    ))
    if duplicate:
        return ok(serialize(duplicate), "该日报已登记，无需重复创建")

    content = ""
    path = Path(attachment.storage_path)
    if path.suffix.lower() in {".txt", ".md", ".csv"}:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")[:10000]
        except OSError:
            content = ""
    if not content:
        content = f"已归档文件「{attachment.file_name}」，请在确认前补充施工内容、进度和风险信息。"

    date_match = re.search(r"20\d{2}[-_.年/]?\d{1,2}[-_.月/]?\d{1,2}", attachment.file_name)
    report_date = date_match.group(0).replace("年", "-").replace("月", "-").replace("日", "").replace("_", "-").replace(".", "-").replace("/", "-") if date_match else datetime.now(UTC).date().isoformat()
    candidates = db.scalars(select(WbsItem).where(WbsItem.project_id == attachment.project_id)).all()
    matched = next((item for item in candidates if item.name and item.name.lower() in attachment.file_name.lower()), None)
    report = DailyReport(project_id=attachment.project_id, file_name=attachment.file_name, report_date=report_date, content=content,
                         matched_wbs_id=matched.id if matched else None, confidence=0.85 if matched else 0.45,
                         parse_status="parsed", status="pending_confirm")
    db.add(report); db.flush()
    attachment.source_type = "daily_report"; attachment.source_id = report.id
    task = Task(project_id=attachment.project_id, title=f"日报解析确认 — {attachment.file_name}", task_type="daily_confirm", risk_level="low",
                assignee_user_id=user.id, due_at=datetime.now(UTC).date().isoformat(), wbs_item_id=report.matched_wbs_id,
                trigger_reason="资料入库后登记日报，等待人工确认解析内容", required_materials=[])
    db.add(task); db.flush()
    db.add(TaskStatusHistory(task_id=task.id, to_status="pending", changed_by=user.id, note="日报登记后自动创建"))
    audit(db, user, "登记日报解析", f"资料「{attachment.file_name}」已生成日报确认任务", attachment.project_id, "daily_report", report.id)
    db.commit(); db.refresh(report)
    return ok(serialize(report), "日报已登记，并生成确认任务")


@router.get("/projects/{project_id}/operation-logs")
def list_operation_logs(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    return ok([serialize(row) for row in db.scalars(select(OperationLog).where(OperationLog.project_id == project_id).order_by(OperationLog.created_at.desc())).all()])


@router.post("/projects/{project_id}/operation-logs")
def create_operation_log(project_id: int, payload: OperationLogInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    project_or_404(db, project_id)
    audit(db, user, payload.action, payload.detail, project_id, payload.target_type, payload.target_id)
    db.commit()
    row = db.scalars(select(OperationLog).where(OperationLog.project_id == project_id).order_by(OperationLog.id.desc())).first()
    return ok(serialize(row), "日志已记录")
