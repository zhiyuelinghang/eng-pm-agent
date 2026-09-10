"""Keep specialist writes on an open draft in the caller's own session."""
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProjectInitializationDraft, ProjectInitializationDraftSection


def require_writable_initialization_draft(
    db: Session, context: Any, operation: str, arguments: dict[str, Any],
    values: dict[str, Any], actor_agent_id: str | None,
) -> None:
    draft_id = values.get("draft_id")
    if operation == "update":
        section = db.scalar(select(ProjectInitializationDraftSection).where(
            ProjectInitializationDraftSection.id == arguments.get("record_id"),
            ProjectInitializationDraftSection.project_id == context.project.id,
            ProjectInitializationDraftSection.conversation_id == context.conversation.id,
            ProjectInitializationDraftSection.writer_agent_id == actor_agent_id,
        ))
        if section is None:
            raise HTTPException(status_code=404, detail="草稿分区不存在或不属于当前智能体会话")
        if draft_id is not None and draft_id != section.draft_id:
            raise HTTPException(status_code=422, detail="不能将草稿分区转移到其他草稿")
        draft_id = section.draft_id
    if not isinstance(draft_id, int) or isinstance(draft_id, bool):
        raise HTTPException(status_code=422, detail="必须提供当前初始化草稿 ID")
    # Serialize specialist revisions on PostgreSQL so concurrent section writes
    # cannot both publish the same draft revision. SQLite serializes writes.
    draft = db.scalar(select(ProjectInitializationDraft).where(
        ProjectInitializationDraft.id == draft_id,
        ProjectInitializationDraft.project_id == context.project.id,
        ProjectInitializationDraft.conversation_id == context.conversation.id,
    ).execution_options(populate_existing=True).with_for_update())
    if draft is None:
        raise HTTPException(status_code=404, detail="初始化草稿不存在或不属于当前会话")
    if draft.status in {"applied", "rejected"}:
        raise HTTPException(status_code=409, detail="该草稿已结束，请为本次资料新建草稿")
