"""Provision the AI-led Dobby project-initialization team.

The engineering platform owns attachment transport and final human
confirmation. AgentScope owns planning, model reasoning and collaboration.
Specialists can write only their assigned initialization-draft interactions.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE_ROOT = PROJECT_ROOT / "AgentScope" / "dobby-skills"
TEAM_CONFIG_PATH = PROJECT_ROOT / "AgentScope" / "project-initialization-team.json"


@dataclass(frozen=True)
class InitializationAgentSpec:
    """One persistent member of the initialization collaboration team."""

    key: str
    name: str
    description: str
    skill_name: str
    sort_order: int
    initialization_role: str
    interaction_keys: tuple[str, ...]
    invitable: bool = True
    reasoning: bool = False


@dataclass(frozen=True)
class CollaborationAgentSpec:
    """One management-centre agent used by Dobby or an explicit mention."""

    key: str
    name: str
    description: str
    category: str
    role: str
    published: bool
    allow_global_main_call: bool
    mcp_ids: tuple[str, ...]
    interaction_keys: tuple[str, ...]
    system_prompt: str


def _load_team_manifest(path: Path = TEAM_CONFIG_PATH) -> dict[str, Any]:
    """Load and validate the declarative platform initialization team."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取项目初始化团队配置：{path}") from exc
    if payload.get("schema_version") != 1:
        raise RuntimeError("项目初始化团队配置版本不受支持。")
    agents = payload.get("agents")
    if not isinstance(agents, list) or not agents:
        raise RuntimeError("项目初始化团队配置缺少智能体。")
    required_roles = {
        "orchestrator",
        "project",
        "personnel",
        "wbs",
        "risks",
        "quality_requirements",
    }
    roles = {
        str(item.get("initialization_role") or "")
        for item in agents
        if isinstance(item, dict)
    }
    if roles != required_roles:
        raise RuntimeError("项目初始化团队配置的角色集合不完整。")
    return payload


def _agent_spec(payload: dict[str, Any]) -> InitializationAgentSpec:
    interaction_keys = payload.get("interaction_keys")
    if not isinstance(interaction_keys, list) or not interaction_keys:
        raise RuntimeError(
            f"智能体“{payload.get('name') or payload.get('key')}”没有数据库交互分配。",
        )
    return InitializationAgentSpec(
        key=str(payload["key"]),
        name=str(payload["name"]),
        description=str(payload["description"]),
        skill_name=str(payload["skill_name"]),
        sort_order=int(payload["sort_order"]),
        initialization_role=str(payload["initialization_role"]),
        interaction_keys=tuple(str(key) for key in interaction_keys),
        invitable=bool(payload.get("invitable", True)),
        reasoning=bool(payload.get("reasoning", False)),
    )


def _collaboration_agent_spec(payload: dict[str, Any]) -> CollaborationAgentSpec:
    return CollaborationAgentSpec(
        key=str(payload["key"]),
        name=str(payload["name"]),
        description=str(payload["description"]),
        category=str(payload["category"]),
        role=str(payload["role"]),
        published=bool(payload.get("published", True)),
        allow_global_main_call=bool(payload.get("allow_global_main_call", False)),
        mcp_ids=tuple(str(value) for value in payload.get("mcp_ids") or []),
        interaction_keys=tuple(
            str(value) for value in payload.get("interaction_keys") or []
        ),
        system_prompt=str(payload["system_prompt"]),
    )


