"""Reusable SQLAlchemy ORM mixins for timestamp management and soft deletes.

DR-005: Soft deletes on `patient` and `encounter` — no hard deletes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds `created_at` and `updated_at` columns to any model.

    `created_at` is set once at INSERT time (server default).
    `updated_at` is updated on every UPDATE (onupdate trigger).
    Both columns store UTC timestamps.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Adds `deleted_at` column and active-record query helper.

    DR-005: Patient and encounter records are never hard-deleted.
    `deleted_at=NULL` → active record.
    `deleted_at=<timestamp>` → soft-deleted; excluded from standard queries.

    Usage:
        # Standard query (excludes deleted):
        stmt = select(Patient).where(Patient.deleted_at.is_(None))

        # Include deleted (admin / audit use only):
        stmt = select(Patient)  # no filter
    """

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        index=True,  # Index supports `WHERE deleted_at IS NULL` queries
    )

    def soft_delete(self) -> None:
        """Mark this record as deleted by setting `deleted_at` to UTC now.

        Does NOT flush or commit — caller is responsible for the session.
        """
        self.deleted_at = datetime.now(tz=timezone.utc)

    @property
    def is_deleted(self) -> bool:
        """Return True if this record has been soft-deleted."""
        return self.deleted_at is not None
