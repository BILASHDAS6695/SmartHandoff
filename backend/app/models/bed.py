"""Bed ORM model — hospital bed inventory managed by the Bed Management Agent.

Used by the `mv_bed_board` materialised view (DR-007, FR-040–FR-043).
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Bed(Base, TimestampMixin):
    """Hospital bed record.

    The Bed Management Agent updates `status` and `predicted_discharge_at`
    based on ADT events and ML inference (FR-040–FR-043).
    """

    __tablename__ = "bed"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    bed_number: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        comment="Human-readable bed identifier (e.g., '4B-12')",
    )

    unit: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        comment="Hospital unit (e.g., 'ICU', 'Cardiology', 'ED')",
    )

    ward: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="available",
        comment="One of: available, occupied, cleaning, maintenance, blocked",
    )

    # Optional FK to current encounter (nullable — bed may be unoccupied)
    current_encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="SET NULL"),
        nullable=True,
    )

    predicted_discharge_at: Mapped[sa.DateTime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        comment="ML-predicted discharge time for bed board planning (FR-042)",
    )

    __table_args__ = (
        sa.UniqueConstraint("unit", "bed_number", name="uq_bed_unit_number"),
        sa.Index("ix_bed_unit_status", "unit", "status"),
    )

    def __repr__(self) -> str:
        return f"<Bed {self.unit}/{self.bed_number} status={self.status}>"
