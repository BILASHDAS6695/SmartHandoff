"""Add user_agent column to audit_log table.

Revision ID: e2a4f7b91c35
Revises: e1f8d3c92a47
Create Date: 2026-07-22

US-058/TASK-001: The audit_log table (provisioned by US-008) requires a
``user_agent`` TEXT column to record the HTTP User-Agent header value per
the DoD requirement.  No PHI is stored here.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = "e2a4f7b91c35"
down_revision = "e1f8d3c92a47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("user_agent", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_log", "user_agent")
