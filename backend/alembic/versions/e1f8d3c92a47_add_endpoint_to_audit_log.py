"""Add endpoint column to audit_log for HIPAA access path recording.

Revision ID: e1f8d3c92a47
Revises: d4b7e2f91c30
Create Date: 2026-07-21

Hand-authored per US-008/TASK-002 gap resolution (autogenerate disabled).

The US-008 TASK-002 spec requires the audit_log to record the request
endpoint (URL path) so compliance queries can determine WHICH API endpoint
was accessed, not just which resource type.

The initial schema migration (a3f9e2c10b4d) did not include an `endpoint`
column; this migration adds it as a nullable VARCHAR(255) so existing rows
are unaffected.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f8d3c92a47"
down_revision: Union[str, None] = "d4b7e2f91c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("endpoint", sa.String(255), nullable=True),
    )
    op.create_index("ix_audit_log_endpoint", "audit_log", ["endpoint"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_endpoint", table_name="audit_log")
    op.drop_column("audit_log", "endpoint")
