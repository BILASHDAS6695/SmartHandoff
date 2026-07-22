"""AppUser ORM model — staff accounts managed by the Identity Provider.

Users are provisioned via SCIM 2.0 (AIR-032). Role claims arrive in JWT
and are validated against this table by RBAC middleware (SEC-002, AIR-031).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin


class AppUser(Base, TimestampMixin):
    """Staff user account.

    Created/updated by SCIM 2.0 provisioning endpoint (AIR-032).
    Deprovisioning sets `is_active=False` and invalidates JWT via Redis blocklist.
    """

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Identity provider subject claim (`sub` in JWT)
    idp_subject: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
        unique=True,
        comment="OIDC `sub` claim from Identity Provider; used to resolve user on login",
    )

    email: Mapped[str] = mapped_column(
        sa.String(320),  # RFC 5321 max email length
        nullable=False,
        unique=True,
    )

    full_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    role: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
        comment="One of: admin, physician, nurse, pharmacist, bed_manager",
    )

    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        comment="Set to False on SCIM deprovisioning (AIR-032)",
    )

    # ── JWT revocation fields (US-059) ────────────────────────────────────────

    current_jti: Mapped[str | None] = mapped_column(
        sa.String(36),
        nullable=True,
        index=True,
        unique=True,
        comment="Most-recently-issued JWT jti; updated on every login (US-059/TASK-004)",
    )

    deprovisioned_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        comment="Set by DELETE /api/v1/admin/users/{id}; non-null = deprovisioned (US-059)",
    )

    unit: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
        comment="Hospital unit assignment for nurses (scopes patient list access)",
    )

    # ── SCIM provisioning fields (US-060) ─────────────────────────────────────

    scim_id: Mapped[str | None] = mapped_column(
        sa.String(256),
        nullable=True,
        index=True,
        unique=True,
        comment="IdP-assigned SCIM externalId; used for SCIM→SmartHandoff cross-reference (US-060)",
    )

    __table_args__ = (
        sa.Index("ix_app_user_idp_subject", "idp_subject", unique=True),
        sa.Index("ix_app_user_email", "email", unique=True),
        sa.Index("ix_app_user_role_active", "role", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<AppUser id={self.id} role={self.role} active={self.is_active}>"
