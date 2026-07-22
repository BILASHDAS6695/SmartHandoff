"""Patient ORM model.

PHI columns use TypeDecorators from US-007 (AES-256-GCM encryption).
DR-002: PHI fields encrypted at rest.
DR-005: Soft deletes — `deleted_at` via SoftDeleteMixin.
DR-020: MRN deduplication via unique constraint on deterministic ciphertext.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.encryption import DeterministicEncryptedString, EncryptedString
from app.db.mixins import SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.encounter import Encounter


class Patient(Base, TimestampMixin, SoftDeleteMixin):
    """Represents a hospital patient.

    All PHI fields are encrypted at the ORM layer using AES-256-GCM (US-007).
    The `mrn_encrypted` column uses deterministic encryption to support the
    unique index required for MRN deduplication (DR-020).
    """

    __tablename__ = "patient"

    # Primary key — UUID v4, generated application-side
    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # PHI fields — encrypted via US-007 TypeDecorators (DR-002)
    first_name: Mapped[str] = mapped_column(EncryptedString(255), nullable=False)
    last_name: Mapped[str] = mapped_column(EncryptedString(255), nullable=False)
    date_of_birth: Mapped[str] = mapped_column(
        EncryptedString(64),
        nullable=False,
        comment="Stored as ISO-8601 string (YYYY-MM-DD) then encrypted",
    )
    phone: Mapped[str | None] = mapped_column(EncryptedString(64), nullable=True)
    email: Mapped[str | None] = mapped_column(EncryptedString(255), nullable=True)

    # MRN uses deterministic encryption to support unique constraint (DR-020)
    mrn_encrypted: Mapped[str] = mapped_column(
        DeterministicEncryptedString(256),
        nullable=False,
        unique=True,  # DB-enforced uniqueness; same plaintext → same ciphertext
        comment="Medical Record Number — deterministically encrypted for unique indexing",
    )

    # Non-PHI fields
    language_code: Mapped[str] = mapped_column(
        sa.String(8),
        nullable=False,
        server_default="en",
        comment="IETF BCP 47 language tag (e.g., en, es, fr) for document generation",
    )

    # Relationships
    encounters: Mapped[list["Encounter"]] = relationship(
        "Encounter",
        back_populates="patient",
        lazy="select",
    )

    __table_args__ = (
        sa.Index("ix_patient_mrn_encrypted", "mrn_encrypted", unique=True),
        sa.Index("ix_patient_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        return f"<Patient id={self.id} mrn=[ENCRYPTED]>"
