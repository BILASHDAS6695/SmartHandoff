"""Document ORM model — AI-generated clinical documents.

DR-013: Document content (PHI) encrypted at rest via EncryptedString (US-007).
DR-013: Retained 7 years with encounter.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.encryption import EncryptedString
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class Document(Base, TimestampMixin):
    """AI-generated clinical document (discharge summary, patient instructions, etc.).

    `content` is encrypted via EncryptedString TypeDecorator (US-007).
    Human approval is required before status transitions to 'approved' (FR-020).
    """

    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    encounter_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("encounter.id", ondelete="RESTRICT"),
        nullable=False,
    )

    document_type: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        comment=(
            "One of: discharge_summary, patient_instructions, "
            "medication_reconciliation, follow_up_plan"
        ),
    )

    # PHI content encrypted via US-007 EncryptedString (DR-002, DR-013)
    content: Mapped[str] = mapped_column(
        EncryptedString,
        nullable=False,
        comment="Document body — AES-256-GCM encrypted (US-007)",
    )

    language_code: Mapped[str] = mapped_column(
        sa.String(8),
        nullable=False,
        server_default="en",
        comment="Document language (FR-022): en, es, fr, zh, pt",
    )

    status: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        server_default="draft",
        comment="One of: draft, pending_approval, approved, rejected",
    )

    generation_type: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="LLM",
        comment="One of: LLM, TEMPLATE — TEMPLATE set on Vertex AI fallback (AIR-022)",
    )

    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="documents",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_document_encounter_type", "encounter_id", "document_type"),
        sa.Index("ix_document_status", "status"),
    )
