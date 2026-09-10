# -*- coding: utf-8 -*-
"""The AgentInvite tool — borrows an existing agent into the leader's team.

Unlike :class:`AgentCreate`, which spawns a brand-new worker
(``source='team'``) from a :class:`SubAgentTemplate`, this tool
**borrows** a pre-existing user-owned agent by minting a fresh
team-scoped :class:`SessionRecord` on top of the *existing*
:class:`AgentRecord`.  The borrowed agent keeps its system prompt,
context/react configs, assigned MCP and skills, and model policy.
Platform calls receive a fresh workspace as well as a fresh session;
another platform user's files and conversation settings are not borrowed.

When the team is dissolved or the leader is deleted, only the borrowed
session is cleaned up — the underlying :class:`AgentRecord` survives
so the user can still use the agent stand-alone.
"""
from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import Field

from ._constants import HANDLE_LEN
from ._team_tool_base import _TeamToolBase
from .._platform_permissions import apply_platform_tool_allow_rules
from .._team_lifecycle import add_and_assign_team_member
from .._team_delegation import ancestor_session_ids, report_recipient_session_id
from .._bus_ops import deliver_to_inbox
from ..storage import SessionConfig, TeamMember
from ..storage._utils import _ensure_team_members
from ...message import HintBlock, TextBlock, ToolResultState
from ...permission import PermissionContext
from ...state import AgentState
from ...tool import ToolChunk, ParamsBase
from ..._utils._common import _generate_id


_MAX_INVITE_PROMPT_CHARS = 12_000

if TYPE_CHECKING:
    from ..message_bus import MessageBus
    from ..storage import AgentRecord, StorageBase
    from ..workspace_manager import WorkspaceManagerBase


def _display_handle(agent_id: str) -> str:
    """Return the derived routing handle for ``agent_id``.

    Kept as a tiny helper (rather than inlining ``agent_id[:HANDLE_LEN]``
    at every call site) so a future change to how a handle is derived
    (widening the prefix, hashing, etc.) has exactly one place to touch.
    The length itself lives in :mod:`_constants` so ``TeamSay``'s
    parser agrees byte-for-byte with what this producer emits.
    """
    return agent_id[:HANDLE_LEN]


def _display_name(agent_name: str, agent_id: str) -> str:
    """Format the leader-facing display / routing string.

    Example: ``"Monday@9f3c1a20"``. Used by both :class:`AgentInvite`
    (as the ``target`` enum values) and :func:`TeamSay` (as the
    directory keys for invited members).
    """
    return f"{agent_name}@{_display_handle(agent_id)}"


class _AgentInviteParams(ParamsBase):
    """Parameters for :class:`AgentInvite`.

    ``target`` and ``prompt`` are the only inputs — the borrowed
    agent's name, system prompt, and configuration all come from its
    existing :class:`AgentRecord`, so there is nothing else for the
    leader LLM to override.
    """

    target: str = Field(
        description=(
            "The invitable agent to borrow, formatted "
            '``"<name>@<handle>"`` (e.g. ``"Monday@9f3c1a20"``). Choose '
            "from the enum values — each was populated from the "
            "user's currently-invitable agents at the moment the tool "
            "list was assembled."
        ),
    )
    prompt: str = Field(
        max_length=_MAX_INVITE_PROMPT_CHARS,
        description=(
            "The first task delivered to the invited agent as a user "
            "message. It begins executing immediately upon joining — "
            "do NOT tell it to wait for further instructions. Include "
            "context, constraints, deliverables, and deadlines the "
            "agent needs to work autonomously."
        ),
    )


