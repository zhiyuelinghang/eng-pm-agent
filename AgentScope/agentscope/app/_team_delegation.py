"""Parent-child delegation inside one observable collaboration run."""

from .storage import TeamMember, TeamRecord


def team_members(team: TeamRecord) -> list[TeamMember]:
    return getattr(getattr(team, "data", None), "members", [])


def report_recipient_session_id(team: TeamRecord, session_id: str) -> str:
    member = next((item for item in team_members(team) if item.session_id == session_id), None)
    return getattr(member, "inviter_session_id", None) or team.session_id


def has_pending_delegations(team: TeamRecord, session_id: str) -> bool:
    return any(
        getattr(member, "inviter_session_id", None) == session_id
        and member.settled_revision < member.work_revision
        for member in team_members(team)
    )


def ancestor_session_ids(team: TeamRecord, session_id: str) -> set[str]:
    ancestors = {team.session_id, session_id}
    current = session_id
    while current != team.session_id:
        parent = report_recipient_session_id(team, current)
        if parent in ancestors:
            break
        ancestors.add(parent)
        current = parent
    return ancestors
