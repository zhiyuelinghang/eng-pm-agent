import json
from pathlib import Path

from backend.app import api
from scripts.provision_initialization_agents import (
    GLOBAL_BUSINESS_INTERACTIONS,
    ORCHESTRATOR,
    PARSED_ATTACHMENT_READ_INTERACTION,
    SPECIALISTS,
    TEAM_CONFIG_PATH,
    VALIDATOR,
    WORKERS,
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


def test_domain_specialists_are_fast_but_orchestrator_and_validator_reason() -> None:
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
    assert _model_policy(template, VALIDATOR)["chat_model_config"][
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
    assert {spec.name for spec in WORKERS} == {
        *(spec.name for spec in SPECIALISTS),
        VALIDATOR.name,
    }
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
        VALIDATOR.interaction_keys
    )
    assert len(GLOBAL_BUSINESS_INTERACTIONS) == 18
    assert not any("initialization" in key for key in GLOBAL_BUSINESS_INTERACTIONS)


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
    assert "TaskCreate" in skill
    assert "第一个业务工具调用" in skill
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
    assert validator["runtime_policy"] == {}
