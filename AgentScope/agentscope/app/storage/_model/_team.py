# -*- coding: utf-8 -*-
"""The team storage class."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ._base import _RecordBase


class TeamMember(BaseModel):
    """An entry in a team's member roster.

    Unlike the legacy :attr:`TeamData.member_ids`, this carries both the
    agent id AND the session id — required because an *invited* member's
    agent (e.g. Monday) can have multiple sessions of its own; the team
    only wants the one it created when the leader called ``AgentInvite``.
    The ``role`` tag then drives cascade behavior (see
    :meth:`SessionService.delete_team`): ``created`` members are fully
    deleted with the team, ``invited`` members only lose the borrowed
    session while their :class:`AgentRecord` survives.
    """

    owner_id: str = Field(
        description=(
            "Owner of the member's agent. Always equals the team owner "
            "in today's user-only invite pool, but is stored explicitly "
            "so a future admin-share layer (agents borrowed across users) "
            "can slot in without a schema migration. Distinct name from "
            ":attr:`TeamRecord.user_id` on purpose — the surrounding "
            "team already carries the team owner in context, so calling "
            "this field ``user_id`` too would be ambiguous."
        ),
    )

    agent_id: str = Field(
        description="The member agent's id.",
    )

    session_id: str = Field(
        description=(
            "The team-scoped session id for this member. For ``created`` "
            "members this is the sole session (1:1 with the agent). For "
            "``invited`` members this is the freshly-minted session that "
            "``AgentInvite`` created — the agent's other sessions are "
            "unrelated to this team."
        ),
    )

    role: Literal["created", "invited"] = Field(
        description=(
            "How this member joined the team. ``created`` — spawned "
            "from a :class:`SubAgentTemplate` via ``AgentCreate``, "
            "deleted with the team. ``invited`` — a pre-existing "
            "user-owned agent borrowed via ``AgentInvite``, retains its "
            ":class:`AgentRecord` when the team is dissolved."
        ),
    )

    work_revision: int = Field(
        default=0,
        ge=0,
        description=(
            "Revision of the latest task assigned to this member. A new "
            "leader-to-member assignment advances the team's global work "
            "revision and stores that value here."
        ),
    )

    settled_revision: int = Field(
        default=0,
        ge=0,
        description=(
            "Latest assigned revision that has produced a terminal report. "
            "The member still has outstanding work while this is smaller "
            "than ``work_revision``."
        ),
    )

    active_revision: int = Field(
        default=0,
        ge=0,
        description=(
            "Assignment revision currently being executed by the member. "
            "This remains stable when another task is queued during the "
            "active run, preventing that later task from being settled by "
            "the earlier reply."
        ),
    )

    work_status: Literal[
        "idle",
        "queued",
        "running",
        "reported",
        "completed",
        "failed",
        "interrupted",
    ] = Field(
        default="idle",
        description=(
            "Durable lifecycle of the member's latest assignment. Unlike "
            "the transient session run lock, this survives the idle gaps "
            "between asynchronous team turns."
        ),
    )

    assigned_at: datetime | None = Field(
        default=None,
        description="When the latest assignment was queued.",
    )

    started_at: datetime | None = Field(
        default=None,
        description="When the member started the latest assignment.",
    )

    settled_at: datetime | None = Field(
        default=None,
        description="When the latest assignment reached a terminal state.",
    )

    last_reply_id: str | None = Field(
        default=None,
        description="Terminal reply id for the latest settled assignment.",
    )

    last_error: str | None = Field(
        default=None,
        description="Failure detail for the latest assignment, if any.",
    )


class TeamData(BaseModel):
    """The team data model."""

    name: str = Field(
        description="Display name of the team.",
        title="Name",
    )

    description: str = Field(
        default="",
        description=(
            "What the team is for — its overall goal or shared context. "
            "Wired into every member's system prompt so all members share "
            "the same high-level understanding of why the team exists."
        ),
        title="Description",
    )

    member_ids: list[str] = Field(
        default_factory=list,
        description=(
            "**Deprecated** — legacy roster of worker agent ids from "
            "before the ``AgentInvite`` era, when every member was "
            "team-spawned (``source='team'``) with a 1:1 agent-session "
            "mapping. New code should read :attr:`members` via the "
            "``ensure_team_members`` helper, which migrates any records "
            "still using this field to the richer schema on first read."
        ),
        title="Member Ids",
        deprecated=True,
    )

    members: list[TeamMember] = Field(
        default_factory=list,
        description=(
            "Explicit member roster with role + session id per entry. "
            "Read this via the ``ensure_team_members`` helper so legacy "
            "records with only :attr:`member_ids` populated are migrated "
            "transparently."
        ),
        title="Members",
    )

    work_revision: int = Field(
        default=0,
        ge=0,
        description=(
            "Monotonic revision advanced whenever the leader assigns work "
            "to a member."
        ),
        title="Work Revision",
    )

    leader_completed_revision: int = Field(
        default=0,
        ge=0,
        description=(
            "Latest team work revision for which the leader completed a "
            "turn after every assigned member had settled. Team work is "
            "not globally complete until this catches up to "
            "``work_revision``."
        ),
        title="Leader Completed Revision",
    )

    settlement_revision: int = Field(
        default=0,
        ge=0,
        description=(
            "Monotonic counter advanced whenever a member assignment "
            "settles. A leader turn only closes team work when no new "
            "settlement occurred after that turn started."
        ),
        title="Settlement Revision",
    )


class TeamRecord(_RecordBase):
    """The team ORM model.

    Team membership is session-level: the leader is identified by its
    ``session_id`` (since a user agent can lead multiple teams across
    different sessions). Workers are identified by
    :class:`TeamMember` entries in :attr:`TeamData.members`, accessed
    via the ``ensure_team_members`` helper which handles migration from
    the legacy :attr:`TeamData.member_ids` shape.
    """

    user_id: str
    """The user id."""

    session_id: str
    """The leader session id — the session that called ``create_team``."""

    data: TeamData
    """The team data."""
