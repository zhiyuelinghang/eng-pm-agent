"""Memory rules belong to trusted scenarios, never editable agent fields."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from agentscope.app.storage import (
    PlatformAgentConfig, PlatformSessionContext, PlatformSettingsData, PlatformSettingsRecord,
    SessionConfig, SessionRecord,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('role', ['business', 'system_internal'])
@pytest.mark.parametrize('published', [False, True])
async def test_platform_visibility_does_not_change_runtime_memory(role, published):
    from agentscope.app.memory._run_context import resolve_agent_memory_access
    config = PlatformAgentConfig(role=role, published=published)
    agent = SimpleNamespace(data=SimpleNamespace(platform_config=config))
    context = PlatformSessionContext(user_id='member', username='member', display_name='成员',
        project_id='project', project_name='项目', conversation_id='conversation',
        conversation_title='会话', conversation_type='business', agent_name='agent')
    session = SessionRecord(id='session', user_id='owner', agent_id='agent',
        config=SessionConfig(workspace_id='workspace', platform_context=context))
    storage = SimpleNamespace(get_session=AsyncMock(return_value=session), get_agent=AsyncMock(return_value=agent),
        get_platform_settings=AsyncMock(return_value=PlatformSettingsRecord(user_id='owner', data=PlatformSettingsData())))
    gateway = SimpleNamespace(resolve_memory_scope=AsyncMock(return_value={
        'user_id': 'member', 'project_id': 'project', 'private': True,
        'project_read': True, 'project_write': True, 'entry_kind': 'business',
    }))
    access, _ = await resolve_agent_memory_access(storage, gateway, 'tenant', 'owner', 'agent', 'session')
    assert set(access.read_scopes) == set(access.write_scopes) == {'user', 'user_project', 'project'}
    assert access.learning_enabled and access.learning_use


@pytest.mark.parametrize('obsolete', [
    {'agent_level': 'worker'}, {'learning_capture': True}, {'learning_process': True},
    {'memory_read_scopes': ['user']}, {'memory_write_scopes': ['project']},
    {'learning_enabled': True}, {'learning_use': True},
    {'memory_policy': 'standard'}, {'memory_policy': 'no_learning'},
    {'memory_policy': 'no_retention'}, {'memory_policy': None},
])
def test_removed_memory_contract_fields_are_rejected(obsolete):
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        PlatformAgentConfig.model_validate(obsolete)


@pytest.mark.parametrize('policy', ['standard', 'no_learning', 'no_retention'])
def test_agent_update_api_rejects_the_removed_memory_policy(policy):
    from agentscope.app._router._schema._agent import UpdateAgentRequest
    with pytest.raises(ValidationError, match='Extra inputs are not permitted'):
        UpdateAgentRequest.model_validate({'platform_config': {'memory_policy': policy}})


def test_memory_schema_has_no_agent_memory_configuration():
    fields = PlatformAgentConfig.model_json_schema()['properties']
    assert not {
        'agent_level', 'learning_capture', 'learning_process', 'memory_read_scopes',
        'memory_write_scopes', 'learning_enabled', 'learning_use', 'memory_policy',
    } & fields.keys()
