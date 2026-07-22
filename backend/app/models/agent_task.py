"""AgentTask ORM model — tracks AI agent task lifecycle and results.

DR-012: Agent task records retained 2 years.
One task row is created per agent execution per encounter.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class AgentTask(Base, TimestampMixin):
    """Agent task execution record.

    Created by the Coordinator Agent for each agent type triggered by
    an ADT event. Status transitions: queued → running → completed / failed.
    """

    __tablename__ = "agent_task"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="CASCADE"),
        nullable=False,
    )

    agent_type: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        comment=(
            "One of: coordinator, documentation, medication_reconciliation, "
            "bed_management, follow_up_care, patient_communication"
        ),
    )

    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="queued",
        comment="One of: queued, running, completed, failed, pending_approval",
    )

    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # Idempotency: prevents duplicate agent triggers for the same encounter + agent
    pubsub_message_id: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
        comment="Pub/Sub message ID; used for idempotency check before processing (AR-008)",
    )

    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default="0"
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="agent_tasks",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_agent_task_encounter_agent", "encounter_id", "agent_type"),
        sa.Index("ix_agent_task_status", "status"),
        sa.UniqueConstraint(
            "encounter_id",
            "agent_type",
            "pubsub_message_id",
            name="uq_agent_task_idempotency",
        ),
    )
