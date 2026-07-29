"""US-044 TASK-004: Add urgency_flag to chatbot_transcript table

Adds urgency detection flag to chatbot_transcript table for persisting
whether the UrgencyDetector flagged a patient message as urgent (US-044).

Chatbot transcript changes:
    - urgency_flag: BOOLEAN — True when UrgencyDetector.detect() returns is_urgent=True
    - Partial index on urgency_flag=TRUE for fast query of urgent messages
    - Enables care team and analytics queries on urgent interactions

Design refs:
    US-044 AC Scenario 1(c) — urgency_flag persisted to DB
    design.md §6.3 DR-016 — chatbot transcripts in Cloud SQL
    design.md §7.5 AIR-040 — Notification Service dispatch via Pub/Sub

Revision ID: h2e5c8d91f36
Revises:     g1d4e7a93c26
Create Date: 2026-07-29 00:00:00.000000
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "h2e5c8d91f36"
down_revision: Union[str, None] = "g1d4e7a93c26"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Add urgency_flag column to chatbot_transcript table."""
    # Add urgency_flag column with default FALSE
    op.add_column(
        "chatbot_transcript",
        sa.Column(
            "urgency_flag",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True when UrgencyDetector flagged this message as urgent (US-044)",
        ),
    )

    # Create partial index for fast query of urgent messages
    op.create_index(
        "ix_chatbot_transcript_urgency_flag",
        "chatbot_transcript",
        ["urgency_flag"],
        postgresql_where=sa.text("urgency_flag = true"),
    )


def downgrade() -> None:
    """Remove urgency_flag column and index from chatbot_transcript table."""
    # Drop partial index
    op.drop_index("ix_chatbot_transcript_urgency_flag", table_name="chatbot_transcript")

    # Drop urgency_flag column
    op.drop_column("chatbot_transcript", "urgency_flag")