_DESCRIPTION_HEADER = """Borrow an existing user-owned agent into the \
team you lead.

<If ``AgentCreate`` is not available in your toolset, ignore all \
references to it below.>

## Difference From ``AgentCreate``
- ``AgentCreate`` spins up a brand-new agent that **shares your \
workspace**, so you and it can collaborate on files inside the same \
working directory. ``AgentInvite`` borrows a pre-existing agent that has \
its **own workspace** — depending on how the user has configured it, the \
two workspaces MAY or MAY NOT expose the same filesystem, so paths you \
hand over cannot be assumed to resolve on the invited agent's side.
- The invited agent already has a name; you cannot rename it.

## When to Use This Tool
- A user-owned agent already exists whose stated purpose matches a role \
you need — reuse it instead of spawning a fresh worker with \
``AgentCreate``.
- You want to notify or delegate to an existing agent that specialises \
in a specific domain.

## When NOT to Use This Tool
- No suitable invitable agent exists — use ``AgentCreate`` instead.
- You need to customise the member's system prompt or role for this \
team specifically — invited members' configs are frozen; use \
``AgentCreate`` if you need per-team customisation.
- You are not currently leading a team. Call ``TeamCreate`` first.

## Important
- Do NOT assume the invited agent shares your filesystem. Prefer \
self-contained messages; do not embed working-directory or file paths \
unless you have first verified the two sides can see them.
- If (and only if) the task genuinely requires jointly operating on the \
same large file or complex project directory, first use ``TeamSay`` to \
check whether the invited agent can actually see the same files (e.g. \
by asking it to list or stat a specific path). Skip this handshake for \
tasks where only message content matters.
- ``TeamSay`` is the primary communication channel between you and the \
invited agent.
- ``TeamDelete`` does NOT delete the invited agent — only the \
team-scoped session is cleaned up. If you invite the same agent into \
multiple teams over time, it may retain long-term memory or files from \
earlier collaborations with you.

## Available invitable agents"""


