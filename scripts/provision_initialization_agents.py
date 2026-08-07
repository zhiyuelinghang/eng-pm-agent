"""Provision the AI-led Dobby project-initialization team.

The engineering platform owns attachment transport and final human
confirmation. AgentScope owns planning, model reasoning and collaboration.
Specialists can write only their assigned initialization-draft interactions.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE_ROOT = PROJECT_ROOT / "AgentScope" / "dobby-skills"
MANAGED_SKILL_NAMES = frozenset(
    {
        "orchestrate-project-initialization",
        "extract-project-basics",
        "organize-project-personnel",
        "validate-wbs-timeline",
        "extract-project-risks",
        "map-quality-requirements",
        "review-project-initialization",
    },
)
OBSOLETE_SKILL_NAMES = frozenset({"read-initialization-attachments"})

COMMON_READ_INTERACTIONS = (
    "dobby_get_project_initialization_state",
    "dobby_get_project_initialization_draft",
    "dobby_list_project_initialization_sections",
)
PARSED_ATTACHMENT_READ_INTERACTION = (
    "dobby_list_project_initialization_attachment_chunks"
)
SPECIALIST_READ_INTERACTIONS = (
    *COMMON_READ_INTERACTIONS,
    PARSED_ATTACHMENT_READ_INTERACTION,
)

GLOBAL_BUSINESS_INTERACTIONS = (
    "dobby_get_project_overview",
    "dobby_list_project_tasks",
    "dobby_list_project_wbs",
    "dobby_list_project_risks",
    "dobby_list_project_information",
    "dobby_list_project_changes",
    "dobby_list_project_notifications",
    "dobby_search_documents",
    "dobby_list_daily_reports",
    "dobby_list_project_personnel",
    "dobby_list_project_quality_requirements",
    "dobby_create_task",
    "dobby_update_task",
    "dobby_dispose_information",
    "dobby_create_project_change",
    "dobby_update_document_category",
    "dobby_create_risk",
    "dobby_update_wbs_progress",
)

UNASSIGNED_SYSTEM_AGENT_NAMES = frozenset({"数据迁移验证助手"})


@dataclass(frozen=True)
class InitializationAgentSpec:
    """One persistent member of the initialization collaboration team."""

    name: str
    description: str
    instructions: str
    skill_name: str
    sort_order: int
    initialization_role: str
    interaction_keys: tuple[str, ...]
    invitable: bool = True


ORCHESTRATOR = InitializationAgentSpec(
    name="Dobby 项目初始化助手",
    description=(
        "理解任意格式的项目资料，先制定执行计划，再组织专项智能体形成"
        "待用户核对的初始化草稿。"
    ),
    instructions=(
        "附件在模型执行前已由平台固定解析器转换为会话级临时分块，消息只"
        "提供 file_id/chunk_id 清单。先用 TaskCreate 建立计划，再读取每个"
        "文件首个 chunk 的首个文本页识别实际分区，不要在主智能体中重复读取"
        "全部正文。读取 content 使用 record_id、limit=1、text_field=content、"
        "text_offset 和 text_limit<=6000；需要完整内容时按 _text_page 读到"
        "末页。随后读取已有草稿、创建 building 草稿，并按实际"
        "内容邀请对应专项智能体。不得假定附件模板，不得直接写正式项目表，"
        "不得用 AgentCreate 替代已配置专家。AgentInvite 只能传 draft_id、"
        "分区、相关 file_id/chunk_id、文件名和核对要求，严禁复制解析正文。"
        "禁止扫描工作区，禁止建立旧式标准化批次。所有"
        "分区完成后必须邀请核验专家。专项专家完成后只用显式 fields 读取"
        "不含 payload 的轻量分区清单。收到核验"
        "结果已持久化的通知后，立即重新读取草稿状态，完成核验和最终汇总任务"
        "并提示用户核对；不要等待"
        "核验专家的第二次 TeamSay。最后等待用户在工程平台确认。知识库不是"
        "固定步骤。"
    ),
    skill_name="orchestrate-project-initialization",
    sort_order=900,
    initialization_role="orchestrator",
    interaction_keys=(
        *COMMON_READ_INTERACTIONS,
        PARSED_ATTACHMENT_READ_INTERACTION,
        "dobby_create_project_initialization_draft",
    ),
    invitable=False,
)

SPECIALISTS = (
    InitializationAgentSpec(
        name="工程信息专家",
        description="从解析资料中整理工程描述、日期、工期、金额及参建单位。",
        instructions=(
            "只处理 project 分区。邀请任务只提供解析分块引用；逐个使用 "
            "record_id=chunk_id、limit=1、text_field=content、text_offset 和 "
            "text_limit<=6000 分页读取全部相关分块，按每页返回的 _text_page "
            "读到 has_more=false，禁止只读第一页。整理"
            "平台字段，"
            "保留来源与冲突，不做无依据推断。使用分配的数据库交互创建或"
            "更新 section=project 的草稿分区；成功写入就是本任务完成边界，"
            "payload 顶层必须直接是工程信息对象，禁止再包裹 project、data、"
            "result 或 summary；字段名必须逐字使用工具 schema 中的英文技术"
            "字段，禁止中文字段名和 schema 外字段。"
            "无需再调用 TeamSay。"
        ),
        skill_name="extract-project-basics",
        sort_order=910,
        initialization_role="project",
        interaction_keys=(
            *SPECIALIST_READ_INTERACTIONS,
            "dobby_create_initialization_project_section",
            "dobby_update_initialization_project_section",
        ),
    ),
    InitializationAgentSpec(
        name="人员与岗位专家",
        description="整理人员、身份证号、岗位、证书、职责及一人多岗关系。",
        instructions=(
            "只处理 personnel 分区。邀请任务只提供解析分块引用；逐个使用 "
            "record_id=chunk_id、limit=1、text_field=content、text_offset 和 "
            "text_limit<=6000 分页读取全部相关分块，按每页返回的 _text_page "
            "读到 has_more=false，禁止只读第一页。以"
            "身份证号识别自然人，同一人的多个岗位"
            "保留多条任职，不生成账号密码。使用分配的数据库交互创建或更新"
            " section=personnel 的草稿分区；成功写入就是本任务完成边界，"
            "payload 顶层必须直接是人员数组，禁止再包裹 personnel、items、"
            "data、result 或 summary；每条记录的字段名必须逐字使用工具 "
            "schema 中的英文技术字段，禁止中文字段名和 schema 外字段。"
            "无需再调用 TeamSay。"
        ),
        skill_name="organize-project-personnel",
        sort_order=920,
        initialization_role="personnel",
        interaction_keys=(
            *SPECIALIST_READ_INTERACTIONS,
            "dobby_create_initialization_personnel_section",
            "dobby_update_initialization_personnel_section",
        ),
    ),
    InitializationAgentSpec(
        name="WBS与进度专家",
        description="整理 WBS 层级、计划日期、进度、状态和明确前置关系。",
        instructions=(
            "只处理 wbs 分区。邀请任务只提供解析分块引用；逐个使用 "
            "record_id=chunk_id、limit=1、text_field=content、text_offset 和 "
            "text_limit<=6000 分页读取全部相关分块，按每页返回的 _text_page "
            "读到 has_more=false，禁止只读第一页。编码仅"
            "确定层级和同级顺序，前置依赖只能来自"
            "资料明确内容；保留数值 0。使用分配的数据库交互创建或更新 "
            "section=wbs 的草稿分区；成功写入就是本任务完成边界。payload "
            "顶层必须直接是 WBS 数组，禁止再包裹 wbs、tasks、items、data、"
            "result 或 summary；数组必须保持扁平，每行一条记录，层级只写 "
            "parent_wbs_code，禁止 children。每条记录字段名必须逐字使用工具 "
            "schema 中的英文技术字段。无需再调用"
            " TeamSay。"
        ),
        skill_name="validate-wbs-timeline",
        sort_order=930,
        initialization_role="wbs",
        interaction_keys=(
            *SPECIALIST_READ_INTERACTIONS,
            "dobby_create_initialization_wbs_section",
            "dobby_update_initialization_wbs_section",
        ),
    ),
    InitializationAgentSpec(
        name="风险源专家",
        description="整理相关工序、风险部位、等级、判定条件和风险窗口。",
        instructions=(
            "只处理 risks 分区。邀请任务只提供解析分块引用；逐个使用 "
            "record_id=chunk_id、limit=1、text_field=content、text_offset 和 "
            "text_limit<=6000 分页读取全部相关分块，按每页返回的 _text_page "
            "读到 has_more=false，禁止只读第一页。相关工序"
            "忠实保留资料原文，不擅自关联 WBS。"
            "使用分配的数据库交互创建或更新 section=risks 的草稿分区，"
            "成功写入就是本任务完成边界。payload 顶层必须直接是风险数组，"
            "禁止再包裹 risks、items、data、result 或 summary；每条记录字段名"
            "必须逐字使用工具 schema 中的英文技术字段。无需再调用 "
            "TeamSay。"
        ),
        skill_name="extract-project-risks",
        sort_order=940,
        initialization_role="risks",
        interaction_keys=(
            *SPECIALIST_READ_INTERACTIONS,
            "dobby_create_initialization_risks_section",
            "dobby_update_initialization_risks_section",
        ),
    ),
    InitializationAgentSpec(
        name="质量指标专家",
        description="按 WBS 编码整理验收项目、控制指标、检查频次和资料要求。",
        instructions=(
            "只处理 quality_requirements 分区。邀请任务只提供解析分块引用；"
            "逐个使用 record_id=chunk_id、limit=1、text_field=content、"
            "text_offset 和 text_limit<=6000 分页读取全部相关分块，按每页"
            "返回的 _text_page 读到 has_more=false，禁止只读第一页。"
            "仅保留资料明确给出的 WBS "
            "编码，不按名称相似度补关联。使用分配的数据库交互创建或更新 "
            "section=quality_requirements 的草稿分区；成功写入就是本任务完成"
            "边界。payload 顶层必须直接是质量指标数组，禁止再包裹 "
            "quality_requirements、items、data、result 或 summary；每条记录字段"
            "名必须逐字使用工具 schema 中的英文技术字段。无需再调用 "
            "TeamSay。"
        ),
        skill_name="map-quality-requirements",
        sort_order=950,
        initialization_role="quality_requirements",
        interaction_keys=(
            *SPECIALIST_READ_INTERACTIONS,
            "dobby_create_initialization_quality_section",
            "dobby_update_initialization_quality_section",
        ),
    ),
)

VALIDATOR = InitializationAgentSpec(
    name="初始化核验专家",
    description="独立读取完整草稿，核验结构、来源和跨专业一致性。",
    instructions=(
        "先读取草稿和轻量分区清单，再按 section 过滤逐个读取每个必需分区。"
        "project 对象可直接读取；personnel、wbs、risks、quality_requirements "
        "的数组 payload 必须使用 json_field=payload、json_offset 和 "
        "json_limit<=20 分页，并根据 _json_page.has_more/next_offset 读到末页；"
        "严禁一次读取全部大型 payload 或只读第一页。核验工程日期与 WBS、"
        "人员职责、质量编码、风险窗口和跨分区矛盾。任何分区缺失、结果被截断"
        "或无法完整核验都必须标记 invalid，绝不能标记 ready。不得重写专项"
        "分区，也不要重复提交合并 payload；把问题写入 validation_issues，有"
        "错误时标记 invalid，否则标记 ready。完成写入后无需 TeamSay，平台会"
        "自动通知主智能体继续。"
    ),
    skill_name="review-project-initialization",
    sort_order=960,
    initialization_role="validator",
    interaction_keys=(
        *COMMON_READ_INTERACTIONS,
        "dobby_finalize_project_initialization_draft",
    ),
)

WORKERS = (*SPECIALISTS, VALIDATOR)


def _load_project_env() -> None:
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}，请先检查项目根目录 .env。")
    return value


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    response = client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {token}"},
        json=json,
        params=params,
    )
    response.raise_for_status()
    return {} if response.status_code == 204 else response.json()


def _system_prompt(spec: InitializationAgentSpec) -> str:
    return (
        f"你是 Dobby 的持久化项目初始化智能体“{spec.name}”。"
        f"{spec.instructions} "
        "只使用当前会话、技能和明确分配给你的能力；缺失值保留 null 或空数组，"
        "不得编造。所有结果仅进入待用户确认的初始化草稿。"
    )


def _platform_config(
    current: dict[str, Any] | None,
    spec: InitializationAgentSpec,
) -> dict[str, Any]:
    config = dict(current or {})
    config.update(
        {
            "role": "system_internal",
            "enabled": True,
            "published": False,
            "allow_global_main_call": False,
            "initialization_role": spec.initialization_role,
            "description": spec.description,
            "category": "项目初始化",
            "sort_order": spec.sort_order,
            "permission_mode": "auto",
            "knowledge_config": config.get("knowledge_config"),
        },
    )
    return config


def _model_policy(
    template_policy: dict[str, Any],
    spec: InitializationAgentSpec,
) -> dict[str, Any]:
    policy = dict(template_policy)
    chat_config = dict(policy.get("chat_model_config") or {})
    parameters = dict(chat_config.get("parameters") or {})
    # DeepSeek V4 supports a 384k completion.  Keep this explicit in every
    # managed initialization agent instead of relying on the provider default.
    parameters["max_tokens"] = 384000
    if spec.initialization_role not in {"orchestrator", "validator"}:
        parameters["thinking_enable"] = False
        parameters.pop("reasoning_effort", None)
    chat_config["parameters"] = parameters
    policy["chat_model_config"] = chat_config
    return policy


def _sync_agent_skills(
    client: httpx.Client,
    *,
    token: str,
    agent_id: str,
    skill_names: tuple[str, ...],
) -> None:
    session = _request(
        client,
        "POST",
        "/sessions/",
        token=token,
        json={
            "agent_id": agent_id,
            "workspace_id": f"dobby-managed-agent-skills-{agent_id}",
            "name": "Dobby 系统技能配置",
        },
    )
    query = {"agent_id": agent_id, "session_id": session["session_id"]}
    existing = _request(
        client,
        "GET",
        "/workspace/skill",
        token=token,
        params=query,
    )
    for skill in existing:
        name = str(skill.get("name") or "")
        managed = next(
            (
                candidate
                for candidate in MANAGED_SKILL_NAMES | OBSOLETE_SKILL_NAMES
                if name == candidate or name.startswith(f"{candidate} (")
            ),
            None,
        )
        if managed is not None:
            _request(
                client,
                "DELETE",
                f"/workspace/skill/{quote(name, safe='')}",
                token=token,
                params=query,
            )
    for skill_name in skill_names:
        skill_path = (SKILL_SOURCE_ROOT / skill_name).resolve()
        if not (skill_path / "SKILL.md").is_file():
            raise RuntimeError(f"缺少初始化技能源文件：{skill_path / 'SKILL.md'}")
        _request(
            client,
            "POST",
            "/workspace/skill",
            token=token,
            params=query,
            json={"skill_path": str(skill_path)},
        )


def _assign_database_interactions(
    client: httpx.Client,
    *,
    token: str,
    agent_id: str,
    keys: tuple[str, ...],
) -> None:
    catalog = _request(
        client,
        "GET",
        "/database-interactions/",
        token=token,
        params={"agent_id": agent_id},
    )
    by_key = {str(item["key"]): int(item["id"]) for item in catalog}
    missing = sorted(set(keys) - set(by_key))
    if missing:
        raise RuntimeError(f"数据库交互尚未就绪：{'、'.join(missing)}")
    _request(
        client,
        "PUT",
        f"/database-interactions/assignments/{agent_id}",
        token=token,
        json={"interaction_ids": [by_key[key] for key in keys]},
    )


def _find_managed_agent(
    agents: list[dict[str, Any]],
    spec: InitializationAgentSpec,
    preferred_id: str | None = None,
) -> dict[str, Any] | None:
    if preferred_id:
        preferred = next((item for item in agents if item.get("id") == preferred_id), None)
        if preferred is not None:
            return preferred
    matches = [
        item
        for item in agents
        if item.get("data", {}).get("name") == spec.name
        and item.get("data", {}).get("platform_config", {}).get("role")
        == "system_internal"
    ]
    if len(matches) > 1:
        raise RuntimeError(f"发现多个同名系统智能体“{spec.name}”，请先清理。")
    return matches[0] if matches else None


def _upsert_agent(
    client: httpx.Client,
    *,
    token: str,
    agents: list[dict[str, Any]],
    template_data: dict[str, Any],
    template_policy: dict[str, Any],
    spec: InitializationAgentSpec,
    preferred_id: str | None = None,
    allowed_agent_ids: list[str] | None = None,
) -> str:
    existing = _find_managed_agent(agents, spec, preferred_id)
    data = existing.get("data", {}) if existing else {}
    invite = dict(data.get("invite_config") or {})
    invite.update(
        {
            "invitable": spec.invitable,
            "invite_description": spec.description,
        },
    )
    payload = {
        "system_prompt": _system_prompt(spec),
        "model_policy": _model_policy(template_policy, spec),
        "platform_config": _platform_config(data.get("platform_config"), spec),
        "invite_config": invite,
        "call_config": {
            "scope": "selected" if allowed_agent_ids else "none",
            "allowed_agent_ids": allowed_agent_ids or [],
        },
        # 初始化已经改为“固定附件解析 + 受控数据库交互 + 专项智能体”链路。
        # 不继承历史 MCP 分配，避免旧的标准化批次工具重新进入初始化上下文。
        "mcp_config": {"allowed_mcp_ids": []},
    }
    if existing:
        _request(
            client,
            "PATCH",
            f"/agent/{existing['id']}",
            token=token,
            json=payload,
        )
        agent_id = str(existing["id"])
        print(f"已校准：{spec.name}（{agent_id[:8]}）")
    else:
        created = _request(
            client,
            "POST",
            "/agent/",
            token=token,
            json={
                "name": spec.name,
                **payload,
                "context_config": template_data.get("context_config") or {},
                "react_config": template_data.get("react_config") or {},
            },
        )
        agent_id = str(created["agent_id"])
        print(f"已创建：{spec.name}（{agent_id[:8]}）")
    _sync_agent_skills(
        client,
        token=token,
        agent_id=agent_id,
        skill_names=(spec.skill_name,),
    )
    _assign_database_interactions(
        client,
        token=token,
        agent_id=agent_id,
        keys=spec.interaction_keys,
    )
    return agent_id


def provision(base_url: str) -> None:
    """Create or refresh the persistent AI-led initialization team."""
    username = _required_env("AGENTSCOPE_ADMIN_USERNAME")
    password = _required_env("AGENTSCOPE_ADMIN_PASSWORD")
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0) as client:
        login = client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        settings = _request(
            client,
            "GET",
            "/agent/platform/settings",
            token=token,
        )
        template_id = settings.get("global_main_agent_id")
        if not template_id:
            raise RuntimeError("请先在平台设置中配置全局主智能体。")
        agents = _request(client, "GET", "/agent/", token=token).get("agents") or []
        template = next((item for item in agents if item.get("id") == template_id), None)
        if template is None:
            raise RuntimeError("平台设置指向的全局主智能体不存在。")
        template_data = template["data"]
        template_policy = template_data.get("model_policy") or {}
        if template_policy.get("mode") != "fixed" or not template_policy.get(
            "chat_model_config",
        ):
            raise RuntimeError("全局主智能体必须先配置固定对话模型。")

        _assign_database_interactions(
            client,
            token=token,
            agent_id=str(template_id),
            keys=GLOBAL_BUSINESS_INTERACTIONS,
        )
        for agent in agents:
            if agent.get("data", {}).get("name") in UNASSIGNED_SYSTEM_AGENT_NAMES:
                _assign_database_interactions(
                    client,
                    token=token,
                    agent_id=str(agent["id"]),
                    keys=(),
                )

        worker_ids = [
            _upsert_agent(
                client,
                token=token,
                agents=agents,
                template_data=template_data,
                template_policy=template_policy,
                spec=spec,
            )
            for spec in WORKERS
        ]
        initializer_id = _upsert_agent(
            client,
            token=token,
            agents=agents,
            template_data=template_data,
            template_policy=template_policy,
            spec=ORCHESTRATOR,
            preferred_id=settings.get("project_initializer_agent_id"),
            allowed_agent_ids=worker_ids,
        )
        _request(
            client,
            "PUT",
            "/agent/platform/settings",
            token=token,
            json={"project_initializer_agent_id": initializer_id},
        )
        print(
            "配置完成：真实初始化主智能体已连接 "
            f"{len(worker_ids)} 个持久化专项智能体。",
        )


def main() -> None:
    _load_project_env()
    parser = argparse.ArgumentParser(description="配置 Dobby 项目初始化智能体团队。")
    parser.add_argument(
        "--base-url",
        default=os.getenv("AGENTSCOPE_BASE_URL", "http://127.0.0.1:18642"),
        help="AgentScope API 地址。",
    )
    args = parser.parse_args()
    provision(args.base_url)


if __name__ == "__main__":
    main()
