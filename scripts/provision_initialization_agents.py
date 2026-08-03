"""Provision persistent AgentScope agents for Dobby project initialization.

This is an explicit, one-time configuration command. It creates ordinary
persisted AgentScope agent records through the management API and assigns their
ids to the configured project initializer's selected collaboration allowlist.
It is never imported by the AgentScope runtime and does not register ephemeral
sub-agent templates.
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
ATTACHMENT_SKILL = "read-initialization-attachments"
ORCHESTRATION_SKILL = "orchestrate-project-initialization"
MANAGED_SKILL_NAMES = frozenset(
    {
        ATTACHMENT_SKILL,
        ORCHESTRATION_SKILL,
        "extract-project-basics",
        "organize-project-personnel",
        "validate-wbs-timeline",
        "extract-project-risks",
        "map-quality-requirements",
        "review-project-initialization",
    },
)


@dataclass(frozen=True)
class InitializationSpecialist:
    """Declarative defaults used only when provisioning a missing agent."""

    name: str
    description: str
    instructions: str
    skill_name: str
    sort_order: int
    initialization_role: str


SPECIALISTS = (
    InitializationSpecialist(
        name="工程信息专家",
        description=(
            "识别工程说明、合同和综合资料，提取工程描述、日期、工期、"
            "金额及参建单位。"
        ),
        instructions=(
            "提取工程类型说明、合同开竣工日期、合同工期、合同金额及各参建"
            "单位。忠实保留原始值和来源位置；同一字段存在多个原始值时不得"
            "自行取舍，只记录各自来源。不判断日期、工期或跨分区是否异常，"
            "不处理人员、WBS、风险或质量数据。"
        ),
        skill_name="extract-project-basics",
        sort_order=910,
        initialization_role="project",
    ),
    InitializationSpecialist(
        name="人员与岗位专家",
        description=(
            "处理人员名单、身份证号、岗位、证书和职责，识别同一人员的"
            "多岗位任职。"
        ),
        instructions=(
            "以身份证号识别自然人，但每个岗位保留独立任职记录；不得把同一"
            "人的不同岗位当作重复数据。提取姓名、身份证号、岗位、证书编号"
            "和岗位职责。只做字段提取和同一自然人的任职归组，不判断重复、"
            "职责冲突或账号状态；不要生成登录账号或密码。"
        ),
        skill_name="organize-project-personnel",
        sort_order=920,
        initialization_role="personnel",
    ),
    InitializationSpecialist(
        name="WBS与进度专家",
        description=(
            "解析阶段式 WBS 树结构、计划日期、进度、状态、优先级、层级"
            "与明确的前置关系。"
        ),
        instructions=(
            "完整保留带 WBS 编码的记录。编码只决定层级和同级自然顺序，上级"
            "只能取直接编码前缀；不得根据相邻编码或日期推断前置关系。保留"
            "数值 0，空单元格才是 null。只构造字段、层级和附件明确给出的"
            "前置关系，不判断时间线、依赖、占位内容或父子结构是否异常。"
        ),
        skill_name="validate-wbs-timeline",
        sort_order=930,
        initialization_role="wbs",
    ),
    InitializationSpecialist(
        name="风险源专家",
        description=(
            "读取工程风险清单，整理相关工序、风险部位、等级、判定条件"
            "和风险窗口。"
        ),
        instructions=(
            "提取序号、相关工序、风险部位、风险等级、判定条件、风险时间"
            "窗口和摘要。风险不关联 WBS，相关工序忠实保留清单原文；不判断"
            "时间窗口是否异常或风险内容是否合理。"
        ),
        skill_name="extract-project-risks",
        sort_order=940,
        initialization_role="risks",
    ),
    InitializationSpecialist(
        name="质量指标专家",
        description=(
            "读取工序质量指标，按 WBS 编码整理验收项目、控制指标、"
            "检查频次和关联资料。"
        ),
        instructions=(
            "提取 WBS 编码、质量验收项目、控制指标、检查频次和关联资料。"
            "只保留附件明确给出的编码，不得用名称相似度擅自建立关联；不"
            "判断编码是否存在、记录是否重复或质量内容是否合理。"
        ),
        skill_name="map-quality-requirements",
        sort_order=950,
        initialization_role="quality_requirements",
    ),
)

VALIDATOR = InitializationSpecialist(
    name="初始化核验专家",
    description=(
        "独立核验各专项智能体已经写入的初始化草稿，检查跨专业语义冲突，"
        "并触发平台确定性规则校验。"
    ),
    instructions=(
        "只读取各专项已经写入的草稿分区，不代替专项专家重新提取附件。"
        "重点核对工程日期与 WBS 范围、人员职责冲突、质量与 WBS 语义"
        "匹配、风险窗口及跨分区明显矛盾；平台可确定的编码、结构、时间和重复"
        "规则由规则引擎执行。完成后调用专用核验工具，提交额外语义问题"
        "或空数组，并向负责人发送简短结论。"
    ),
    skill_name="review-project-initialization",
    sort_order=960,
    initialization_role="validator",
)

MANAGED_INITIALIZATION_AGENTS = (*SPECIALISTS, VALIDATOR)


def _model_policy_for_initialization_agent(
    initializer_policy: dict[str, Any],
    spec: InitializationSpecialist,
) -> dict[str, Any]:
    """Derive the fixed model policy for one initialization worker.

    The orchestrator and validator need deliberate reasoning.  The bounded
    domain workers mainly import an already-normalized section, so extended
    thinking only adds latency and token cost there.
    """
    policy = dict(initializer_policy)
    chat_model_config = dict(policy.get("chat_model_config") or {})
    parameters = dict(chat_model_config.get("parameters") or {})
    if spec.initialization_role != "validator":
        parameters["thinking_enable"] = False
        parameters.pop("reasoning_effort", None)
    chat_model_config["parameters"] = parameters
    policy["chat_model_config"] = chat_model_config
    return policy


def _load_project_env() -> None:
    """Load root .env values without adding a dotenv dependency."""
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
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}，请先检查项目根目录 .env。")
    return value


def _orchestrator_system_prompt() -> str:
    return (
        "你是 Dobby 工程管理平台的“项目初始化助手”，负责把用户问答和"
        "任意格式附件整理成标准化中间资料，再交给专项智能体写入可核对的"
        "项目初始化草稿。项目名称由用户先行创建，禁止修改；任何内容都"
        "必须先进入草稿，用户确认后才可正式入库。\n\n"
        "必须遵守：\n"
        "1. 平台会在每轮注入当前项目、附件和完整初始化流程规则；必须以"
        "该动态规则为准，不得沿用旧流程或绕过标准化阶段。\n"
        "2. 只有你可以读取原始附件。先建立 normalization，再按工程信息、"
        "人员、WBS、风险源和质量指标整理平台标准 JSON/Markdown；专项"
        "智能体只能读取你整理好的标准资料。\n"
        "3. 除工程信息外，每个 JSON 分区先只提交 1 条记录试写；收到 "
        "probe_accepted 后再按连续 part_index、每批最多 20 条提交剩余"
        "记录。试写失败时只修正首条，禁止先生成整批数据。\n"
        "4. 只能使用工具参数明确声明的标准字段名，不得自造字段别名；"
        "严格区分数值 0、空值和未知值，不得根据常识补造数据。\n"
        "5. 你写入的 artifact 只是标准化中间资料，不是业务草稿或正式"
        "入库。标准化 ready 后，只要需要写入任一草稿分区，就必须创建"
        "临时团队并邀请对应专项智能体批量导入；即使只有一个分区也不得"
        "由你代写。全部分区完成后再由初始化核验专家统一核验。不得临时"
        "创建专家。\n"
        "6. 成员回复、单次工具成功或等待其他智能体都不代表整轮完成；只有"
        "全部实际分区已导入且最终核验完成，才可向用户报告结束。\n"
        "7. 不使用命令行或直接操作数据库，不生成用户登录凭证，不修改正式"
        "业务表。发现问题时保留原值并提示用户进入“核对草稿”处理。"
    )


def _system_prompt(spec: InitializationSpecialist) -> str:
    if spec.initialization_role == "validator":
        return (
            "你是 Dobby 系统内置的“初始化核验专家”。你只在项目初始化"
            "主智能体邀请后工作，不直接面向最终用户，也不读取或修改正式"
            "项目数据。\n\n"
            "工作规则：\n"
            "1. 调用草稿读取工具检查本轮所有已完成分区和流程状态。\n"
            "2. 不重新解析原始附件，不替专项专家补录数据，不使用命令行或"
            "直接数据库操作。\n"
            "3. 平台规则引擎负责确定性的结构、编码、重复、日期和关联校验；"
            "你只补充规则引擎无法可靠判断的跨专业语义矛盾。\n"
            "4. 所有必需分区完成后调用 "
            "dobby_finalize_project_initialization_draft；没有额外语义问题"
            "时 semantic_issues 必须传空数组。\n"
            "5. 完成后通过 TeamSay 向负责人报告核验是否完成、问题数量和"
            "是否需要用户进入“核对草稿”；不要复制整份草稿。\n\n"
            f"专项职责：\n{spec.instructions}"
        )
    return (
        f"你是 Dobby 系统内置的项目初始化专项智能体“{spec.name}”。\n\n"
        "你只在被“Dobby 项目初始化助手”邀请进临时团队后工作，不直接面向"
        "最终用户，也不独立写入正式项目数据。\n\n"
        "通用规则：\n"
        "1. 只分析负责人交给你的业务分区和标准化批次，不擅自扩展任务。\n"
        "2. 禁止读取原始附件。先用 "
        "dobby_read_project_initialization_artifact 读取本分区的标准 JSON "
        "或 Markdown 清单及必要内容；读取具体分片时必须明确 "
        "artifact_format；不得使用命令行或直接操作数据库。\n"
        "3. 标准资料已经保留附件、工作表、行号、页码或段落来源；核对结论"
        "必须继续引用这些来源。\n"
        "4. 严格区分数值 0、空值和未知值，不得根据常识补造数据。\n"
        "5. 只负责本专业字段核对和分区入草稿。无法读取、来源值冲突或字段"
        "归属不明确时记录简短说明，不做最终异常判定；统一结论由平台规则"
        "与初始化核验专家给出。\n"
        "6. 规范 JSON 已由主智能体合并为本轮完整分区时，优先调用 "
        "dobby_import_project_initialization_artifact 一次性批量导入；后端"
        "负责合并分片，不得在工具参数里重新生成或复制整批 JSON。只有标准"
        "资料确实需要少量人工修正时，才使用 "
        "dobby_write_project_initialization_draft_section 提交修正后的完整"
        "分区。\n"
        "7. 写入成功后使用 TeamSay 只报告完成状态、记录数和需统一核验的"
        "简短摘要，不在团队消息中复制整批数据；不等待用户确认，不自行"
        "结束团队。\n\n"
        f"专项职责：\n{spec.instructions}"
    )


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
    if response.status_code == 204:
        return {}
    return response.json()


def _sync_agent_skills(
    client: httpx.Client,
    *,
    token: str,
    agent_id: str,
    skill_names: tuple[str, ...],
) -> None:
    """Replace Dobby-managed skills without touching manually added skills."""
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
    session_id = session["session_id"]
    query = {
        "agent_id": agent_id,
        "session_id": session_id,
    }
    existing = _request(
        client,
        "GET",
        "/workspace/skill",
        token=token,
        params=query,
    )
    target_names = set(skill_names)
    for skill in existing:
        name = str(skill.get("name") or "")
        managed_base = next(
            (
                managed
                for managed in MANAGED_SKILL_NAMES
                if name == managed or name.startswith(f"{managed} (")
            ),
            None,
        )
        if managed_base is None:
            continue
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
            raise RuntimeError(
                f"缺少初始化技能源文件：{skill_path / 'SKILL.md'}",
            )
        _request(
            client,
            "POST",
            "/workspace/skill",
            token=token,
            params=query,
            json={"skill_path": str(skill_path)},
        )
    print(
        f"已同步技能：{agent_id[:8]}（{len(target_names)} 项）",
    )


def _full_platform_config(
    current: dict[str, Any] | None,
    spec: InitializationSpecialist,
) -> dict[str, Any]:
    config = dict(current or {})
    config.update(
        {
            "role": "system_internal",
            "enabled": True,
            "published": False,
            "allow_global_main_call": False,
            "initialization_role": spec.initialization_role,
            "description": config.get("description") or spec.description,
            "category": "项目初始化",
            "sort_order": spec.sort_order,
            "permission_mode": "auto",
            "knowledge_config": config.get("knowledge_config"),
        },
    )
    return config


def provision(base_url: str) -> None:
    """Create missing specialists and assign them to the initializer."""
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
        initializer_id = settings.get("project_initializer_agent_id")
        if not initializer_id:
            raise RuntimeError(
                "AgentScope 尚未配置“项目初始化助手”，请先在平台设置中指定。",
            )

        agents_payload = _request(
            client,
            "GET",
            "/agent/",
            token=token,
        )
        agents = agents_payload.get("agents") or []
        initializer = next(
            (item for item in agents if item.get("id") == initializer_id),
            None,
        )
        if initializer is None:
            raise RuntimeError("平台设置指向的项目初始化助手不存在。")
        initializer_data = initializer["data"]
        model_policy = initializer_data.get("model_policy") or {}
        if (
            model_policy.get("mode") != "fixed"
            or not model_policy.get("chat_model_config")
        ):
            raise RuntimeError("项目初始化助手必须先配置固定对话模型。")

        ids: list[str] = []
        for spec in MANAGED_INITIALIZATION_AGENTS:
            worker_model_policy = _model_policy_for_initialization_agent(
                model_policy,
                spec,
            )
            matches = [
                item
                for item in agents
                if item.get("data", {}).get("name") == spec.name
                and item.get("data", {})
                .get("platform_config", {})
                .get("role")
                == "system_internal"
            ]
            if len(matches) > 1:
                raise RuntimeError(
                    f"发现多个同名系统智能体“{spec.name}”，请先在管理端清理。",
                )

            if matches:
                agent = matches[0]
                data = agent["data"]
                invite = dict(data.get("invite_config") or {})
                invite.update(
                    {
                        "invitable": True,
                        "invite_description": (
                            invite.get("invite_description")
                            or spec.description
                        ),
                    },
                )
                _request(
                    client,
                    "PATCH",
                    f"/agent/{agent['id']}",
                    token=token,
                    json={
                        "system_prompt": _system_prompt(spec),
                        "model_policy": worker_model_policy,
                        "platform_config": _full_platform_config(
                            data.get("platform_config"),
                            spec,
                        ),
                        "invite_config": invite,
                        "call_config": {
                            "scope": "none",
                            "allowed_agent_ids": [],
                        },
                    },
                )
                agent_id = agent["id"]
                print(f"已校准：{spec.name}（{agent_id[:8]}）")
            else:
                created = _request(
                    client,
                    "POST",
                    "/agent/",
                    token=token,
                    json={
                        "name": spec.name,
                        "system_prompt": _system_prompt(spec),
                        "context_config": (
                            initializer_data.get("context_config") or {}
                        ),
                        "react_config": (
                            initializer_data.get("react_config") or {}
                        ),
                        "model_policy": worker_model_policy,
                        "platform_config": _full_platform_config(None, spec),
                        "invite_config": {
                            "invitable": True,
                            "invite_description": spec.description,
                        },
                        "call_config": {
                            "scope": "none",
                            "allowed_agent_ids": [],
                        },
                    },
                )
                agent_id = created["agent_id"]
                print(f"已创建：{spec.name}（{agent_id[:8]}）")
            ids.append(agent_id)
            _sync_agent_skills(
                client,
                token=token,
                agent_id=agent_id,
                skill_names=(spec.skill_name,),
            )

        initializer_platform_config = dict(
            initializer_data.get("platform_config") or {},
        )
        initializer_platform_config.update(
            {
                "role": "system_internal",
                "enabled": True,
                "published": False,
                "allow_global_main_call": False,
                "initialization_role": "orchestrator",
            },
        )
        _request(
            client,
            "PATCH",
            f"/agent/{initializer_id}",
            token=token,
            json={
                "system_prompt": _orchestrator_system_prompt(),
                "platform_config": initializer_platform_config,
                "call_config": {
                    "scope": "selected",
                    "allowed_agent_ids": ids,
                },
            },
        )
        _sync_agent_skills(
            client,
            token=token,
            agent_id=initializer_id,
            skill_names=(ATTACHMENT_SKILL, ORCHESTRATION_SKILL),
        )
        print(
            "配置完成：项目初始化助手已分配 "
            f"{len(ids)} 个持久化系统智能体（含独立核验专家）。",
        )


def main() -> None:
    _load_project_env()
    parser = argparse.ArgumentParser(
        description="创建并分配 Dobby 项目初始化系统智能体。",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv(
            "AGENTSCOPE_BASE_URL",
            "http://127.0.0.1:18642",
        ),
        help="AgentScope API 地址。",
    )
    args = parser.parse_args()
    provision(args.base_url)


if __name__ == "__main__":
    main()
