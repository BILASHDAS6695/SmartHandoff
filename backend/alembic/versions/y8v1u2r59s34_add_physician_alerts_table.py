"""Add physician_alerts table for physician review alerts.

Adds physician_alerts table for clinical review alerts surfaced to physicians,
starting with medication reconciliation review requests.

New ENUM types:
    - physician_alert_type_enum: MEDICATION_REVIEW
    - physician_alert_severity_enum: HIGH | MEDIUM | LOW
    - physician_alert_status_enum: ACTIVE | RESOLVED

physician_alerts table:
    - id: UUID PRIMARY KEY
    - encounter_id: UUID NOT NULL FK(encounter.id) ON DELETE CASCADE
    - patient_id: UUID NULL FK(patient.id) ON DELETE SET NULL
    - alert_type: physician_alert_type_enum NOT NULL DEFAULT 'MEDICATION_REVIEW'
    - severity: physician_alert_severity_enum NOT NULL
    - title: VARCHAR(255) NOT NULL
    - message: TEXT NULL
    - status: physician_alert_status_enum NOT NULL DEFAULT 'ACTIVE'
    - resolution_type: VARCHAR(64) NULL
    - resolution_note: TEXT NULL
    - resolved_by_user_id: UUID NULL
    - resolved_at: TIMESTAMPTZ NULL
    - created_at: TIMESTAMPTZ NOT NULL DEFAULT NOW()

Indexes:
    - ix_physician_alerts_encounter_id on encounter_id
    - ix_physician_alerts_patient_id on patient_id
    - ix_physician_alerts_status on status

Revision ID: y8v1u2r59s34
Revises:     x7u0t1q48p23
Create Date: 2026-08-17

Design refs:
    US-030 extension — Physician medication review alert
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "y8v1u2r59s34"
down_revision: Union[str, None] = "x7u0t1q48p23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create physician_alerts table with enums and indexes."""

    # 1. Create ENUM types
    alert_type_enum = postgresql.ENUM(
        "MEDICATION_REVIEW",
        name="physician_alert_type_enum",
        create_type=True,
    )
    alert_type_enum.create(op.get_bind(), checkfirst=True)

    severity_enum = postgresql.ENUM(
        "HIGH", "MEDIUM", "LOW",
        name="physician_alert_severity_enum",
        create_type=True,
    )
    severity_enum.create(op.get_bind(), checkfirst=True)

    status_enum = postgresql.ENUM(
        "ACTIVE", "RESOLVED",
        name="physician_alert_status_enum",
        create_type=True,
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    # 2. Create physician_alerts table
    op.create_table(
        "physician_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="Unique alert identifier",
        ),
        sa.Column(
            "encounter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
            comment="Reference to encounter",
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patient.id", ondelete="SET NULL"),
            nullable=True,
            comment="Reference to patient for display/filtering",
        ),
        sa.Column(
            "alert_type",
            postgresql.ENUM(
                "MEDICATION_REVIEW",
                name="physician_alert_type_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="MEDICATION_REVIEW",
            comment="Physician alert category",
        ),
        sa.Column(
            "severity",
            postgresql.ENUM(
                "HIGH", "MEDIUM", "LOW",
                name="physician_alert_severity_enum",
                create_type=False,
            ),
            nullable=False,
            comment="Alert severity level",
        ),
        sa.Column(
            "title",
            sa.String(255),
            nullable=False,
            comment="Short alert summary",
        ),
        sa.Column(
            "message",
            sa.Text(),
            nullable=True,
            comment="Detailed alert context",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "ACTIVE", "RESOLVED",
                name="physician_alert_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="ACTIVE",
            comment="Alert status",
        ),
        sa.Column(
            "resolution_type",
            sa.String(64),
            nullable=True,
            comment="How the alert was resolved",
        ),
        sa.Column(
            "resolution_note",
            sa.Text(),
            nullable=True,
            comment="Resolution free-text note",
        ),
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="User that resolved the alert",
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Resolution timestamp",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="UTC timestamp when alert was created",
        ),
    )

    # 3. Create indexes
    op.create_index(
        "ix_physician_alerts_encounter_id",
        "physician_alerts",
        ["encounter_id"],
        unique=False,
    )
    op.create_index(
        "ix_physician_alerts_patient_id",
        "physician_alerts",
        ["patient_id"],
        unique=False,
    )
    op.create_index(
        "ix_physician_alerts_status",
        "physician_alerts",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Drop physician_alerts table and associated enums."""

    # 1. Drop indexes
    op.drop_index("ix_physician_alerts_status", table_name="physician_alerts")
    op.drop_index("ix_physician_alerts_patient_id", table_name="physician_alerts")
    op.drop_index("ix_physician_alerts_encounter_id", table_name="physician_alerts")

    # 2. Drop table
    op.drop_table("physician_alerts")

    # 3. Drop ENUM types
    op.execute("DROP TYPE IF EXISTS physician_alert_status_enum")
    op.execute("DROP TYPE IF EXISTS physician_alert_severity_enum")
    op.execute("DROP TYPE IF EXISTS physician_alert_type_enum")