class AgentInvite(_TeamToolBase):
    """Borrow one of the user's invitable agents into the current team.

    The tool is attached to a caller's toolkit only when the calling
    user has at least one enabled agent in the caller's explicit list
    (or enabled targets that allow main calls) — see the toolkit assembly logic in
    :func:`get_toolkit`. The invitable pool is captured as a **snapshot**
    at attachment time so the tool's ``input_schema`` can enumerate
    concrete targets; ``__call__`` re-fetches the target's record and
    re-checks the current caller policy before minting the session, so a race
    between snapshot and call (e.g. the user just disabled the target)
    is caught cleanly.
    """

    display_name = "邀请协同助手"
    presentation_category = "collaboration"

    name: str = "AgentInvite"
    # No leader state needed — the borrowed session starts from a
    # fresh PermissionContext(); nothing carries over from the leader.
    is_state_injected: bool = False

    description: str
    input_schema: dict

    def __init__(
        self,
        storage: "StorageBase",
        message_bus: "MessageBus",
        workspace_manager: "WorkspaceManagerBase",
        user_id: str,
        session_id: str,
        agent_id: str,
        invitable_pool: list["AgentRecord"],
        caller_owner_id: str | None = None,
    ) -> None:
        """Bind request-scoped identifiers plus the invitable pool snapshot.

        Args:
            storage (`StorageBase`):
                Application storage backend.
            message_bus (`MessageBus`):
                Application message bus.
            workspace_manager (`WorkspaceManagerBase`):
                Used to mint the workspace id for freshly-invited
                agents (see :meth:`__call__`).
            user_id (`str`):
                The owner user id.
            session_id (`str`):
                The calling session id.
            agent_id (`str`):
                The calling agent id.
            invitable_pool (`list[AgentRecord]`):
                Snapshot of currently-invitable agents. Must be
                non-empty — the caller skips construction otherwise.
            caller_owner_id (`str | None`):
                Storage owner of the calling agent. Defaults to ``user_id``
                for backwards compatibility.
        """
        super().__init__(
            storage,
            message_bus,
            workspace_manager,
            user_id,
            session_id,
            agent_id,
        )

        self._pool_by_id: dict[str, "AgentRecord"] = {
            a.id: a for a in invitable_pool
        }
        self._caller_owner_id = caller_owner_id or user_id

        # Build enum + a human-readable per-target rundown for the LLM.
        enum_values = [
            _display_name(a.data.name, a.id) for a in invitable_pool
        ]
        target_lines = [
            f"- ``{_display_name(a.data.name, a.id)!r}`` — "
            f"{a.data.invite_config.invite_description or a.data.platform_config.description or a.data.name}"
            for a in invitable_pool
        ]
        self.description = (
            _DESCRIPTION_HEADER + "\n" + "\n".join(target_lines) + "\n"
        )

        schema = copy.deepcopy(_AgentInviteParams.model_json_schema())
        schema["properties"]["target"]["enum"] = enum_values
        self.input_schema = schema

    async def __call__(
        self,
        target: str,
        prompt: str,
    ) -> ToolChunk:
        """Mint a team-scoped session on top of an existing agent record.

        Preconditions (all rechecked at call time against fresh storage
        reads):
        - Caller is the team leader or a member delegating to an allowed target.
        - ``target`` is a well-formed ``"<name>@<handle>"`` string whose
          handle prefix-matches an agent id in the current invitable
          pool.
        - The caller's latest agent-call configuration still allows the
          matched agent.
        - The matched agent is still enabled and allowed by the caller policy.
        - The team does not already have this agent as a member (one
          borrow per agent per team).
        - The invited agent has at least one existing session to
          inherit ``workspace_id`` / ``chat_model_config`` from — a
          brand-new never-opened agent record is not invitable in
          practice because it has no runtime state to reuse.

        Args:
            target (`str`):
                The ``"<name>@<handle>"`` display string chosen from
                the enum.
            prompt (`str`):
                First task delivered as a user message to the invited
                agent.

        Returns:
            `ToolChunk`:
                A success message containing the invited agent's
                display name, or an error chunk on failure.
        """
        if len(prompt) > _MAX_INVITE_PROMPT_CHARS:
            return _error(
                "AgentInvite: prompt 过长。请把大型资料保存到受控存储，"
                "邀请时只传引用和任务要求。",
            )
        try:
            invited, resolve_err = _resolve_target(
                self._pool_by_id,
                target,
            )
            if resolve_err is not None:
                return _error(resolve_err)
            assert invited is not None  # narrows for mypy

            session = await self._storage.get_session(
                self._user_id,
                self._agent_id,
                self._session_id,
            )
            if session is None or session.team_id is None:
                return _error(
                    "AgentInvite: this session is not in any team — "
                    "call TeamCreate first.",
                )
            team = await self._storage.get_team(
                self._user_id,
                session.team_id,
            )
            if team is None:
                return _error(
                    f"AgentInvite: team {session.team_id} no longer "
                    f"exists.",
                )
            if team.session_id != self._session_id and not any(
                member.session_id == self._session_id
                for member in await _ensure_team_members(self._storage, self._user_id, team)
            ):
                return _error(
                    "AgentInvite: 当前会话不属于本次协同运行。",
                )

            # Re-fetch the caller and enforce the current whitelist. The
            # toolkit's pool is only a snapshot, so a configuration change
            # made after assembly must still take effect before execution.
            caller = await self._storage.get_agent(
                self._caller_owner_id,
                self._agent_id,
            )
            from .._service._platform_settings import (
                get_global_main_agent_id,
                get_platform_duties,
            )

            global_main_agent_id = await get_global_main_agent_id(
                self._storage,
                self._caller_owner_id,
            )
            from .._agent_collaboration import can_delegate
            duties = await get_platform_duties(self._storage, self._caller_owner_id)

            if not can_delegate(caller, invited, global_main_agent_id, duties):
                return _error(
                    f"AgentInvite: agent {invited.data.name!r} is no longer "
                    "allowed by the caller's agent-call configuration.",
                )

            # Re-fetch so disabling a target takes effect before execution.
            fresh = await self._storage.get_agent(
                invited.user_id,
                invited.id,
            )
            if not can_delegate(caller, fresh, global_main_agent_id, duties):
                return _error(
                    f"AgentInvite: agent {invited.data.name!r} is no "
                    f"longer invitable.",
                )
            invited = fresh

            from .._service._model import (
                managed_chat_model_config,
                resolve_effective_chat_model_config,
            )

            # A fixed caller can differ from its saved session selection.
            # Resolve both policies before borrowing, including reassignment.
            inherited_config = session.config.model_copy(update={
                "chat_model_config": resolve_effective_chat_model_config(
                    caller.data, session.config,
                ),
            })
            borrowed_chat_model = resolve_effective_chat_model_config(
                invited.data, inherited_config,
            )
            borrowed_fallback_model = managed_chat_model_config(
                session.config.fallback_chat_model_config,
            )

            for ancestor_id in ancestor_session_ids(team, self._session_id):
                ancestor = await self._storage.get_session(self._user_id, "", ancestor_id)
                if ancestor is not None and getattr(ancestor, "agent_id", None) == invited.id:
                    return _error("AgentInvite: 不能调用本次运行的上级智能体形成循环。")

            # Duplicate-borrow guard — one team, one borrow per agent.
            existing_members = await _ensure_team_members(
                self._storage,
                self._user_id,
                team,
            )
            existing = next(
                (m for m in existing_members if m.agent_id == invited.id), None,
            )
            if existing is not None:
                if report_recipient_session_id(team, existing.session_id) != self._session_id:
                    return _error("AgentInvite: 目标已由其他阶段调用，请由该阶段继续分配。")
                return await self._reassign_existing(
                    invited, existing, team, session, prompt,
                    chat_model_config=borrowed_chat_model,
                    fallback_chat_model_config=borrowed_fallback_model,
                )

            # Leader session — needed for chat-model / workspace fallback
            # when the invited agent has no existing session, and for the
            # sender-name in the initial team-message hint.
            leader_session = await self._storage.get_session(
                self._user_id,
                "",
                self._session_id,
            )
            if leader_session is None:
                return _error(
                    f"AgentInvite: leader session {team.session_id} "
                    f"for team {team.id} is missing — team is in an "
                    f"inconsistent state.",
                )
            leader_agent = await self._storage.get_agent(
                self._user_id,
                leader_session.agent_id,
            )
            leader_name = (
                leader_agent.data.name
                if leader_agent is not None
                else leader_session.agent_id
            )

            # Reuse the invited agent's primary workspace when available,
            # but do not implicitly reuse that unrelated conversation's
            # model. A fixed agent model wins; otherwise this team-scoped
            # session follows the leader's currently selected model.
            # Platform sessions carry an account/project boundary. Borrowing
            # an agent's unrelated primary workspace would expose another
            # conversation's files through ordinary workspace tools.
            invited_sessions = (
                [] if leader_session.config.platform_context is not None
                else await self._storage.list_sessions(self._user_id, invited.id)
            )
            borrowed_knowledge_config = (
                invited.data.platform_config.knowledge_config
            )
            if invited_sessions:
                primary = invited_sessions[0]
                borrowed_workspace_id = primary.config.workspace_id
                borrowed_knowledge_config = (
                    borrowed_knowledge_config
                    or primary.config.knowledge_config
                )
            else:
                borrowed_workspace_id = (
                    self._workspace_manager.assign_workspace_id(
                        user_id=self._user_id,
                        agent_id=invited.id,
                        session_id=_generate_id(),
                    )
                )
            worker_platform_context = leader_session.config.platform_context
            if worker_platform_context is not None:
                worker_platform_context = worker_platform_context.model_copy(
                    update={
                        "session_role": "worker",
                        "root_session_id": (
                            worker_platform_context.root_session_id
                            or leader_session.id
                        ),
                    },
                )

            # Permission rules and working directories are NOT inherited from
            # the leader. The invited agent does, however, keep its
            # administrator-selected platform permission mode so platform team
            # workers honour the same Auto/Explore policy as direct sessions.
            # PermissionContext.working_directories and allow/deny/ask
            # rules are anchored to the leader's workspace, which the
            # invited agent may not share (it has its own workspace_id).
            # Merging leader dirs / rules would advertise paths the
            # invited agent cannot reach and pull in user confirmations
            # granted against a different filesystem. Nor do we inherit
            # from the invited agent's own primary session — the
            # team-scoped conversation is a separate context; prior
            # "user approved X" state should not silently cross over.
            # Exact-tool rules declared by the authenticated platform session
            # are workspace-independent and are re-applied explicitly. This
            # lets internal orchestration continue in background workers
            # without copying unrelated user approvals from the leader.
            worker_state = AgentState(
                permission_context=apply_platform_tool_allow_rules(
                    PermissionContext(
                        mode=invited.data.platform_config.permission_mode,
                    ),
                    worker_platform_context,
                ),
            )

            invited_display = _display_name(
                invited.data.name,
                invited.id,
            )
            invited_handle = _display_handle(invited.id)
            borrowed = await self._storage.upsert_session(
                user_id=self._user_id,
                agent_id=invited.id,
                config=SessionConfig(
                    workspace_id=borrowed_workspace_id,
                    name=f"team:{team.id}/invited:{invited_handle}",
                    chat_model_config=borrowed_chat_model,
                    fallback_chat_model_config=borrowed_fallback_model,
                    knowledge_config=borrowed_knowledge_config,
                    platform_context=worker_platform_context,
                    memory_run_id=leader_session.config.memory_run_id,
                ),
                state=worker_state,
                source=leader_session.source,
            )
            assigned_revision = await add_and_assign_team_member(
                self._storage,
                self._message_bus,
                user_id=self._user_id,
                team_id=team.id,
                member=TeamMember(
                    owner_id=self._user_id,
                    agent_id=invited.id,
                    session_id=borrowed.id,
                    role="invited",
                    inviter_session_id=self._session_id,
                ),
            )
            if assigned_revision is None:
                raise RuntimeError(
                    "team membership changed before the initial invited "
                    "assignment could be recorded",
                )
            await self._storage.set_session_team_id(
                self._user_id,
                borrowed.id,
                team.id,
            )

            hint = HintBlock(
                hint=(
                    "<system-reminder>You're now invited into a team named "
                    f"'{team.data.name}' led by an agent named "
                    f"'{leader_name}' in this session. All team members "
                    f"can **ONLY** communicate through the `TeamSay` tool. "
                    f"Once you finished the given tasks, or want to "
                    f"communicate with the leader or team members, "
                    f"use `TeamSay`.</system-reminder>\n"
                    f'<team-message from="{leader_name}">\n'
                    f"{prompt}\n"
                    f"</team-message>"
                ),
                source=json.dumps(
                    {
                        "label": "team_message",
                        "sublabel": leader_name,
                    },
                    ensure_ascii=False,
                ),
            )
            await deliver_to_inbox(
                self._message_bus,
                user_id=self._user_id,
                session_id=borrowed.id,
                agent_id=invited.id,
                payload=hint.model_dump(mode="json"),
            )

            return ToolChunk(
                content=[
                    TextBlock(
                        text=(
                            f"Invited {invited_display!r} into team "
                            f"{team.data.name!r}."
                        ),
                    ),
                ],
                metadata={
                    "collaboration_member": {
                        "team_id": team.id,
                        "team_name": team.data.name,
                        "worker_agent_id": invited.id,
                        "worker_agent_name": invited.data.name,
                        "worker_session_id": borrowed.id,
                        "work_revision": assigned_revision,
                        "assigned_at": datetime.now(UTC).isoformat(),
                    },
                },
            )
        except Exception as e:  # pylint: disable=broad-except
            return ToolChunk(
                content=[TextBlock(text=f"AgentInvite failed: {e}")],
                state=ToolResultState.ERROR,
            )

    async def _reassign_existing(
        self, invited, member, team, leader, prompt, *,
        chat_model_config, fallback_chat_model_config,
    ):
        """Reuse a settled worker for another stage, with fresh authorization."""
        if member.settled_revision < member.work_revision:
            return _error("AgentInvite: 目标智能体仍在执行上一阶段，请等待结果后再调用。")
        borrowed = await self._storage.get_session(
            self._user_id, invited.id, member.session_id,
        )
        if borrowed is None:
            return _error("AgentInvite: 协同会话已失效，请通过恢复工具重新建立运行。")
        context = leader.config.platform_context
        if context is not None:
            context = context.model_copy(update={
                "session_role": "worker",
                "root_session_id": context.root_session_id or leader.id,
            })
        state = borrowed.state.model_copy(deep=True)
        state.permission_context = apply_platform_tool_allow_rules(
            PermissionContext(mode=invited.data.platform_config.permission_mode),
            context,
        )
        await self._storage.upsert_session(
            user_id=self._user_id, agent_id=invited.id, session_id=borrowed.id,
            config=borrowed.config.model_copy(update={
                "chat_model_config": chat_model_config,
                "fallback_chat_model_config": fallback_chat_model_config,
                "platform_context": context,
                "memory_run_id": leader.config.memory_run_id,
            }),
            state=state, source=borrowed.source,
        )
        from ._team_say import TeamSay

        result = await TeamSay(
            self._storage, self._message_bus, self._workspace_manager,
            self._user_id, self._session_id, self._agent_id, role="leader",
        )(content=prompt, to=_display_name(invited.data.name, invited.id))
        if result.state != ToolResultState.ERROR:
            current = await self._storage.get_team(self._user_id, team.id)
            updated = next(m for m in current.data.members if m.session_id == borrowed.id)
            result.metadata = {"collaboration_member": {
                "team_id": team.id, "team_name": team.data.name,
                "worker_agent_id": invited.id, "worker_agent_name": invited.data.name,
                "worker_session_id": borrowed.id, "work_revision": updated.work_revision,
                "assigned_at": updated.assigned_at.isoformat(),
            }}
        return result


