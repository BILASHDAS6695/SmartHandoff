"""AuditLog ORM model — immutable PHI access record.

DR-003: Append-only. PostgreSQL RLS (DENY DELETE/UPDATE) enforced by
migration 0002_audit_log_rls.py (TASK-007).
BR-023: 6-year retention minimum.
US-058: AuditAction enum + write_audit_entry helpers added for middleware.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditAction(str, enum.Enum):
    """Permitted action values for audit_log.action (US-058).

    Maps to the plain-string ``action`` column.  String subclass so
    SQLAlchemy stores and reads the enum as its value without needing a
    DB-level ENUM type.
    """

    READ = "read"
    WRITE = "write"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    REJECT = "reject"
    RESOLVE = "resolve"


class AuditLog(Base):
    """Immutable audit log entry.

    Written by the HIPAA Audit Logger middleware on every PHI access.
    The application DB user does NOT have DELETE or UPDATE privileges on
    this table — enforced by the Row Security Policy in migration 0002.

    NOTE: No `TimestampMixin` — `created_at` is set once at INSERT only.
    `updated_at` would be misleading for an append-only table.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    # Who accessed the data
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=True,
        comment="AppUser.id of the actor; NULL for system/agent actions",
    )
    user_role: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)

    # What was accessed
    resource_type: Mapped[str] = mapped_column(
        sa.String(64),
        nullable=False,
        comment="e.g., 'patient', 'encounter', 'document', 'medication'",
    )
    resource_id: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
        comment="String representation of the resource primary key",
    )
    action: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        comment="One of: read, create, update, delete, approve, export",
    )

    # Request context (no PHI in these fields — log sanitiser strips it)
    ip_address: Mapped[str | None] = mapped_column(sa.String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    endpoint: Mapped[str | None] = mapped_column(
        sa.String(255),
        nullable=True,
        comment="Request URL path, e.g. /api/v1/patients/abc-123",
    )
    request_id: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
        comment="Distributed trace ID for correlation with Cloud Logging",
    )

    outcome: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        server_default="success",
        comment="One of: success, denied, error",
    )

    __table_args__ = (
        sa.Index("ix_audit_log_user_id", "user_id"),
        sa.Index("ix_audit_log_resource", "resource_type", "resource_id"),
        sa.Index("ix_audit_log_created_at", "created_at"),
    )
