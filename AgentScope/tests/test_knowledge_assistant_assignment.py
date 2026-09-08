"""Dedicated platform assignment, isolated from business publication and live databases."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from fastapi import HTTPException
from agentscope.agent import ContextConfig, ReActConfig
from agentscope.app._router._agent import get_platform_agent_catalog, update_platform_settings
from agentscope.app._router._schema._agent import UpdatePlatformSettingsRequest
from agentscope.app._service import AgentView
from agentscope.app.storage import (
    AgentData, AgentRecord, AgentModelPolicy, ChatModelConfig, PlatformAgentConfig,
    PlatformSettingsData, PlatformSettingsRecord, AsyncSQLAlchemyStorage,
)


def agent(key='docs', **config):
    return AgentRecord(id=key, user_id='test', data=AgentData(name='内部资料问答模型',
        context_config=ContextConfig(), react_config=ReActConfig(),
        model_policy=AgentModelPolicy(mode='fixed', chat_model_config=ChatModelConfig(
            type='custom_openai_credential', credential_id='test-only', model='test-model', parameters={})),
        platform_config=PlatformAgentConfig(project_knowledge_enabled=True, **config)))


def fixture(records=None, **settings):
    records = {a.id: a for a in records or [agent()]}
    state = {'settings': PlatformSettingsRecord(user_id='test', data=PlatformSettingsData(**settings))}

    async def save_settings(user, data):
        state['settings'] = state['settings'].model_copy(update={'data':data})
        return state['settings']

    async def save_agent(user, row):
        records[row.id] = row
        return row.id

    storage = SimpleNamespace(
        get_platform_settings=AsyncMock(side_effect=lambda user: state['settings']),
        upsert_platform_settings=AsyncMock(side_effect=save_settings),
        get_agent=AsyncMock(side_effect=lambda user, key: records.get(key)),
        list_agents=AsyncMock(side_effect=lambda user: list(records.values())),
        upsert_agent=AsyncMock(side_effect=save_agent),
    )
    access = SimpleNamespace(list_resource=AsyncMock(side_effect=lambda *args: [
        AgentView.model_validate({**row.model_dump(), 'editable':True}) for row in records.values()]))
    manager = SimpleNamespace(list_records=AsyncMock(return_value=[]))
    return storage, access, manager, records


class KnowledgeAssistantAssignmentTests(IsolatedAsyncioTestCase):
    async def test_assign_clear_and_catalog_keep_fixed_identity_and_permissions(self):
        storage, access, manager, records = fixture()
        before = records['docs'].data.platform_config
        response = await update_platform_settings(
            UpdatePlatformSettingsRequest(knowledge_assistant_agent_id='docs'),
            user_id='test', storage=storage, manager=manager)
        self.assertEqual(response.knowledge_assistant_agent_id, 'docs')
        self.assertEqual(records['docs'].data.platform_config.agent_level, before.agent_level)
        self.assertEqual(records['docs'].data.platform_config.memory_write_scopes, before.memory_write_scopes)
        catalog = await get_platform_agent_catalog(user_id='test', storage=storage, access=access)
        self.assertEqual(catalog.knowledge_assistant.id, 'docs')
        self.assertEqual(catalog.knowledge_assistant.name, '资料助手')
        self.assertFalse(catalog.knowledge_assistant.published)
        self.assertEqual(catalog.business_agents, [])
        cleared = await update_platform_settings(
            UpdatePlatformSettingsRequest(knowledge_assistant_agent_id=None),
            user_id='test', storage=storage, manager=manager)
        self.assertIsNone(cleared.knowledge_assistant_agent_id)
        self.assertIsNone((await get_platform_agent_catalog(user_id='test', storage=storage, access=access)).knowledge_assistant)

    async def test_assignment_validates_model_capability_and_independent_responsibility(self):
        invalid = [agent(enabled=False), agent()]
        invalid[1].data.model_policy = AgentModelPolicy()
        no_knowledge = agent()
        no_knowledge.data.platform_config.project_knowledge_enabled = False
        for row in [*invalid, no_knowledge]:
            storage, _, manager, _ = fixture([row])
            with self.assertRaises(HTTPException) as error:
                await update_platform_settings(UpdatePlatformSettingsRequest(knowledge_assistant_agent_id='docs'),
                    user_id='test', storage=storage, manager=manager)
            self.assertEqual(error.exception.status_code, 422)
            storage.upsert_platform_settings.assert_not_awaited()
        for field in ('global_main_agent_id', 'project_initializer_agent_id', 'task_assistant_agent_id'):
            storage, _, manager, _ = fixture()
            with self.assertRaises(HTTPException):
                await update_platform_settings(UpdatePlatformSettingsRequest(**{field:'docs', 'knowledge_assistant_agent_id':'docs'}),
                    user_id='test', storage=storage, manager=manager)
            storage.upsert_platform_settings.assert_not_awaited()

    async def test_unassigned_catalog_does_not_pick_an_eligible_business_agent(self):
        storage, access, _, _ = fixture()
        catalog = await get_platform_agent_catalog(user_id='test', storage=storage, access=access)
        self.assertIsNone(catalog.knowledge_assistant)
        self.assertEqual([a.id for a in catalog.business_agents], ['docs'])

    async def test_existing_json_settings_support_new_assignment_without_schema_change(self):
        async with AsyncSQLAlchemyStorage('sqlite+aiosqlite:///:memory:', create_tables=True) as storage:
            await storage.upsert_platform_settings('test', PlatformSettingsData(global_main_agent_id='main'))
            old = await storage.get_platform_settings('test')
            self.assertIsNone(old.data.knowledge_assistant_agent_id)
            await storage.upsert_platform_settings('test', old.data.model_copy(update={'knowledge_assistant_agent_id':'docs'}))
            loaded = await storage.get_platform_settings('test')
            self.assertEqual(loaded.data.knowledge_assistant_agent_id, 'docs')
            self.assertEqual(loaded.data.global_main_agent_id, 'main')