def _resolve_target(
    pool_by_id: dict[str, "AgentRecord"],
    target: str,
) -> tuple["AgentRecord | None", str | None]:
    """Parse a ``"<name>@<handle>"`` string and look up the pool entry.

    Matches on **both** the name part and the handle so that two
    invitable agents sharing an 8-char UUID4 prefix are still
    disambiguated by the LLM-supplied name. Falls back to a
    handle-only lookup when exactly one pool entry matches the handle,
    which keeps the common single-agent case working. If two or more
    entries share the handle AND the name does not narrow the match,
    an ``ambiguous`` error is returned so the caller can retry.

    Returns ``(record, None)`` on success or ``(None, error_message)``
    on any parse or resolution failure.
    """
    if "@" not in target:
        return None, (
            f"AgentInvite: malformed target {target!r} — expected "
            f'"<name>@<handle>", got no ``@`` separator.'
        )
    name_part, handle = target.rsplit("@", 1)
    name_part = name_part.strip()
    handle = handle.strip()
    if not handle:
        return None, (
            f"AgentInvite: malformed target {target!r} — empty handle "
            f"after ``@``."
        )
    handle_matches = [
        record
        for agent_id, record in pool_by_id.items()
        if _display_handle(agent_id) == handle
    ]
    # Preferred: unique (name, handle) match. Guards against the rare
    # 8-char-prefix collision on distinct agents with distinct names.
    named_matches = [r for r in handle_matches if r.data.name == name_part]
    if len(named_matches) == 1:
        return named_matches[0], None
    if len(named_matches) > 1:
        # Same name AND same handle prefix on multiple pool entries —
        # the display strings are indistinguishable, so no client
        # input could disambiguate. Surface the ids so the caller can
        # see what collided.
        ids = sorted(r.id for r in named_matches)
        return None, (
            f"AgentInvite: target {target!r} is ambiguous — multiple "
            f"invitable agents share this display string: {ids}."
        )
    # Fallback: no name match, but exactly one handle match — accept it.
    if len(handle_matches) == 1:
        return handle_matches[0], None
    if len(handle_matches) > 1:
        colliding = sorted(
            _display_name(r.data.name, r.id) for r in handle_matches
        )
        return None, (
            f"AgentInvite: handle {handle!r} matches multiple invitable "
            f"agents: {colliding}. Retry with the exact display string."
        )
    available = sorted(
        _display_name(a.data.name, a.id) for a in pool_by_id.values()
    )
    return None, (
        f"AgentInvite: no invitable agent matches target {target!r}. "
        f"Available: {available}."
    )


def _error(text: str) -> ToolChunk:
    """Build an ``ERROR``-state :class:`ToolChunk` with a text block.

    Not moved to :mod:`_team_tool_base` because that shape is specific
    to :class:`AgentInvite`'s branchy validation path — the other team
    tools currently inline the same pattern.
    """
    return ToolChunk(
        content=[TextBlock(text=text)],
        state=ToolResultState.ERROR,
    )
