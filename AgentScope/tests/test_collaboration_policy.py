"""Fixed main privileges, explicit delegates and legacy incoming compatibility."""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agentscope.app._agent_collaboration import can_delegate
from agentscope.app.storage import PlatformSettingsRecord, PlatformSettingsData
from agentscope.app.storage import AgentData, AgentRecord, AgentCallConfig, InviteConfig
from agentscope.app.storage import SessionRecord, SessionConfig, TeamRecord, TeamData, TeamMember
from agentscope.app._service._toolkit import get_toolkit


@pytest.mark.parametrize('target_id', ['main', 'initializer'])
@pytest.mark.parametrize('caller_id', ['main', 'business', 'initializer'])
def test_fixed_entry_agents_cannot_be_invoked_even_with_old_permissions(target_id, caller_id):
    duties = SimpleNamespace(project_initializer_agent_id='initializer', task_assistant_agent_id='task', knowledge_assistant_agent_id='knowledge')
    caller = record(caller_id, scope='selected', ids=[target_id])
    target = record(target_id, allow_main=True, invitable=True)
    assert not can_delegate(caller, target, 'main', duties)


@pytest.mark.parametrize('target_id', ['task', 'knowledge'])
def test_main_fixed_assistants_do_not_depend_on_old_invitation_flags(target_id):
    duties = SimpleNamespace(project_initializer_agent_id='initializer', task_assistant_agent_id='task', knowledge_assistant_agent_id='knowledge')
    target = record(target_id)
    assert can_delegate(record('main'), target, 'main', duties)
    assert not can_delegate(record('business', scope='selected', ids=[target_id]), target, 'main', duties)
    target.data.platform_config.enabled = False
    assert not can_delegate(record('main'), target, 'main', duties)


def test_initializer_entry_rejects_other_pages_and_delegated_legacy_sessions():
    from fastapi import HTTPException
    from agentscope.app._service._platform_settings import ensure_fixed_agent_entry
    duties = SimpleNamespace(global_main_agent_id='main', project_initializer_agent_id='initializer')
    ensure_fixed_agent_entry(duties, 'initializer', SimpleNamespace(conversation_type='initialization'))
    ensure_fixed_agent_entry(duties, 'initializer', None)  # Management-centre debugging.
    for kind in ['general', 'business', 'group_chat']:
        with pytest.raises(HTTPException):
            ensure_fixed_agent_entry(duties, 'initializer', SimpleNamespace(conversation_type=kind))
    for agent_id in ['main', 'initializer']:
        with pytest.raises(HTTPException):
            ensure_fixed_agent_entry(duties, agent_id, None, delegated=True)


def record(agent_id, *, scope="none", ids=(), enabled=True, role="business", allow_main=False, invitable=False):
    data = AgentData.model_validate({
        "name": agent_id,
        "context_config": {},
        "react_config": {},
        "invite_config": {"invitable": invitable},
        "call_config": {"scope": scope, "allowed_agent_ids": list(ids)},
        "platform_config": {"role": role, "enabled": enabled, "allow_global_main_call": allow_main},
    })
    return AgentRecord(id=agent_id, user_id="owner", data=data)


