from backend.app import api
from scripts.dobby_agent_tools import (
    _initialization_attachment_chunk_read_error,
    _initialization_section_read_error,
    _is_team_completion_interaction,
    _team_completion_message,
)
from scripts.provision_initialization_agents import (
    GLOBAL_BUSINESS_INTERACTIONS,
    ORCHESTRATOR,
    PARSED_ATTACHMENT_READ_INTERACTION,
    SPECIALISTS,
    VALIDATOR,
    WORKERS,
    _model_policy,
    _system_prompt,
)


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


def test_persistent_team_has_bounded_draft_interactions() -> None:
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
        for spec in SPECIALISTS
    )
    assert "dobby_create_initialization_wbs_section" in (
        SPECIALISTS[2].interaction_keys
    )
    assert "dobby_finalize_project_initialization_draft" in (
        VALIDATOR.interaction_keys
    )
    assert "无需再调用 TeamSay" in _system_prompt(SPECIALISTS[2])
    assert "按 section 过滤逐个读取" in _system_prompt(VALIDATOR)
    assert "严禁一次读取全部大型 payload" in _system_prompt(VALIDATOR)
    assert "_json_page.has_more/next_offset" in _system_prompt(VALIDATOR)
    assert "不要等待核验专家的第二次 TeamSay" in _system_prompt(ORCHESTRATOR)
    assert len(GLOBAL_BUSINESS_INTERACTIONS) == 18
    assert not any(
        "initialization" in key
        for key in GLOBAL_BUSINESS_INTERACTIONS
    )


def test_platform_api_enforces_ai_led_plan_first_initialization() -> None:
    assert hasattr(api, "_initialization_agent_instruction")
    conversation = type("Conversation", (), {"conversation_type": "initialization"})()
    instruction = api._initialization_agent_instruction(conversation)
    assert "TaskCreate" in instruction
    assert "第一个业务工具调用" in instruction
    assert "不得假定文件模板" in instruction
    assert "知识库不是初始化固定步骤" in instruction
    assert "<parsed-attachment-manifest>" in instruction
    assert "严禁复制解析正文" in instruction
    assert "_text_page.has_more/next_offset" in instruction
    assert not hasattr(api, "_stream_initialization_message")


def test_durable_initialization_writes_signal_team_completion() -> None:
    section_create = {
        "table_operation": "create",
        "policy": {
            "table_name": "project_initialization_draft_sections",
        },
    }
    draft_update = {
        "table_operation": "update",
        "policy": {"table_name": "project_initialization_drafts"},
    }
    ordinary_read = {
        "table_operation": "read",
        "policy": {"table_name": "project_initialization_drafts"},
    }

    assert _is_team_completion_interaction(section_create, "wbs")
    assert _is_team_completion_interaction(
        section_create,
        "quality_requirements",
    )
    assert _is_team_completion_interaction(draft_update, "validator")
    assert not _is_team_completion_interaction(section_create, "orchestrator")
    assert not _is_team_completion_interaction(ordinary_read, "validator")


def test_durable_completion_messages_drive_the_next_workflow_step() -> None:
    specialist_message = _team_completion_message("wbs")
    validator_message = _team_completion_message("validator")

    assert specialist_message is not None
    assert "读取分区状态继续编排" in specialist_message
    assert "不要等待额外汇报" in specialist_message
    assert validator_message is not None
    assert "立即重新读取草稿状态" in validator_message
    assert "不要等待其他汇报" in validator_message
    assert _team_completion_message("orchestrator") is None


def test_initialization_section_payload_must_be_read_one_section_at_a_time() -> None:
    assert _initialization_section_read_error({}) is not None
    assert _initialization_section_read_error(
        {"fields": ["id", "section", "revision"], "limit": 20},
    ) is None
    assert _initialization_section_read_error(
        {"fields": ["section", "payload"], "limit": 1},
    ) is not None
    assert _initialization_section_read_error(
        {
            "fields": ["section", "payload"],
            "filters": {"section": "wbs"},
            "limit": 5,
        },
    ) is not None
    assert _initialization_section_read_error(
        {
            "fields": ["section", "payload", "source_files"],
            "filters": {"section": "quality_requirements"},
            "limit": 1,
            "json_field": "payload",
            "json_offset": 0,
            "json_limit": 20,
        },
    ) is None
    assert _initialization_section_read_error(
        {
            "fields": ["section", "payload"],
            "filters": {"section": "wbs"},
            "limit": 1,
        },
    ) is not None
    assert _initialization_section_read_error(
        {
            "fields": ["section", "payload"],
            "filters": {"section": "project"},
            "limit": 1,
        },
    ) is None


def test_parsed_attachment_content_must_use_bounded_manifest_chunk_ids() -> None:
    assert _initialization_attachment_chunk_read_error({}) is not None
    assert _initialization_attachment_chunk_read_error(
        {"fields": ["id", "file_id", "chunk_index"]},
    ) is None
    assert _initialization_attachment_chunk_read_error(
        {"fields": ["id", "content"], "limit": 1},
    ) is not None
    assert _initialization_attachment_chunk_read_error(
        {"fields": ["id", "content"], "record_id": 7, "limit": 2},
    ) is not None
    assert _initialization_attachment_chunk_read_error(
        {"fields": ["id", "content"], "record_id": 7, "limit": 1},
    ) is not None
    assert _initialization_attachment_chunk_read_error(
        {
            "fields": ["id", "file_id", "chunk_index", "content"],
            "record_id": 7,
            "limit": 1,
            "text_field": "content",
            "text_offset": 0,
            "text_limit": 6000,
        },
    ) is None
    assert _initialization_attachment_chunk_read_error(
        {
            "fields": ["id", "content"],
            "record_ids": [7, 8],
            "limit": 2,
            "text_field": "content",
            "text_offset": 0,
            "text_limit": 6000,
        },
    ) is not None
    assert _initialization_attachment_chunk_read_error(
        {
            "fields": ["id", "content"],
            "record_id": 7,
            "limit": 1,
            "text_field": "content",
            "text_offset": -1,
            "text_limit": 6000,
        },
    ) is not None
    assert _initialization_attachment_chunk_read_error(
        {
            "fields": ["id", "content"],
            "record_id": 7,
            "limit": 1,
            "text_field": "content",
            "text_offset": 6000,
            "text_limit": 6001,
        },
    ) is not None
    assert _initialization_attachment_chunk_read_error(
        {
            "fields": ["id", "content"],
            "record_id": 7,
            "record_ids": [7],
            "limit": 1,
        },
    ) is not None
