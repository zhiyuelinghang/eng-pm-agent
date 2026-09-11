# -*- coding: utf-8 -*-
"""Toolkit assembly for an (agent, session) pair.

The single entry point :func:`get_toolkit` gathers every tool source —
workspace builtins, MCPs, skills, planning tools (Task*), background-task
control (ToolStop), schedule control (Schedule*), team participation
tools, and caller-supplied extras — into one :class:`Toolkit`.
"""
from typing import Any, Literal

from .._manager import BackgroundTaskManager, SchedulerManager
from ..database_interactions import DatabaseInteractionTool
from ..message_bus import MessageBus
from ..mcp_registry import MCPRegistryManager
from ..skill_registry import SkillRegistryManager
from .._platform_tool_policy import PlatformToolPolicy
from .._tool import (
    AgentCancel,
    AgentInvite,
    AgentInvoke,
    AgentRetryOrSwitch,
    AgentRunStatus,
    AgentSearch,
    TeamCreate,
    TeamDelete,
    TeamSay,
)
from .._types import AgentToolFactory, SubAgentTemplate
from ..storage import AgentRecord, SessionRecord, StorageBase
from ..workspace_manager import WorkspaceManagerBase
from ...middleware import MiddlewareBase
from ...tool import (
    TaskCreate,
    TaskGet,
    TaskList,
    TaskUpdate,
    Toolkit,
    ToolGroup,
)
from ...workspace import WorkspaceBase
from ..access import ResourceKind
from ._access import ResourceAccessService
from ._model import resolve_effective_chat_model_config


_GLOBALLY_DISABLED_TOOL_NAMES = frozenset({"PowerShell"})
PROJECT_DATABASE_TOOL_GROUP = "project_database"


def _attach_extra_tools(
    *,
    tools: list[Any],
    tool_groups: list[ToolGroup],
    extra_tools: list[Any],
    platform_context: Any | None,
) -> None:
    """Attach caller tools without flooding ordinary platform turns.

    Database interactions are still resolved exclusively from the
    management-centre assignments.  For the homepage general conversation
    they are exposed as one lazy AgentScope tool group: Dobby sees the
    group's intent in ``reset_tools`` and receives the individual schemas
    only after deciding that the current request needs live project data.
    Non-platform and specialised conversations keep their existing direct
    tool behaviour.
    """
    provided_groups = [
        item for item in extra_tools if isinstance(item, ToolGroup)
    ]
    tool_groups.extend(provided_groups)
    direct_tools = [
        item for item in extra_tools if not isinstance(item, ToolGroup)
    ]

    if (
        platform_context is None
        or platform_context.conversation_type != "general"
    ):
        tools.extend(direct_tools)
        return

    database_tools = [
        tool for tool in direct_tools if isinstance(tool, DatabaseInteractionTool)
    ]
    tools.extend(
        tool
        for tool in direct_tools
        if not isinstance(tool, DatabaseInteractionTool)
    )
    if not database_tools:
        return
    tool_groups.append(
        ToolGroup(
            name=PROJECT_DATABASE_TOOL_GROUP,
            description=(
                "当前项目的数据库交互能力。仅当用户请求需要读取或更新实时"
                "项目业务数据时激活；普通问候、解释以及不依赖项目数据的"
                "请求保持关闭。组内只包含管理中心已分配给当前智能体、且"
                "通过当前登录用户权限校验的能力。"
            ),
            instructions=(
                "根据用户本轮意图，只调用完成请求所必需的数据库交互。"
                "工具返回中没有的数据不得猜测；涉及写入时必须遵守工具自身"
                "的确认和权限策略。"
            ),
            tools=database_tools,
        ),
    )


def _filter_globally_disabled_tools(tools: list[Any]) -> list[Any]:
    """Remove tools disabled for every AgentScope and Dobby chat surface."""
    return [
        tool
        for tool in tools
        if str(getattr(tool, "name", "")) not in _GLOBALLY_DISABLED_TOOL_NAMES
    ]


