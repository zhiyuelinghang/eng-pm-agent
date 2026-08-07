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
        "validator",
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
_AGENT_BY_ROLE = {spec.initialization_role: spec for spec in _AGENT_SPECS}
ORCHESTRATOR = _AGENT_BY_ROLE["orchestrator"]
SPECIALISTS = tuple(
    spec
    for spec in _AGENT_SPECS
    if spec.initialization_role
    in {"project", "personnel", "wbs", "risks", "quality_requirements"}
)
VALIDATOR = _AGENT_BY_ROLE["validator"]
WORKERS = (*SPECIALISTS, VALIDATOR)
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
        f"处理项目初始化任务前，必须先通过 Skill 能力读取并严格遵循已分配技能"
        f"“{spec.skill_name}”。技能内容是业务流程的唯一说明，不能跳过或用本地"
        "固定流程替代。"
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
        replace_existing=replace_skills,
    )
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
    parser.add_argument(
        "--replace-skills",
        action="store_true",
        help="用仓库内技能覆盖平台已存在的同名技能；默认保留管理端修改。",
    )
    args = parser.parse_args()
    provision(args.base_url, replace_skills=args.replace_skills)


if __name__ == "__main__":
    main()
