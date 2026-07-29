"""Add chatbot_escalation table for US-045 Care Team Escalation.

Revision ID: x7u0t1q48p23
Revises: w7t0s3r68p22
Create Date: 2026-07-29 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "x7u0t1q48p23"
down_revision: Union[str, None] = "w7t0s3r68p22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create chatbot_escalation table.

    US-045: Records care team escalations triggered by urgency detection.
    Includes columns for escalation tracking, acknowledgement, and SLA monitoring.
    """
    op.create_table(
        "chatbot_escalation",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Primary key — auto-generated UUID v4",
        ),
        sa.Column(
            "encounter_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK to encounter — used for patient-scoped GET queries",
        ),
        sa.Column(
            "transcript_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK to the chat_transcript row that triggered urgency detection",
        ),
        sa.Column(
            "notified_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK to app_user — the on-call nurse who received the alert",
        ),
        sa.Column(
            "notified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="UTC timestamp when Pub/Sub escalation alert was published",
        ),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when on-call nurse acknowledged the alert; NULL = unacknowledged",
        ),
        sa.Column(
            "channel",
            sa.String(20),
            nullable=False,
            comment="Notification channel used: SMS or IN_APP",
        ),
        sa.Column(
            "urgency_message",
            sa.Text,
            nullable=False,
            comment="Verbatim patient urgency message — minimum PHI; MUST NOT appear in logs",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Row insert timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["encounter_id"],
            ["encounter.id"],
            name="fk_chatbot_escalation_encounter",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_message_id"],
            ["chat_transcript.id"],
            name="fk_chatbot_escalation_transcript",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notified_user_id"],
            ["app_user.id"],
            name="fk_chatbot_escalation_notified_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chatbot_escalation"),
    )

    # Create index on encounter_id for patient-scoped queries
    op.create_index(
        "ix_chatbot_escalation_encounter_notified",
        "chatbot_escalation",
        ["encounter_id", "notified_at"],
        postgresql_using="btree",
    )

    # Create index on encounter_id for general queries
    op.create_index(
        "ix_chatbot_escalation_encounter",
        "chatbot_escalation",
        ["encounter_id"],
        postgresql_using="btree",
    )


def downgrade() -> None:
    """Drop chatbot_escalation table and indexes."""
    op.drop_index("ix_chatbot_escalation_encounter", table_name="chatbot_escalation")
    op.drop_index(
        "ix_chatbot_escalation_encounter_notified", table_name="chatbot_escalation"
    )
    op.drop_table("chatbot_escalation")
