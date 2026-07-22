"""Add scim_id to app_user for IdP cross-reference.

Revision ID: a1b2c3d4e5f6
Revises: f7a3e9c01d2b

US-060 Technical Notes — scim_id stored on app_user for SCIM IdP cross-reference
AIR-032               — SCIM IdP to SmartHandoff cross-reference
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = "a1b2c3d4e5f6"
down_revision = "f7a3e9c01d2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column(
            "scim_id",
            sa.String(256),
            nullable=True,
            comment=(
                "IdP-assigned SCIM externalId; "
                "used for SCIM→SmartHandoff cross-reference (US-060)"
            ),
        ),
    )
    op.create_index(
        "ix_app_user_scim_id",
        "app_user",
        ["scim_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_app_user_scim_id", table_name="app_user")
    op.drop_column("app_user", "scim_id")
