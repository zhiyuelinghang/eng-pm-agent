"""Dedicated platform assignment, isolated from business publication and live databases."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from agentscope.agent import ContextConfig, ReActConfig
from agentscope.app._router._agent import get_platform_agent_catalog, update_platform_settings, update_agent, delete_agent
from agentscope.app._router._schema._agent import UpdatePlatformSettingsRequest, UpdateAgentRequest
from agentscope.app._service._platform_settings import can_query_project_knowledge
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
        platform_config=PlatformAgentConfig(**config)))


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
    async def test_only_enabled_published_public_agents_enter_business_catalog(self):
        rows = [
            agent('public', role='business', published=True),
            agent('unpublished', role='business', published=False),
            agent('disabled', role='business', published=True, enabled=False),
            # Old inconsistent records must not leak into lists or @ candidates.
            agent('internal', role='system_internal', published=True),
            agent('initializer', role='business', published=True),
        ]
        storage, access, _, _ = fixture(rows, project_initializer_agent_id='initializer')
        catalog = await get_platform_agent_catalog(user_id='test', storage=storage, access=access)
        self.assertEqual([item.id for item in catalog.business_agents], ['public'])

    async def test_assign_and_catalog_keep_fixed_identity_and_permissions(self):
        storage, access, manager, records = fixture()
        response = await update_platform_settings(
            UpdatePlatformSettingsRequest(knowledge_assistant_agent_id='docs'),
            user_id='test', storage=storage, manager=manager)
        self.assertEqual(response.knowledge_assistant_agent_id, 'docs')
        self.assertNotIn('memory_policy', records['docs'].data.platform_config.model_dump())
        catalog = await get_platform_agent_catalog(user_id='test', storage=storage, access=access)
        self.assertEqual(catalog.knowledge_assistant.id, 'docs')
        self.assertEqual(catalog.knowledge_assistant.name, '知识库助手')
        self.assertFalse(catalog.knowledge_assistant.published)
        self.assertEqual(catalog.business_agents, [])
        with self.assertRaises(HTTPException) as error:
            await update_platform_settings(
                UpdatePlatformSettingsRequest(knowledge_assistant_agent_id=None),
                user_id='test', storage=storage, manager=manager)
        self.assertEqual(error.exception.status_code, 409)

    async def test_assignment_validates_model_capability_and_independent_responsibility(self):
        invalid = [agent(enabled=False), agent()]
        invalid[1].data.model_policy = AgentModelPolicy()
        for row in invalid:
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
        self.assertFalse(catalog.business_agents[0].project_knowledge_enabled)

    async def test_knowledge_duty_needs_no_capability_checkbox(self):
        row = agent()
        storage, access, manager, records = fixture([row])
        await update_platform_settings(
            UpdatePlatformSettingsRequest(knowledge_assistant_agent_id='docs'),
            user_id='test', storage=storage, manager=manager)
        catalog = await get_platform_agent_catalog(user_id='test', storage=storage, access=access)
        self.assertTrue(catalog.knowledge_assistant.project_knowledge_enabled)
        self.assertTrue(await can_query_project_knowledge(storage, 'test', 'docs'))
        self.assertNotIn("project_knowledge_enabled", records["docs"].data.platform_config.model_dump())

    async def test_all_fixed_duties_reject_disabling_deleting_and_clearing(self):
        for field in ('global_main_agent_id', 'project_initializer_agent_id',
                      'task_assistant_agent_id', 'knowledge_assistant_agent_id'):
            with self.subTest(field=field):
                row = agent()
                storage, access, manager, _ = fixture([row], **{field:'docs'})
                access.resolve_for_edit = AsyncMock(return_value=('test', row))
                session_service = SimpleNamespace(delete_agent=AsyncMock())
                with self.assertRaises(HTTPException) as error:
                    await update_agent('docs', UpdateAgentRequest(platform_config=PlatformAgentConfig(enabled=False)),
                                       user_id='test', storage=storage, access=access)
                self.assertEqual(error.exception.status_code, 409)
                self.assertTrue((await storage.get_agent('test', 'docs')).data.platform_config.enabled)
                with self.assertRaises(HTTPException) as error:
                    await delete_agent('docs', user_id='test', storage=storage, access=access,
                                       session_service=session_service)
                self.assertEqual(error.exception.status_code, 409)
                session_service.delete_agent.assert_not_awaited()
                with self.assertRaises(HTTPException):
                    await update_platform_settings(UpdatePlatformSettingsRequest(**{field:None}),
                                                   user_id='test', storage=storage, manager=manager)
                storage.upsert_platform_settings.assert_not_awaited()

    async def test_ordinary_agent_can_disable_but_cannot_opt_into_knowledge(self):
        row = agent()
        storage, access, _, _ = fixture([row])
        access.resolve_for_edit = AsyncMock(return_value=('test', row))
        with patch('agentscope.app._router._agent._validate_model_policy',
                   new=AsyncMock(return_value=row.data.model_policy)):
            saved = await update_agent('docs', UpdateAgentRequest(platform_config=PlatformAgentConfig(
                enabled=False)),
                user_id='test', storage=storage, access=access)
        self.assertFalse(saved.data.platform_config.enabled)
        self.assertNotIn("project_knowledge_enabled", saved.data.platform_config.model_dump())

    async def test_publication_patch_does_not_create_manual_memory_controls(self):
        row = agent()
        storage, access, _, _ = fixture([row])
        access.resolve_for_edit = AsyncMock(return_value=('test', row))
        with patch('agentscope.app._router._agent._validate_model_policy',
                   new=AsyncMock(return_value=row.data.model_policy)):
            saved = await update_agent('docs', UpdateAgentRequest.model_validate({
                'platform_config': {'role': 'system_internal', 'published': False},
            }), user_id='test', storage=storage, access=access)
        config = saved.data.platform_config
        self.assertNotIn('memory_policy', config.model_dump())

    async def test_update_rejects_retired_memory_policy_choices(self):
        for value in ('standard', 'no_learning', 'no_retention'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                UpdateAgentRequest.model_validate({'platform_config': {'memory_policy': value}})

    async def test_main_configuration_edit_keeps_system_memory_and_dynamic_collaboration(self):
        row = agent(role='global_main')
        storage, access, _, _ = fixture([row], global_main_agent_id='docs')
        access.resolve_for_edit = AsyncMock(return_value=('test', row))
        with patch('agentscope.app._router._agent._validate_model_policy',
                   new=AsyncMock(return_value=row.data.model_policy)):
            saved = await update_agent('docs', UpdateAgentRequest.model_validate({
                'platform_config': {'description': '首页总控'},
            }), user_id='test', storage=storage, access=access)
        self.assertEqual(saved.data.call_config.scope, 'none')
        self.assertEqual(saved.data.platform_config.role, 'global_main')
        self.assertNotIn('memory_policy', saved.data.platform_config.model_dump())

    async def test_only_fixed_knowledge_duty_grants_direct_access(self):
        rows = [agent(key) for key in ('main', 'init', 'task', 'docs', 'business')]
        storage, _, _, records = fixture(rows, global_main_agent_id='main',
            project_initializer_agent_id='init', task_assistant_agent_id='task',
            knowledge_assistant_agent_id='docs')
        for key in records:
            self.assertEqual(await can_query_project_knowledge(storage, 'test', key), key == 'docs')
        await storage.upsert_platform_settings('test', PlatformSettingsData(knowledge_assistant_agent_id='replacement'))
        self.assertFalse(await can_query_project_knowledge(storage, 'test', 'docs'))

    async def test_existing_json_settings_support_new_assignment_without_schema_change(self):
        async with AsyncSQLAlchemyStorage('sqlite+aiosqlite:///:memory:', create_tables=True) as storage:
            await storage.upsert_platform_settings('test', PlatformSettingsData(global_main_agent_id='main'))
            old = await storage.get_platform_settings('test')
            self.assertIsNone(old.data.knowledge_assistant_agent_id)
            await storage.upsert_platform_settings('test', old.data.model_copy(update={'knowledge_assistant_agent_id':'docs'}))
            loaded = await storage.get_platform_settings('test')
            self.assertEqual(loaded.data.knowledge_assistant_agent_id, 'docs')
            self.assertEqual(loaded.data.global_main_agent_id, 'main')
