import json
from pathlib import Path

from backend.app import api
from scripts.provision_initialization_agents import (
    COLLABORATION_AGENTS,
    GLOBAL_BUSINESS_INTERACTIONS,
    ORCHESTRATOR,
    PARSED_ATTACHMENT_READ_INTERACTION,
    SPECIALISTS,
    TEAM_CONFIG_PATH,
    WORKERS,
    _DOBBY_POLICY,
    _model_policy,
    _system_prompt,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _database_interaction(key: str) -> dict:
    payload = json.loads(
        (PROJECT_ROOT / "backend" / "database_interaction_defaults.json").read_text(
            encoding="utf-8",
        ),
    )
    return next(item for item in payload["interactions"] if item["key"] == key)


def test_domain_specialists_are_fast_but_orchestrator_reasons() -> None:
    template = {
        "mode": "fixed",
        "chat_model_config": {
            "type": "deepseek_credential",
            "credential_id": "credential-1",
            "model": "deepseek-v4-flash",
            "parameters": {
                "thinking_enable": True,
                "reasoning_effort": "max",
                "temperature": 0.2,
            },
        },
    }

    specialist = _model_policy(template, SPECIALISTS[0])
    parameters = specialist["chat_model_config"]["parameters"]
    assert parameters["thinking_enable"] is False
    assert "reasoning_effort" not in parameters
    assert parameters["temperature"] == 0.2

    assert _model_policy(template, ORCHESTRATOR)["chat_model_config"][
        "parameters"
    ]["thinking_enable"] is True


def test_persistent_team_is_declarative_and_has_bounded_assignments() -> None:
    manifest = json.loads(TEAM_CONFIG_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert {spec.initialization_role for spec in SPECIALISTS} == {
        "project",
        "personnel",
        "wbs",
        "risks",
        "quality_requirements",
    }
    assert WORKERS == SPECIALISTS
    assert ORCHESTRATOR.invitable is False
    assert all(spec.invitable for spec in WORKERS)
    assert "dobby_create_project_initialization_draft" in (
        ORCHESTRATOR.interaction_keys
    )
    assert PARSED_ATTACHMENT_READ_INTERACTION in ORCHESTRATOR.interaction_keys
    assert all(
        PARSED_ATTACHMENT_READ_INTERACTION in spec.interaction_keys
        for spec in WORKERS
    )
    assert "dobby_finalize_project_initialization_draft" in (
        ORCHESTRATOR.interaction_keys
    )
    assert not any(
        spec.initialization_role == "validator"
        for spec in WORKERS
    )
    assert len(GLOBAL_BUSINESS_INTERACTIONS) == 17
    assert "dobby_get_project_basic_info_status" in GLOBAL_BUSINESS_INTERACTIONS
    assert "dobby_create_task" not in GLOBAL_BUSINESS_INTERACTIONS
    assert "dobby_update_task" not in GLOBAL_BUSINESS_INTERACTIONS
    assert not any("initialization" in key for key in GLOBAL_BUSINESS_INTERACTIONS)


def test_section_17_collaboration_roles_and_confirmed_writes_are_declarative() -> None:
    agents = {spec.key: spec for spec in COLLABORATION_AGENTS}

    knowledge = agents["knowledge_manager"]
    assert knowledge.name == "知识库助手"
    assert not hasattr(knowledge, 'memory_policy')
    assert knowledge.published is True
    assert knowledge.allow_global_main_call is True

    risk = agents["risk_advisor"]
    assert risk.name == "风险研判助手"
    assert not hasattr(risk, 'memory_policy')
    assert risk.allow_global_main_call is True
    assert "不得直接写入风险源" in risk.system_prompt

    task = agents["task_assistant"]
    assert task.name == "任务助手"
    assert task.role == "system_internal"
    assert not hasattr(task, 'memory_policy')
    assert task.published is False
    assert task.mcp_ids == ("task-engine",)
    assert "绝不调用发布" in task.system_prompt

    for interaction_key in (
        "dobby_update_document_category",
        "dobby_create_risk",
    ):
        assert interaction_key in GLOBAL_BUSINESS_INTERACTIONS
        assert _database_interaction(interaction_key)["requires_confirmation"] is True

    assert "普通交流、意图理解、参数明确的受控业务操作" in _DOBBY_POLICY
    assert "只有需要专业判断、专属工具或复杂多阶段执行" in _DOBBY_POLICY
    assert "先调用 agent_search，再用 agent_invoke" in _DOBBY_POLICY
    assert "普通问候直接回答，不激活项目数据库工具组" in _DOBBY_POLICY
    assert "dobby_get_project_basic_info_status，不启动子智能体" in _DOBBY_POLICY
    assert "要求分析资料分类时先调用知识库助手" in _DOBBY_POLICY
    assert "要求从施工资料识别风险时先调用风险研判助手" in _DOBBY_POLICY
    assert "专业智能体失败时先检查 agent_run_status" in _DOBBY_POLICY


def test_platform_skill_is_the_only_initialization_workflow_source() -> None:
    assert not hasattr(api, "_initialization_agent_instruction")
    assert "业务流程的唯一说明" in _system_prompt(ORCHESTRATOR)
    assert ORCHESTRATOR.skill_name in _system_prompt(ORCHESTRATOR)
    assert "TaskCreate" not in _system_prompt(ORCHESTRATOR)
    assert "第一个业务工具调用" not in _system_prompt(ORCHESTRATOR)

    skill = (
        PROJECT_ROOT
        / "AgentScope"
        / "dobby-skills"
        / ORCHESTRATOR.skill_name
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "不创建执行计划" in skill
    assert "TaskCreate" not in skill
    assert "不得自行修复、删改问题记录" in skill
    assert "只能由用户修改原始资料后重新上传" in skill
    assert "进度说明、协同反馈和最终答复必须使用简体中文" in _system_prompt(ORCHESTRATOR)
    assert "<parsed-attachment-manifest>" in skill
    assert "严禁把解析正文复制进邀请 prompt" in skill
    assert "`ready` 才能说“核验通过”" in skill
    assert not hasattr(api, "_stream_initialization_message")


def test_runtime_guards_wait_for_terminal_worker_completion() -> None:
    attachment = _database_interaction(
        "dobby_list_project_initialization_attachment_chunks",
    )
    sections = _database_interaction("dobby_list_project_initialization_sections")
    specialist = _database_interaction("dobby_create_initialization_wbs_section")
    validator = _database_interaction(
        "dobby_finalize_project_initialization_draft",
    )

    assert attachment["runtime_policy"]["argument_guard"]["type"] == (
        "single_record_text_page"
    )
    assert sections["runtime_policy"]["argument_guard"]["type"] == (
        "single_partition_json_page"
    )
    assert specialist["runtime_policy"] == {}
    assert validator["runtime_policy"] == {
        "handler": "project_initialization_validation",
    }
