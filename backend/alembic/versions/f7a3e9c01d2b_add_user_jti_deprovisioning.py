"""Add current_jti and deprovisioned_at to app_user.

Revision ID: f7a3e9c01d2b
Revises: e2a4f7b91c35
Create Date: 2026-07-22

US-059/TASK-004 — deprovisioning via JWT blocklist (AIR-032)
Adds:
    app_user.current_jti       — most-recently-issued JWT ID (enables per-token blocklisting)
    app_user.deprovisioned_at  — UTC timestamp set by DELETE /api/v1/admin/users/{id}
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = "f7a3e9c01d2b"
down_revision = "e2a4f7b91c35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "current_jti",
            sa.String(36),   # UUID string length (8-4-4-4-12)
            nullable=True,
            comment="Most-recently-issued JWT ID; used for immediate revocation on deprovision",
        ),
    )
    op.add_column(
        "app_user",
        sa.Column(
            "deprovisioned_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp of admin-initiated deprovisioning; non-null = deprovisioned",
        ),
    )
    # Unique index for fast jti lookup during deprovisioning
    op.create_index(
        "ix_app_user_current_jti",
        "app_user",
        ["current_jti"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_app_user_current_jti", table_name="app_user")
    op.drop_column("app_user", "deprovisioned_at")
    op.drop_column("app_user", "current_jti")
