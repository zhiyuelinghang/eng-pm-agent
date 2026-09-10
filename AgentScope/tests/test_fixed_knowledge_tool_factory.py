"""Exercise the deployed factory without starting services or contacting WeKnora."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentscope.app.storage import AgentData, AgentRecord, PlatformSettingsData, PlatformSettingsRecord
from agentscope.agent import ContextConfig, ReActConfig


@pytest.mark.asyncio
async def test_deployed_factory_uses_fixed_duty_and_rechecks_it_before_query():
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'agentscope_dev_app.py'
    parsed = ast.parse(path.read_text(encoding='utf-8'))
    factory = next(node for node in parsed.body if isinstance(node, ast.AsyncFunctionDef)
                   and node.name == '_create_platform_agent_tools')
    records = {key: AgentRecord(id=key, user_id='test', data=AgentData(
                    name=key, context_config=ContextConfig(), react_config=ReActConfig()))
               for key in ('main', 'init', 'task', 'docs', 'business')}
    settings = PlatformSettingsRecord(user_id='test', data=PlatformSettingsData(
        global_main_agent_id='main', project_initializer_agent_id='init',
        task_assistant_agent_id='task', knowledge_assistant_agent_id='docs'))
    settings.data.weknora_connection = SimpleNamespace(
        api_key=SimpleNamespace(get_secret_value=lambda: 'test-only'))
    context = SimpleNamespace(conversation_type='business', weknora_agent_id='robot',
        project_id='project', user_id='user', conversation_id='chat',
        weknora_knowledge_base_ids=['base'], weknora_knowledge_ids=['document'],
        weknora_access_mode='restricted')
    storage = SimpleNamespace(
        get_agent=AsyncMock(side_effect=lambda user, key: records.get(key)),
        get_platform_settings=AsyncMock(return_value=settings),
        get_session=AsyncMock(return_value=SimpleNamespace(team_id=None,
            config=SimpleNamespace(platform_context=context))))
    manager = SimpleNamespace(resolve_knowledge_scope=AsyncMock(return_value={'scope':'authorized'}))
    namespace = {'storage':storage, 'database_interaction_manager':manager,
        'create_database_interaction_tools':AsyncMock(return_value=[]),
        'WeKnoraProjectKnowledgeTool':lambda **kwargs: SimpleNamespace(**kwargs),
        'DatabaseInteractionGatewayError':RuntimeError}
    exec(compile(ast.Module(body=[factory], type_ignores=[]), str(path), 'exec'), namespace)
    create = namespace['_create_platform_agent_tools']
    for key in ('main', 'init', 'task', 'business'):
        assert await create('test', key, 'session') == []
    tools = await create('test', 'docs', 'session')
    assert len(tools) == 1
    assert await tools[0].scope_resolver() == {'scope':'authorized'}
    settings.data.knowledge_assistant_agent_id = 'replacement'
    manager.resolve_knowledge_scope.reset_mock()
    with pytest.raises(RuntimeError, match='只有平台知识库助手'):
        await tools[0].scope_resolver()
    manager.resolve_knowledge_scope.assert_not_awaited()