@pytest.mark.parametrize("role", ["business", "system_internal"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("allow_main", [False, True])
@pytest.mark.parametrize("invitable", [False, True])
def test_main_requires_both_enablement_and_target_permission(role, enabled, allow_main, invitable):
    target = record("target", role=role, enabled=enabled, allow_main=allow_main, invitable=invitable)
    assert can_delegate(record("main"), target, "main") is (enabled and allow_main)


def test_main_cannot_bypass_target_permission_through_its_saved_list():
    caller = record("main", scope="selected", ids=["target"])
    assert not can_delegate(caller, record("target"), "main")
    assert can_delegate(caller, record("target", allow_main=True), "main")


@pytest.mark.parametrize("role", ["business", "system_internal"])
@pytest.mark.parametrize("allow_main", [False, True])
@pytest.mark.parametrize("invitable", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_nonmain_requires_invitation_consent_enablement_and_saved_id(role, allow_main, invitable, enabled):
    caller = record("specialist", scope="selected", ids=["target"], role=role)
    target = record("target", allow_main=allow_main, invitable=invitable, enabled=enabled)
    assert can_delegate(caller, target, "main") is (enabled and invitable)
    assert not can_delegate(caller, record("unlisted", invitable=True, allow_main=True), "main")
    caller.data.call_config = AgentCallConfig(scope="none", allowed_agent_ids=["target"])
    assert not can_delegate(caller, target, "main")


def test_role_label_cannot_grant_global_access():
    caller = record("old-main", scope="selected", ids=["target"], role="global_main")
    assert can_delegate(caller, record("target", invitable=True), "new-main")
    assert not can_delegate(caller, record("new-agent"), "new-main")
    assert not can_delegate(caller, caller, "old-main")
    assert not can_delegate(None, record("target"), "main")
    assert not can_delegate(record("main", enabled=False), record("target"), "main")


def test_invitation_consent_is_exposed_and_defaults_to_off_with_optional_description():
    config = InviteConfig(invitable=True, invite_description=None)
    assert config.invite_description is None
    assert "invitable" in InviteConfig.model_json_schema()["properties"]
    assert InviteConfig().invitable is False


@pytest.mark.asyncio
@pytest.mark.parametrize('agent_id', ['main', 'initializer'])
async def test_fixed_entry_agents_cannot_acquire_a_toolkit_in_an_invited_session(agent_id):
    from fastapi import HTTPException
    caller = record(agent_id, role='global_main' if agent_id == 'main' else 'system_internal')
    child = SessionRecord(id='fixed-child', user_id='owner', agent_id=agent_id,
                          team_id='team', config=SessionConfig(workspace_id='workspace'))
    parent = SessionRecord(id='parent', user_id='owner', agent_id='business',
                           team_id='team', config=SessionConfig(workspace_id='parent-workspace'))
    team = TeamRecord(id='team', user_id='owner', session_id='parent', data=TeamData(name='协作团队', members=[
        TeamMember(owner_id='owner', agent_id=agent_id, session_id=child.id,
                   role='invited', inviter_session_id='parent'),
    ]))
    with pytest.raises(HTTPException) as error:
        await get_toolkit(
            storage=SimpleNamespace(get_platform_settings=AsyncMock(return_value=PlatformSettingsRecord(user_id='owner',
                data=PlatformSettingsData(global_main_agent_id='main', project_initializer_agent_id='initializer'))),
                get_team=AsyncMock(return_value=team), get_session=AsyncMock(return_value=parent),
                get_agent=AsyncMock(return_value=record('business'))),
            workspace=SimpleNamespace(list_tools=AsyncMock(return_value=[]), list_mcps=AsyncMock(return_value=[]),
                                      list_skills=AsyncMock(return_value=[])),
            workspace_manager=object(), scheduler_manager=object(),
            background_task_manager=SimpleNamespace(list_tools=AsyncMock(return_value=[])),
            message_bus=object(), middlewares=[], user_id='owner', agent_record=caller,
            session_record=child,
            resource_access_service=SimpleNamespace(list_resource=AsyncMock(return_value=[])),
        )
    assert error.value.status_code == 403
    assert '总控和项目初始化不接受' in error.value.detail


def test_removed_all_scope_is_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AgentCallConfig(scope="all", allowed_agent_ids=["target"])


@pytest.mark.asyncio
async def test_role_field_cannot_infer_a_missing_main_duty():
    from agentscope.app._service._platform_settings import get_global_main_agent_id
    storage = SimpleNamespace(
        get_platform_settings=AsyncMock(return_value=None),
        list_agents=AsyncMock(return_value=[record('main', role='global_main')]),
    )
    assert await get_global_main_agent_id(storage, 'owner') is None
    storage.list_agents.assert_not_awaited()
