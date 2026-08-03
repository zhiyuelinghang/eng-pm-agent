import asyncio
from types import SimpleNamespace

from backend.app.api import _initialization_agent_instruction
from scripts import dobby_agent_tools
from scripts.provision_initialization_agents import (
    MANAGED_INITIALIZATION_AGENTS,
    SPECIALISTS,
    VALIDATOR,
    _model_policy_for_initialization_agent,
    _orchestrator_system_prompt,
    _system_prompt,
)


def test_domain_specialists_disable_thinking_but_validator_keeps_it() -> None:
    initializer_policy = {
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

    specialist_policy = _model_policy_for_initialization_agent(
        initializer_policy,
        SPECIALISTS[0],
    )
    specialist_parameters = specialist_policy["chat_model_config"][
        "parameters"
    ]
    assert specialist_parameters["thinking_enable"] is False
    assert "reasoning_effort" not in specialist_parameters
    assert specialist_parameters["temperature"] == 0.2

    validator_policy = _model_policy_for_initialization_agent(
        initializer_policy,
        VALIDATOR,
    )
    assert validator_policy["chat_model_config"]["parameters"] == {
        "thinking_enable": True,
        "reasoning_effort": "max",
        "temperature": 0.2,
    }
    assert initializer_policy["chat_model_config"]["parameters"][
        "thinking_enable"
    ] is True


class _ContextResponse:
    status_code = 200

    @staticmethod
    def json() -> dict:
        return {
            "data": {
                "agent_id": "initializer",
                "capabilities": {
                    "read": True,
                    "write": True,
                    "admin_write": True,
                    "initialization_draft": True,
                },
            },
        }

    @staticmethod
    def raise_for_status() -> None:
        return None


class _ContextClient:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    async def get(self, url, *, headers, params):
        del url, headers
        assert params["agentscope_session_id"] == "leader-session"
        return _ContextResponse()


def test_persistent_initialization_specialists_have_bounded_prompts() -> None:
    assert {spec.name for spec in SPECIALISTS} == {
        "工程信息专家",
        "人员与岗位专家",
        "WBS与进度专家",
        "风险源专家",
        "质量指标专家",
    }
    wbs_prompt = _system_prompt(SPECIALISTS[2])
    assert "系统内置" in wbs_prompt
    assert "不得根据相邻编码或日期推断前置关系" in wbs_prompt
    assert "禁止读取原始附件" in wbs_prompt
    assert "dobby_read_project_initialization_artifact" in wbs_prompt
    assert "dobby_import_project_initialization_artifact" in wbs_prompt
    assert "dobby_write_project_initialization_draft_section" in wbs_prompt
    assert "artifact_format" in wbs_prompt
    assert "TeamSay" in wbs_prompt
    assert {spec.name for spec in MANAGED_INITIALIZATION_AGENTS} == {
        *(spec.name for spec in SPECIALISTS),
        VALIDATOR.name,
    }
    validator_prompt = _system_prompt(VALIDATOR)
    assert "dobby_finalize_project_initialization_draft" in validator_prompt
    assert "不重新解析原始附件" in validator_prompt
    orchestrator_prompt = _orchestrator_system_prompt()
    assert "probe_accepted" in orchestrator_prompt
    assert "每批最多 20 条" in orchestrator_prompt
    assert "专项智能体只能读取你整理好的标准资料" in orchestrator_prompt
    assert "即使只有一个分区也不得" in orchestrator_prompt
    assert "artifact 只是标准化中间资料" in orchestrator_prompt


def test_initializer_uses_plans_and_teams_only_when_the_task_needs_them(
) -> None:
    instruction = _initialization_agent_instruction(
        SimpleNamespace(conversation_type="initialization"),
    )

    assert "简单问答" in instruction
    assert "不为形式创建计划" in instruction
    assert "TaskCreate/TaskUpdate" in instruction
    assert "WBS 与进度专家" in instruction
    assert "AgentInvite" in instruction
    assert "禁止使用AgentCreate临时创建专家" in instruction.replace(" ", "")
    assert "初始化核验专家" in instruction
    assert "标准化完成以前" in instruction or "此前严禁" in instruction
    assert "dobby_begin_project_initialization_normalization" in instruction
    assert "dobby_finalize_project_initialization_normalization" in instruction
    assert "dobby_import_project_initialization_artifact" in instruction
    assert "只提交 1 条代表性记录" in instruction
    assert "probe_accepted" in instruction
    assert "每批最多 20 条" in instruction
    assert "即使只有一个分区也不得由你代写" in instruction
    assert "随后必须创建临时团队" in instruction
    assert "artifact 只是标准化中间资料" in instruction
    assert instruction.index(
        "dobby_finalize_project_initialization_normalization",
    ) < instruction.index("TaskCreate")


def test_internal_worker_only_gets_leader_bound_read_tools(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTSCOPE_SERVICE_TOKEN", "test-token")
    monkeypatch.setattr(
        dobby_agent_tools.httpx,
        "AsyncClient",
        _ContextClient,
    )

    tools = asyncio.run(
        dobby_agent_tools.create_dobby_agent_tools(
            "platform",
            "temporary-worker",
            "worker-session",
            platform_session_id="leader-session",
            platform_agent_id="initializer",
            read_only=True,
        ),
    )
    names = {tool.name for tool in tools}

    assert {
        "dobby_get_project_initialization_state",
        "dobby_get_project_initialization_draft",
        "dobby_read_project_initialization_artifact",
    } <= names
    assert "dobby_read_project_initialization_file" not in names
    assert "dobby_submit_project_initialization_draft" not in names
    assert "dobby_update_project_initialization_draft" not in names
    assert "dobby_update_wbs_progress" not in names
    assert all(
        getattr(tool, "_session_id", None) == "leader-session"
        for tool in tools
    )


def test_specialist_gets_only_its_owned_draft_writer(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTSCOPE_SERVICE_TOKEN", "test-token")
    monkeypatch.setattr(
        dobby_agent_tools.httpx,
        "AsyncClient",
        _ContextClient,
    )

    tools = asyncio.run(
        dobby_agent_tools.create_dobby_agent_tools(
            "platform",
            "wbs-specialist",
            "worker-session",
            platform_session_id="leader-session",
            platform_agent_id="initializer",
            read_only=True,
            initialization_role="wbs",
        ),
    )
    names = {tool.name for tool in tools}

    assert "dobby_read_project_initialization_artifact" in names
    assert "dobby_import_project_initialization_artifact" in names
    assert "dobby_write_project_initialization_draft_section" in names
    assert "dobby_read_project_initialization_file" not in names
    assert "dobby_begin_project_initialization_draft" not in names
    assert "dobby_begin_project_initialization_normalization" not in names
    assert "dobby_finalize_project_initialization_draft" not in names
    writer = next(
        tool
        for tool in tools
        if tool.name == "dobby_write_project_initialization_draft_section"
    )
    assert writer.input_schema["properties"]["data"]["type"] == "array"


def test_orchestrator_gets_raw_file_and_normalization_tools(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTSCOPE_SERVICE_TOKEN", "test-token")
    monkeypatch.setattr(
        dobby_agent_tools.httpx,
        "AsyncClient",
        _ContextClient,
    )

    tools = asyncio.run(
        dobby_agent_tools.create_dobby_agent_tools(
            "platform",
            "initializer",
            "leader-session",
            initialization_role="orchestrator",
        ),
    )
    names = {tool.name for tool in tools}

    assert "dobby_read_project_initialization_file" in names
    assert "dobby_begin_project_initialization_normalization" in names
    assert "dobby_write_project_initialization_artifact" in names
    assert "dobby_finalize_project_initialization_normalization" in names
    assert "dobby_begin_project_initialization_draft" in names
    assert "dobby_import_project_initialization_artifact" not in names
    assert "dobby_write_project_initialization_draft_section" not in names
    assert "dobby_create_task" not in names
    assert "dobby_create_risk" not in names
    assert "dobby_update_wbs_progress" not in names
    writer = next(
        tool
        for tool in tools
        if tool.name == "dobby_write_project_initialization_artifact"
    )
    schemas = writer.input_schema["properties"]["json_data"]["anyOf"]
    assert any(schema.get("title") == "WBS 记录数组" for schema in schemas)
    wbs_schema = next(
        schema
        for schema in schemas
        if schema.get("title") == "WBS 记录数组"
    )
    assert wbs_schema["maxItems"] == 20
    assert "parent_wbs_code" in wbs_schema["items"]["properties"]
    assert wbs_schema["items"]["additionalProperties"] is False