async def get_toolkit(
    *,
    storage: StorageBase,
    workspace: WorkspaceBase,
    workspace_manager: WorkspaceManagerBase,
    scheduler_manager: SchedulerManager,
    background_task_manager: BackgroundTaskManager,
    message_bus: MessageBus,
    middlewares: list[MiddlewareBase],
    user_id: str,
    agent_record: AgentRecord,
    session_record: SessionRecord,
    resource_access_service: ResourceAccessService,
    extra_factory: AgentToolFactory | None = None,
    sub_agent_templates: dict[str, SubAgentTemplate] | None = None,
    mcp_registry_manager: MCPRegistryManager | None = None,
    skill_registry_manager: SkillRegistryManager | None = None,
    input_has_attachments: bool = True,
) -> Toolkit:
    """Assemble the complete :class:`Toolkit` for one chat turn.

    Tool sources (in attachment order):

    1. Workspace builtins (Bash / Read / Write / Grep / …)
    2. Planning tools (:class:`TaskCreate` / :class:`TaskList` /
       :class:`TaskGet` / :class:`TaskUpdate`)
    3. Background-task control (:class:`ToolStop`, from
       :meth:`BackgroundTaskManager.list_tools`)
    4. Schedule control (:class:`ScheduleCreate` / :class:`ScheduleView`
       / :class:`ScheduleDelete` / :class:`ScheduleList`, from
       :meth:`SchedulerManager.list_tools`). Only attached when the
       agent has an effective model configured (Schedule tools need a model to
       fire new chats with).
    5. Team tools — variant based on the *session's* team role, not
       the agent's ``source``. This matters because a borrowed
       ("invited") agent's session must see worker-only tools even
       though its underlying :class:`AgentRecord` still has
       ``source='user'``. A session that is a worker in some team
       gets only ``TeamSay``. A session that is not in any team OR
       that is its team's leader gets the bounded leader-side toolset
       (``TeamCreate / TeamSay / TeamDelete``, plus ``AgentInvite`` when
       the caller's agent-call configuration allows at least one visible
       invitable agent). The global main agent gets only the managed
       ``agent_*`` orchestration facade.
    6. Caller-supplied extras (``extra_factory``)

    Plus the workspace's skills and MCPs, which become the toolkit's
    ``skills_or_loaders`` and ``mcps`` parameters.

    Args:
        storage (`StorageBase`):
            Application storage backend; needed by team tools to read
            fresh team / session state at call time, and by schedule
            tools.
        workspace (`WorkspaceBase`):
            Pre-resolved per-session workspace (caller resolves it
            via :meth:`WorkspaceManagerBase.get_workspace`). Used here
            for tool / skill / MCP discovery.
        scheduler_manager (`SchedulerManager`):
            Application scheduler. Provides the four schedule tools and
            persists schedules through it.
        background_task_manager (`BackgroundTaskManager`):
            Application background-task registry. Provides the
            :class:`ToolStop` tool bound to its live task dict.
        message_bus (`MessageBus`):
            Application message bus; passed to team tools so they can
            push HintBlocks + wakeups when delivering inter-session
            messages.
        middlewares (`list[MiddlewareBase]`):
            The agent middlewares that may provide tools to the agent via the
            `list_tools` interface.
        user_id (`str`):
            Caller user id.
        agent_record (`AgentRecord`):
            Pre-loaded agent record (loaded once by the caller). Still
            used for its identity (``id``) and for pipeline consumers
            downstream; the ``source`` field is no longer the team-tool
            gate — see :attr:`session_record.team_id` below.
        session_record (`SessionRecord`):
            Pre-loaded session record (loaded once by the caller).
            Used for the schedule-tool model configuration and — via
            :attr:`SessionRecord.team_id` and the resolved team's
            leader session id — for deciding which team tools to
            attach.
        extra_factory (`AgentToolFactory | None`, optional):
            Async factory invoked once per assembly to produce
            user/session-specific extra tools.
        sub_agent_templates (`dict[str, SubAgentTemplate] | None`, optional):
            Retained for call-site compatibility. Runtime creation of
            arbitrary subagents is disabled by this platform policy.

    Returns:
        `Toolkit`: Fully populated toolkit (tools + skills + MCPs).
    """

    tool_groups = []
    platform_context = getattr(session_record.config, "platform_context", None)
    from ._platform_settings import get_global_main_agent_id, get_platform_duties

    global_main_agent_id = await get_global_main_agent_id(
        storage,
        user_id,
    )
    caller_is_global_main = global_main_agent_id == agent_record.id
    is_platform_dobby = caller_is_global_main
    if is_platform_dobby:
        # Project-data activation is a turn-local intent decision.  Do not
        # carry a previous data-heavy turn's schemas into the next greeting.
        session_state = getattr(session_record, "state", None)
        tool_context = getattr(session_state, "tool_context", None)
        if tool_context is not None:
            tool_context.activated_groups = [
                group
                for group in tool_context.activated_groups
                if group != PROJECT_DATABASE_TOOL_GROUP
            ]

    # The general tools running in the workspace
    # Workspace/system tools are platform capabilities, not per-agent
    # assignments. Every agent receives the same catalogue; only the global
    # safety policy below may remove a tool for the whole platform.
    tools = [] if is_platform_dobby else await workspace.list_tools()

    # Dobby's platform surface is deliberately narrower than an ordinary
    # AgentScope workspace: it receives only native orchestration, managed
    # business interactions, and management-level memory.
    initialization_role = getattr(getattr(agent_record.data, "platform_config", None), "initialization_role", None)
    if not is_platform_dobby and not initialization_role:
        tools += [TaskCreate(), TaskList(), TaskGet(), TaskUpdate()]

    # Background-task control.
    if not is_platform_dobby:
        tools += await background_task_manager.list_tools(
            session_id=session_record.id,
        )

    # Schedule control. Resolve the current agent policy because
    # ``ScheduleCreate`` records it into new ``ScheduleRecord`` instances.
    effective_chat_model = resolve_effective_chat_model_config(
        agent_record.data, session_record.config,
    )
    if not is_platform_dobby and effective_chat_model is not None:
        # Add schedule tools as a tool group
        tool_groups.append(
            ToolGroup(
                name="schedule_tools",
                description=(
                    """Tools for managing cron schedules. A cron schedule is \
a recurring task that fires at a specified time — at that point, a new \
session is created and an agent will be invoked to complete the given task \
autonomously.

## When to Use This Tool Group
- When you need to create a new cron schedule that triggers at a specific \
time or interval"
- When you're asked to list, inspect, stop, or delete existing cron schedules
"""
                ),
                tools=await scheduler_manager.list_tools(
                    user_id=user_id,
                    agent_id=agent_record.id,
                    chat_model_config=effective_chat_model,
                ),
            ),
        )

    # Team tools — variant based on the session's team role rather
    # than the agent's ``source`` field. A borrowed ("invited") agent
    # runs with ``source='user'`` on its underlying AgentRecord but
    # its session must behave as a worker; the session-level check
    # captures both created and invited workers uniformly. Sessions
    # not in a team fall through to the leader-side toolset — each
    # leader tool has a runtime precondition check anyway (am I in a
    # team? am I the leader?), so attaching the full set is safe.
    team_tool_kwargs: dict[str, Any] = {
        "storage": storage,
        "message_bus": message_bus,
        "workspace_manager": workspace_manager,
        "user_id": user_id,
        "session_id": session_record.id,
        "agent_id": agent_record.id,
    }
    team_role: Literal["leader", "worker"] | None = None
    if session_record.team_id is not None:
        team = await storage.get_team(user_id, session_record.team_id)
        if team is not None:
            team_role = (
                "leader" if team.session_id == session_record.id else "worker"
            )
    from ._platform_settings import ensure_fixed_agent_entry

    memory_settings = await get_platform_duties(storage, user_id)
    ensure_fixed_agent_entry(
        memory_settings, agent_record.id, platform_context,
        delegated=team_role == 'worker',
    )
    if caller_is_global_main:
        orchestration_kwargs = {
            **team_tool_kwargs,
            "resource_access_service": resource_access_service,
            "caller_owner_id": agent_record.user_id,
        }
        tools += [
            AgentSearch(**orchestration_kwargs),
            AgentInvoke(**orchestration_kwargs),
            AgentRunStatus(**orchestration_kwargs),
            AgentCancel(**orchestration_kwargs),
            AgentRetryOrSwitch(**orchestration_kwargs),
        ]
    elif team_role == "worker":
        tools.append(TeamSay(**team_tool_kwargs, role="worker"))
    else:
        tools.append(TeamCreate(**team_tool_kwargs))
        tools += [
            TeamSay(**team_tool_kwargs, role="leader"),
            TeamDelete(**team_tool_kwargs),
        ]
    if not caller_is_global_main:
        # Conditionally attach AgentInvite. Skipping construction when
        # the user has no invitable agents keeps the input_schema enum
        # non-empty (an empty enum would break tool-schema validators
        # and confuse the LLM into calling a tool with no valid
        # targets). Team-tool base is safe to call for either team or
        # non-team sessions — AgentInvite rechecks the leader
        # precondition at call time.
        #
        # Walk agents *visible* to the caller (own + shared through the
        # resource access policy) so a leader can invite a partner's
        # agent when the policy grants access.
        visible_agents = await resource_access_service.list_resource(
            user_id,
            ResourceKind.AGENT,
        )
        from .._agent_collaboration import can_delegate
        duties = await get_platform_duties(storage, user_id)

        invitable_pool = [
            view
            for view in visible_agents
            if can_delegate(agent_record, view, global_main_agent_id, duties)
        ]
        if invitable_pool:
            tools.append(
                AgentInvite(
                    **team_tool_kwargs,
                    invitable_pool=invitable_pool,
                    caller_owner_id=agent_record.user_id,
                ),
            )

    # Caller-supplied extras.
    if extra_factory is not None:
        _attach_extra_tools(
            tools=tools,
            tool_groups=tool_groups,
            extra_tools=await extra_factory(
                user_id,
                agent_record.id,
                session_record.id,
            ),
            platform_context=platform_context,
        )

    # Tools from middleware
    for mw in middlewares:
        tools.extend(await mw.list_tools())

    # Temporary global command-execution policy: PowerShell must not be
    # available in either the AgentScope management chat or a Dobby business
    # chat.  Keep this final defensive filter after every direct tool source
    # so a caller-supplied factory or middleware cannot accidentally add it
    # back.  Revisit only together with the planned isolated code sandbox.
    tools = _filter_globally_disabled_tools(tools)

    workspace_mcps = [] if is_platform_dobby else await workspace.list_mcps()
    blocked_mcp_names: set[str] = set()
    if is_platform_dobby:
        # Homepage task assignment is an explicit, private platform flow.
        # Do not expose the direct task-engine MCP to the conversational
        # Dobby session, otherwise an ordinary message could bypass the draft.
        blocked_mcp_names.add("task-engine")
    if not input_has_attachments:
        # The fixed parser runs as a session-isolated stdio process and can
        # take seconds to start. Do not launch it for text-only turns: the
        # attachment pipeline returns immediately when no data blocks exist.
        blocked_mcp_names.add("attachment-parser")
    platform_session_id = session_record.id
    platform_agent_id = agent_record.id
    if session_record.team_id is not None:
        team = await storage.get_team(user_id, session_record.team_id)
        if team is not None and team.session_id != session_record.id:
            leader_session = await storage.get_session(
                user_id,
                "",
                team.session_id,
            )
            if leader_session is not None:
                platform_session_id = leader_session.id
                platform_agent_id = leader_session.agent_id
    managed_mcps = (
        await mcp_registry_manager.get_session_clients(
            user_id=user_id,
            agent_id=agent_record.id,
            session_id=session_record.id,
            package_ids=[
                package_id
                for package_id in agent_record.data.mcp_config.allowed_mcp_ids
                if package_id not in blocked_mcp_names
            ],
            excluded_package_ids=blocked_mcp_names,
            platform_agent_id=platform_agent_id,
            platform_session_id=platform_session_id,
        )
        if mcp_registry_manager is not None and not is_platform_dobby
        else []
    )
    managed_names = {client.name for client in managed_mcps}
    resolved_mcps = [
        client
        for client in workspace_mcps
        if client.name not in managed_names
        and client.name not in blocked_mcp_names
    ] + [
        client for client in managed_mcps if client.name not in blocked_mcp_names
    ]

    workspace_skills = (
        []
        if is_platform_dobby
        else await workspace.list_skills(agent_id=agent_record.id)
    )
    managed_skills = (
        await skill_registry_manager.get_assigned_skills(
            agent_record.data.skill_config.allowed_skill_ids,
        )
        if skill_registry_manager is not None and not is_platform_dobby
        else []
    )
    managed_skill_names = {skill.name for skill in managed_skills}
    resolved_skills = [
        skill
        for skill in workspace_skills
        if skill.name not in managed_skill_names
    ] + managed_skills

    from ..memory._policy import memory_duty, memory_rules
    from ..memory._run_context import session_chain

    # Discovery uses system rules; each tool rechecks live permissions and
    # request exclusions when invoked.
    memory_chain = await session_chain(storage, user_id, session_record)
    root_context = memory_chain[-1].config.platform_context
    memory_rule = memory_rules(
        duties=[memory_duty(memory_settings, node.agent_id) for node in memory_chain],
        entry_kind=root_context.conversation_type if root_context is not None else 'debug',
        delegated=len(memory_chain) > 1,
    )
    return Toolkit(
        tools=tools,
        skills_or_loaders=resolved_skills,
        mcps=resolved_mcps,
        tool_groups=tool_groups,
        tool_policy=PlatformToolPolicy(
            global_main=caller_is_global_main,
            memory_read_scopes=memory_rule.read_scopes,
            memory_write_scopes=memory_rule.write_scopes,
            learning_enabled=memory_rule.learning_enabled,
            learning_use=memory_rule.learning_use,
        ),
    )
