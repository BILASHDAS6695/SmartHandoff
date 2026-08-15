"""AgentTask ORM model — tracks AI agent task lifecycle and results.

DR-012: Agent task records retained 2 years.
One task row is created per agent execution per encounter.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class AgentTaskStatus(str, enum.Enum):
    """Valid agent task lifecycle statuses.

    Terminal statuses (COMPLETED, CANCELLED, FAILED) are never overwritten
    by bulk cancellation operations (US-015).
    
    US-019: BLOCKED status indicates task cannot proceed due to patient
    resolution issues (ambiguous or unresolved patient identity).
    """

    QUEUED           = "queued"
    PENDING          = "pending"
    IN_PROGRESS      = "running"
    BLOCKED          = "blocked"     # US-019: patient resolution issue
    COMPLETED        = "completed"
    FAILED           = "failed"
    PENDING_APPROVAL = "pending_approval"
    CANCELLED        = "cancelled"   # US-015: set by CancellationService on A11/A12


# Statuses that are terminal — bulk cancel must not overwrite these
AGENT_TASK_TERMINAL_STATUSES: frozenset[AgentTaskStatus] = frozenset(
    {AgentTaskStatus.COMPLETED, AgentTaskStatus.CANCELLED, AgentTaskStatus.FAILED}
)


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

    # Denormalised routing fields — populated at task creation from the parent Encounter.
    # Required by SignalR group router (US-022) to avoid a JOIN on every broadcast.
    unit_id: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        comment="Hospital unit ID for SignalR group routing (US-022)",
    )
    target_role: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
        comment="Target clinical role for SignalR group routing (US-022)",
    )

    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="queued",
        comment="One of: queued, pending, running, blocked, completed, failed, pending_approval, cancelled",
    )

    # US-019: Reason task is blocked (e.g., patient identity unresolved)
    blocked_reason: Mapped[str | None] = mapped_column(
        sa.String,
        nullable=True,
        comment="Reason task is blocked (e.g., patient identity ambiguous or unresolved) - US-019",
    )

    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # SLA fields — populated by SLAMonitor (app/monitor/sla_monitor.py, US-021)
    sla_threshold_minutes: Mapped[int | None] = mapped_column(
        sa.Integer,
        nullable=True,
        comment="SLA threshold in minutes for this agent type (from sla_config.yaml).",
    )
    sla_breached: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("false"),
        comment="Set to TRUE by SLAMonitor when task exceeds its SLA threshold.",
    )
    
    # SLA escalation idempotency — US-034
    sla_escalation_sent_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
        comment=(
            "Timestamp when a CHARGE_PHARMACIST_ESCALATION notification was last sent "
            "for this task. NULL means no escalation has been sent. "
            "Set by MedRecSLAMonitor (US-034); cleared by override endpoint (US-034 AC4)."
        ),
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

    # Structured agent output/results (bed assignment, document id, risk score, etc.)
    output: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Structured agent output: bed assignment, document id, risk score, etc.",
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="agent_tasks",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_agent_task_encounter_agent", "encounter_id", "agent_type"),
        sa.Index("ix_agent_task_status", "status"),
        sa.Index(
            "ix_agent_task_active_status_created",
            "status",
            "created_at",
            postgresql_where=sa.text("status IN ('IN_PROGRESS', 'PENDING')"),
        ),
        sa.UniqueConstraint(
            "encounter_id",
            "agent_type",
            "pubsub_message_id",
            name="uq_agent_task_idempotency",
        ),
    )