_TEAM_MANIFEST = _load_team_manifest()
MANAGED_SKILL_NAMES = frozenset(
    str(name) for name in _TEAM_MANIFEST["managed_skill_names"]
)
OBSOLETE_SKILL_NAMES = frozenset(
    str(name) for name in _TEAM_MANIFEST["obsolete_skill_names"]
)
GLOBAL_BUSINESS_INTERACTIONS = tuple(
    str(key) for key in _TEAM_MANIFEST["global_business_interactions"]
)
UNASSIGNED_SYSTEM_AGENT_NAMES = frozenset(
    str(name) for name in _TEAM_MANIFEST["unassigned_system_agent_names"]
)
_AGENT_SPECS = tuple(_agent_spec(item) for item in _TEAM_MANIFEST["agents"])
COLLABORATION_AGENTS = tuple(
    _collaboration_agent_spec(item)
    for item in _TEAM_MANIFEST.get("collaboration_agents") or []
)
_AGENT_BY_ROLE = {spec.initialization_role: spec for spec in _AGENT_SPECS}
ORCHESTRATOR = _AGENT_BY_ROLE["orchestrator"]
SPECIALISTS = tuple(
    spec
    for spec in _AGENT_SPECS
    if spec.initialization_role
    in {"project", "personnel", "wbs", "risks", "quality_requirements"}
)
WORKERS = SPECIALISTS
PARSED_ATTACHMENT_READ_INTERACTION = next(
    key
    for key in ORCHESTRATOR.interaction_keys
    if key.endswith("_attachment_chunks")
)


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
        "从第一句话开始，所有面向用户的正文、进度说明、协同反馈和最终答复必须使用简体中文；"
        "读取技能前的开场说明也必须用中文，不得先用英文开场再切回中文。"
        "工具名称、字段、路径和原始资料引用保持原样。"
        f"处理项目初始化任务前，必须先通过 Skill 能力读取并严格遵循已分配技能"
        f"“{spec.skill_name}”。技能内容是业务流程的唯一说明，不能跳过或用本地"
        "固定流程替代。"
        "只使用当前会话、技能和明确分配给你的能力；未识别字段省略，保留正式旧值，"
        "不得编造。所有结果仅进入待用户确认的初始化草稿。"
        "资料是否正确、完整、重复、匹配、必填或允许留空，全部由平台当前绑定的核验 MCP 判定。"
        "你的职责仅为采集资料并形成草稿，不得自行核验、生成问题列表或替用户修正资料；"
        "只能原样转述 MCP 结论，存在问题时须由用户修改原始资料后重新上传。"
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
    if not spec.reasoning:
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
    replace_existing: bool = False,
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
    desired = set(skill_names)
    preserved: set[str] = set()
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
        should_delete = managed is not None and (
            managed in OBSOLETE_SKILL_NAMES
            or managed not in desired
            or replace_existing
        )
        if should_delete:
            _request(
                client,
                "DELETE",
                f"/workspace/skill/{quote(name, safe='')}",
                token=token,
                params=query,
            )
        elif managed in desired:
            preserved.add(managed)
    for skill_name in skill_names:
        if skill_name in preserved:
            continue
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


