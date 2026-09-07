"""Agent-to-database-capability assignment model boundary."""

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, TimestampMixin


class DatabaseInteractionAgentAssignment(TimestampMixin, Base):
    """Durable assignment state for one AgentScope agent and capability."""

    __tablename__ = "database_interaction_agent_assignments"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "interaction_id",
            name="uq_database_interaction_agent_assignment",
        ),
        Index(
            "ix_database_interaction_assignments_agent",
            "agent_id",
            "assigned",
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(128))
    interaction_id: Mapped[int] = mapped_column(
        ForeignKey("database_interactions.id", ondelete="CASCADE"),
        index=True,
    )
    assigned: Mapped[bool] = mapped_column(Boolean, default=False)
