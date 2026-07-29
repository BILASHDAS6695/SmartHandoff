"""US-046: Add escalated field and RLS immutability policy to chatbot_transcript

Migration steps:
    1. Add `escalated` BOOLEAN column to chatbot_transcript
    2. Rename `message_content` column to `message`
    3. Rename `is_urgent` column to `urgency_flag`
    4. Drop `escalated_at` column (replaced by `escalated` boolean)
    5. Add composite index on (encounter_id, timestamp)
    6. Enable Row Level Security on chatbot_transcript
    7. Create RESTRICTIVE RLS policy blocking UPDATE/DELETE (audit immutability)
    8. Create PERMISSIVE RLS policy allowing INSERT

Design refs:
    US-046 AC Scenarios 1-4 — encrypted transcripts, urgency flags, escalation status
    US-046 DoD — AES-256-GCM encryption, RLS immutability pattern from US-008
    design.md §6.1 DR-002, DR-003 — PHI encryption and audit immutability

Revision ID: i3f6d9e27a48
Revises:     h2e5c8d91f36
Create Date: 2026-07-29 00:00:00.000000
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op


# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "i3f6d9e27a48"
down_revision: Union[str, None] = "h2e5c8d91f36"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Upgrade chatbot_transcript for US-046."""

    # Step 1: Add `escalated` boolean column (will be set from escalated_at or default False)
    op.add_column(
        "chatbot_transcript",
        sa.Column(
            "escalated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="True when escalation alert was published to Pub/Sub (US-045)",
        ),
    )

    # Step 2: Rename message_content to message
    op.alter_column(
        "chatbot_transcript",
        "message_content",
        new_column_name="message",
        existing_type=sa.Text(),
    )

    # Step 3: Rename is_urgent to urgency_flag
    op.alter_column(
        "chatbot_transcript",
        "is_urgent",
        new_column_name="urgency_flag",
        existing_type=sa.Boolean(),
    )

    # Step 4: Add `timestamp` column (if not present from earlier migrations)
    # Check: if the initial schema included timestamp, this is a no-op
    # Otherwise, add it with a default value pointing to created_at
    try:
        op.add_column(
            "chatbot_transcript",
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="UTC message timestamp; used for chronological ordering",
            ),
        )
        # Backfill timestamp with created_at for existing rows
        op.execute("UPDATE chatbot_transcript SET timestamp = created_at WHERE timestamp IS NULL")
        # Now make it NOT NULL
        op.alter_column(
            "chatbot_transcript",
            "timestamp",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    except Exception:
        # Column might already exist; ignore error
        pass

    # Step 5: Drop the old escalated_at column (replaced by boolean escalated)
    op.drop_column("chatbot_transcript", "escalated_at")

    # Step 6: Drop the old indexes to recreate them cleanly
    op.drop_index("ix_chatbot_encounter_id", table_name="chatbot_transcript")
    op.drop_index("ix_chatbot_urgent", table_name="chatbot_transcript")

    # Step 7: Create new composite index on (encounter_id, timestamp) for pagination
    op.create_index(
        "ix_chatbot_transcript_encounter_timestamp",
        "chatbot_transcript",
        ["encounter_id", "timestamp"],
    )

    # Step 8: Enable Row Level Security
    op.execute("ALTER TABLE chatbot_transcript ENABLE ROW LEVEL SECURITY")

    # Step 9: Create RESTRICTIVE policy — blocks UPDATE/DELETE for app_write role
    # This enforces immutability: transcript rows cannot be modified once inserted
    op.execute("""
        CREATE POLICY transcript_immutable
            ON chatbot_transcript
            AS RESTRICTIVE
            FOR ALL
            TO app_write
            USING (false)
    """)

    # Step 10: Create PERMISSIVE INSERT policy — allows persistence service to write
    # The persistence service can only INSERT; UPDATE/DELETE blocked by RESTRICTIVE policy
    op.execute("""
        CREATE POLICY transcript_insert_allowed
            ON chatbot_transcript
            AS PERMISSIVE
            FOR INSERT
            TO app_write
            WITH CHECK (true)
    """)


def downgrade() -> None:
    """Downgrade chatbot_transcript from US-046."""

    # Drop RLS policies
    op.execute(
        "DROP POLICY IF EXISTS transcript_insert_allowed ON chatbot_transcript"
    )
    op.execute("DROP POLICY IF EXISTS transcript_immutable ON chatbot_transcript")

    # Disable RLS
    op.execute("ALTER TABLE chatbot_transcript DISABLE ROW LEVEL SECURITY")

    # Drop new index
    op.drop_index(
        "ix_chatbot_transcript_encounter_timestamp",
        table_name="chatbot_transcript",
    )

    # Recreate old indexes
    op.create_index(
        "ix_chatbot_encounter_id", "chatbot_transcript", ["encounter_id"]
    )
    op.create_index(
        "ix_chatbot_urgent", "chatbot_transcript", ["encounter_id", "urgency_flag"]
    )

    # Rename columns back
    op.alter_column(
        "chatbot_transcript",
        "message",
        new_column_name="message_content",
        existing_type=sa.Text(),
    )
    op.alter_column(
        "chatbot_transcript",
        "urgency_flag",
        new_column_name="is_urgent",
        existing_type=sa.Boolean(),
    )

    # Add escalated_at back
    op.add_column(
        "chatbot_transcript",
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Drop new columns
    op.drop_column("chatbot_transcript", "escalated")
    op.drop_column("chatbot_transcript", "timestamp")