def _initialization_react_config(
    current: dict[str, Any] | None,
    template: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep administrator settings while reserving enough tool iterations."""
    config = dict(current or template or {})
    config["max_iters"] = max(int(config.get("max_iters") or 0), 80)
    config["structured_output_grace_iters"] = max(
        int(config.get("structured_output_grace_iters") or 0),
        5,
    )
    return config


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
    replace_skills: bool = False,
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
        "react_config": _initialization_react_config(
            data.get("react_config"),
            template_data.get("react_config"),
        ),
        "model_policy": _model_policy(template_policy, spec),
        "platform_config": _platform_config(data.get("platform_config"), spec),
        "invite_config": invite,
        "call_config": {
            "scope": "selected" if allowed_agent_ids else "none",
            "allowed_agent_ids": allowed_agent_ids or [],
        },
        # 初始化链路只使用固定附件解析、受控数据库交互和专项智能体。
        # 初始化智能体不分配普通 MCP，最终核验 MCP 由平台设置统一管理。
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
            },
        )
        agent_id = str(created["agent_id"])
        print(f"已创建：{spec.name}（{agent_id[:8]}）")
    _sync_agent_skills(
        client,
        token=token,
        agent_id=agent_id,
        skill_names=(spec.skill_name,),
        replace_existing=replace_skills,
    )
    _assign_database_interactions(
        client,
        token=token,
        agent_id=agent_id,
        keys=spec.interaction_keys,
    )
    return agent_id


_DOBBY_POLICY_START = "<!-- DOBBY-COLLABORATION-POLICY:START -->"
_DOBBY_POLICY_END = "<!-- DOBBY-COLLABORATION-POLICY:END -->"
_DOBBY_POLICY = f"""{_DOBBY_POLICY_START}
你是工程管理平台全局总控 Dobby。普通交流、意图理解、参数明确的受控业务操作
和项目基础只读查询由你直接完成。只有需要专业判断、专属工具或复杂多阶段执行
时，才先调用 agent_search，再用 agent_invoke 调用一个管理中心授权智能体；禁止
使用运行时新建智能体。用户明确 @ 某个智能体时由平台直接路由，不得重复转交。
普通问候直接回答，不激活项目数据库工具组，不调用记忆或专业智能体。查询基本信息
上传情况直接调用 dobby_get_project_basic_info_status，不启动子智能体。指定文件和目标
分类时直接形成修改确认；要求分析资料分类时先调用知识库助手。用户已明确风险字段时
直接形成新增确认；要求从施工资料识别风险时先调用风险研判助手。普通工程资料问题
需要动态搜索并调用知识库助手，不得由你假装已检索资料。
所有写操作必须通过登记的语义化工具并等待用户确认。任务安排必须交给任务助手
生成草稿，确认前不得发布。专业智能体失败时先检查 agent_run_status，再自行重试、
切换或在无法恢复时向用户说明。不得把子智能体原始错误直接甩给用户。只传目标
智能体完成任务所需的最小上下文，并始终遵守平台用户、项目和权限范围。
若任务助手返回 <task-draft>...</task-draft>，最终答复必须原样保留该标签及 JSON，
由平台转换为私有待确认草稿；不得声称已发布。
{_DOBBY_POLICY_END}"""


def _with_dobby_policy(prompt: str) -> str:
    """Replace the managed policy block without discarding admin content."""
    start = prompt.find(_DOBBY_POLICY_START)
    end = prompt.find(_DOBBY_POLICY_END)
    if start >= 0 and end >= start:
        end += len(_DOBBY_POLICY_END)
        prompt = (prompt[:start] + prompt[end:]).strip()
    return (prompt.strip() + "\n\n" + _DOBBY_POLICY).strip()


def _find_collaboration_agent(
    agents: list[dict[str, Any]],
    spec: CollaborationAgentSpec,
) -> dict[str, Any] | None:
    matches = [
        agent
        for agent in agents
        if agent.get("data", {}).get("name") == spec.name
    ]
    if len(matches) > 1:
        raise RuntimeError(f"发现多个同名协同智能体“{spec.name}”，请先清理。")
    return matches[0] if matches else None


def _upsert_collaboration_agent(
    client: httpx.Client,
    *,
    token: str,
    agents: list[dict[str, Any]],
    template_data: dict[str, Any],
    template_policy: dict[str, Any],
    spec: CollaborationAgentSpec,
) -> str:
    existing = _find_collaboration_agent(agents, spec)
    current = existing.get("data", {}) if existing else {}
    platform_config = dict(current.get("platform_config") or {})
    platform_config.update(
        {
            "role": spec.role,
            "enabled": True,
            "published": spec.published,
            "allow_global_main_call": spec.allow_global_main_call,
            "description": spec.description,
            "category": spec.category,
            "sort_order": int(platform_config.get("sort_order") or 200),
            "permission_mode": "auto",
            "knowledge_config": platform_config.get("knowledge_config"),
        },
    )
    payload = {
        "system_prompt": spec.system_prompt,
        "react_config": _initialization_react_config(
            current.get("react_config"),
            template_data.get("react_config"),
        ),
        "model_policy": dict(template_policy),
        "platform_config": platform_config,
        "invite_config": {
            "invitable": True,
            "invite_description": spec.description,
        },
        "call_config": {"scope": "none", "allowed_agent_ids": []},
        "mcp_config": {"allowed_mcp_ids": list(spec.mcp_ids)},
        "skill_config": {"allowed_skill_ids": []},
    }
    if existing is None:
        created = _request(
            client,
            "POST",
            "/agent/",
            token=token,
            json={
                "name": spec.name,
                **payload,
                "context_config": template_data.get("context_config") or {},
            },
        )
        agent_id = str(created["agent_id"])
        print(f"已创建协同智能体：{spec.name}（{agent_id[:8]}）")
    else:
        agent_id = str(existing["id"])
        _request(
            client,
            "PATCH",
            f"/agent/{agent_id}",
            token=token,
            json=payload,
        )
        print(f"已校准协同智能体：{spec.name}（{agent_id[:8]}）")
    _assign_database_interactions(
        client,
        token=token,
        agent_id=agent_id,
        keys=spec.interaction_keys,
    )
    return agent_id


def provision(base_url: str, *, replace_skills: bool = False) -> None:
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
        obsolete_validator_ids = [
            str(agent["id"])
            for agent in agents
            if agent.get("data", {}).get("platform_config", {}).get(
                "initialization_role",
            ) == "validator"
        ]
        for agent_id in obsolete_validator_ids:
            _request(
                client,
                "DELETE",
                f"/agent/{agent_id}",
                token=token,
            )
            print(f"已移除旧核验智能体：{agent_id[:8]}")
        if obsolete_validator_ids:
            agents = [
                agent
                for agent in agents
                if str(agent.get("id")) not in obsolete_validator_ids
            ]
        template = next((item for item in agents if item.get("id") == template_id), None)
        if template is None:
            raise RuntimeError("平台设置指向的全局主智能体不存在。")
        template_data = template["data"]
        template_policy = template_data.get("model_policy") or {}
        if template_policy.get("mode") != "fixed" or not template_policy.get(
            "chat_model_config",
        ):
            raise RuntimeError("全局主智能体必须先配置固定对话模型。")

        dobby_platform_config = dict(template_data.get("platform_config") or {})
        _request(
            client,
            "PATCH",
            f"/agent/{template_id}",
            token=token,
            json={
                "system_prompt": _with_dobby_policy(
                    str(template_data.get("system_prompt") or ""),
                ),
                "platform_config": dobby_platform_config,
                "call_config": {"scope": "none", "allowed_agent_ids": []},
                "mcp_config": {"allowed_mcp_ids": []},
            },
        )

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
                replace_skills=replace_skills,
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
            replace_skills=replace_skills,
        )
        collaboration_ids = {
            spec.key: _upsert_collaboration_agent(
                client,
                token=token,
                agents=agents,
                template_data=template_data,
                template_policy=template_policy,
                spec=spec,
            )
            for spec in COLLABORATION_AGENTS
        }
        task_assistant_id = collaboration_ids.get("task_assistant")
        if not task_assistant_id:
            raise RuntimeError("协同智能体配置缺少 task_assistant。")
        _request(
            client,
            "PUT",
            "/agent/platform/settings",
            token=token,
            json={
                "project_initializer_agent_id": initializer_id,
                "task_assistant_agent_id": task_assistant_id,
            },
        )
        print(
            "配置完成：Dobby 编排策略、资料/风险/任务助手及初始化团队已校准；"
            f"初始化主智能体已连接 {len(worker_ids)} 个持久化专项智能体。",
        )


def main() -> None:
    _load_project_env()
    parser = argparse.ArgumentParser(description="配置 Dobby 项目初始化智能体团队。")
    parser.add_argument(
        "--base-url",
        default=os.getenv("AGENTSCOPE_BASE_URL", "http://127.0.0.1:18642"),
        help="AgentScope API 地址。",
    )
    parser.add_argument(
        "--replace-skills",
        action="store_true",
        help="用仓库内技能覆盖平台已存在的同名技能；默认保留管理端修改。",
    )
    args = parser.parse_args()
    provision(args.base_url, replace_skills=args.replace_skills)


if __name__ == "__main__":
    main()
