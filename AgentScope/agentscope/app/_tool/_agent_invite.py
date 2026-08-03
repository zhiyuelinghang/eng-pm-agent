# -*- coding: utf-8 -*-
"""The AgentInvite tool — borrows an existing agent into the leader's team.

Unlike :class:`AgentCreate`, which spawns a brand-new worker
(``source='team'``) from a :class:`SubAgentTemplate`, this tool
**borrows** a pre-existing user-owned agent by minting a fresh
team-scoped :class:`SessionRecord` on top of the *existing*
:class:`AgentRecord`.  The borrowed agent keeps its system prompt,
context/react configs, workspace, MCP, skills, and model choice; only
a new session is created so it can hold a parallel conversation for
the team.

When the team is dissolved or the leader is deleted, only the borrowed
session is cleaned up — the underlying :class:`AgentRecord` survives
so the user can still use the agent stand-alone.
"""
from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING

from pydantic import Field

from ._constants import HANDLE_LEN
from ._team_tool_base import _TeamToolBase
from .._team_lifecycle import assign_team_member
from ..message_bus import MessageBusKeys
from .._bus_ops import enqueue_run_trigger
from ..storage import SessionConfig, TeamMember
from ..storage._utils import _ensure_team_members
from ...message import HintBlock, TextBlock, ToolResultState
from ...permission import PermissionContext
from ...state import AgentState
from ...tool import ToolChunk, ParamsBase
from ..._utils._common import _generate_id

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

    The tool is only attached to the leader's toolkit when the calling
    user has at least one agent with ``invitable=True`` and a non-empty
    ``invite_description`` — see the toolkit assembly logic in
    :func:`get_toolkit`. The invitable pool is captured as a **snapshot**
    at attachment time so the tool's ``input_schema`` can enumerate
    concrete targets; ``__call__`` re-fetches the target's record and
    re-checks invitability before minting the session, so a race
    between snapshot and call (e.g. the user just turned off the toggle)
    is caught cleanly.
    """

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
            f"{a.data.invite_config.invite_description}"
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
        - Caller's session is in a team AND is that team's leader.
        - ``target`` is a well-formed ``"<name>@<handle>"`` string whose
          handle prefix-matches an agent id in the current invitable
          pool.
        - The caller's latest agent-call configuration still allows the
          matched agent.
        - The matched agent is still ``invitable=True`` with a
          non-empty ``invite_description`` (guards against a
          toggle-off race between attachment and invocation).
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
            if team.session_id != self._session_id:
                return _error(
                    "AgentInvite: only the team leader can invite "
                    "members; this session is a worker.",
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
            )

            global_main_agent_id = await get_global_main_agent_id(
                self._storage,
                self._caller_owner_id,
                legacy_record=caller,
            )
            caller_is_global_main = (
                caller is not None and global_main_agent_id == caller.id
            )
            global_main_target_allowed = (
                caller_is_global_main
                and invited.data.platform_config.enabled
                and invited.data.platform_config.allow_global_main_call
                and invited.id != global_main_agent_id
            )
            configured_target_allowed = (
                caller is not None
                and not caller_is_global_main
                and caller.data.call_config.allows(invited.id)
            )
            if (
                caller is None
                or invited.id == caller.id
                or not (
                    global_main_target_allowed
                    or configured_target_allowed
                )
            ):
                return _error(
                    f"AgentInvite: agent {invited.data.name!r} is no longer "
                    "allowed by the caller's agent-call configuration.",
                )

            # Re-fetch fresh — the snapshot could be stale if the user
            # just toggled the invite off.
            fresh = await self._storage.get_agent(
                invited.user_id,
                invited.id,
            )
            if (
                fresh is None
                or not fresh.data.invite_config.invitable
                or not (
                    fresh.data.invite_config.invite_description or ""
                ).strip()
                or (
                    caller_is_global_main
                    and (
                        fresh.id == global_main_agent_id
                        or not fresh.data.platform_config.enabled
                        or not (
                            fresh.data.platform_config.allow_global_main_call
                        )
                    )
                )
            ):
                return _error(
                    f"AgentInvite: agent {invited.data.name!r} is no "
                    f"longer invitable.",
                )
            invited = fresh

            # Duplicate-borrow guard — one team, one borrow per agent.
            existing_members = await _ensure_team_members(
                self._storage,
                self._user_id,
                team,
            )
            if any(m.agent_id == invited.id for m in existing_members):
                return _error(
                    f"AgentInvite: agent {invited.data.name!r} is "
                    f"already a member of team "
                    f"{team.data.name!r}.",
                )

            # Leader session — needed for chat-model / workspace fallback
            # when the invited agent has no existing session, and for the
            # sender-name in the initial team-message hint.
            leader_session = await self._storage.get_session(
                self._user_id,
                "",
                team.session_id,
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
            invited_sessions = await self._storage.list_sessions(
                self._user_id,
                invited.id,
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
            invited_policy = invited.data.model_policy
            borrowed_chat_model = (
                invited_policy.chat_model_config
                if invited_policy.mode == "fixed"
                else leader_session.config.chat_model_config
            )
            borrowed_fallback_model = (
                leader_session.config.fallback_chat_model_config
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
            worker_state = AgentState(
                permission_context=PermissionContext(
                    mode=invited.data.platform_config.permission_mode,
                ),
            )

            invited_display = _display_name(
                invited.data.name,
                invited.id,
            )
            invited_handle = _display_handle(invited.id)
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
                ),
                state=worker_state,
                source=leader_session.source,
            )
            await self._storage.set_session_team_id(
                self._user_id,
                borrowed.id,
                team.id,
            )

            team.data.members = [
                *existing_members,
                TeamMember(
                    owner_id=self._user_id,
                    agent_id=invited.id,
                    session_id=borrowed.id,
                    role="invited",
                ),
            ]
            await self._storage.upsert_team(self._user_id, team)
            assigned_revision = await assign_team_member(
                self._storage,
                self._message_bus,
                user_id=self._user_id,
                team_id=team.id,
                member_session_id=borrowed.id,
            )
            if assigned_revision is None:
                raise RuntimeError(
                    "invited member disappeared before its initial "
                    "assignment could be recorded",
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
            await self._message_bus.queue_push(
                MessageBusKeys.inbox(borrowed.id),
                hint.model_dump(mode="json"),
            )
            await enqueue_run_trigger(
                self._message_bus,
                user_id=self._user_id,
                session_id=borrowed.id,
                agent_id=invited.id,
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
            )
        except Exception as e:  # pylint: disable=broad-except
            return ToolChunk(
                content=[TextBlock(text=f"AgentInvite failed: {e}")],
                state=ToolResultState.ERROR,
            )


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
