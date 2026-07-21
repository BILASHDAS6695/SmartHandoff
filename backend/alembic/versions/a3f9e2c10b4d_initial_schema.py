"""Initial schema — all 10 domain tables.

Revision ID: a3f9e2c10b4d
Revises: None
Create Date: 2026-07-15

Hand-authored per US-006 Technical Notes (autogenerate disabled).
PHI columns declared as TEXT — ciphertext written by EncryptedString
TypeDecorator (US-007). Column comments document encryption intent.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f9e2c10b4d"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── app_user ──────────────────────────────────────────────────────────
    op.create_table(
        "app_user",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("idp_subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idp_subject", name="uq_app_user_idp_subject"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )
    op.create_index("ix_app_user_idp_subject", "app_user", ["idp_subject"], unique=True)
    op.create_index("ix_app_user_email", "app_user", ["email"], unique=True)
    op.create_index("ix_app_user_role_active", "app_user", ["role", "is_active"])

    # ── patient ───────────────────────────────────────────────────────────
    # PHI columns stored as TEXT (AES-256-GCM ciphertext via US-007 TypeDecorator)
    op.create_table(
        "patient",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "first_name",
            sa.Text(),
            nullable=False,
            comment="AES-256-GCM encrypted (US-007)",
        ),
        sa.Column(
            "last_name",
            sa.Text(),
            nullable=False,
            comment="AES-256-GCM encrypted (US-007)",
        ),
        sa.Column(
            "date_of_birth",
            sa.Text(),
            nullable=False,
            comment="ISO-8601 date, AES-256-GCM encrypted (US-007)",
        ),
        sa.Column(
            "phone",
            sa.Text(),
            nullable=True,
            comment="AES-256-GCM encrypted (US-007)",
        ),
        sa.Column(
            "email",
            sa.Text(),
            nullable=True,
            comment="AES-256-GCM encrypted (US-007)",
        ),
        sa.Column(
            "mrn_encrypted",
            sa.String(128),
            nullable=False,
            comment="Deterministically encrypted MRN for unique indexing (DR-020)",
        ),
        sa.Column(
            "language_code", sa.String(8), nullable=False, server_default="en"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Soft delete (DR-005)
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mrn_encrypted", name="uq_patient_mrn_encrypted"),
    )
    op.create_index(
        "ix_patient_mrn_encrypted", "patient", ["mrn_encrypted"], unique=True
    )
    op.create_index("ix_patient_deleted_at", "patient", ["deleted_at"])

    # ── encounter ─────────────────────────────────────────────────────────
    op.create_table(
        "encounter",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "patient_id",
            sa.UUID(),
            sa.ForeignKey("patient.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="REGISTERED",
            comment="Encounter lifecycle status; transitions enforced by ORM event listener",
        ),
        sa.Column("admit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discharge_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admitting_diagnosis", sa.Text(), nullable=True),
        sa.Column(
            "attending_physician_id",
            sa.UUID(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column(
            "risk_tier",
            sa.String(16),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("visit_number", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Soft delete (DR-005)
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # DR-004: Composite indexes for dashboard query performance
    op.create_index(
        "ix_encounter_patient_admit", "encounter", ["patient_id", "admit_date"]
    )
    op.create_index("ix_encounter_unit_status", "encounter", ["unit", "status"])
    op.create_index(
        "ix_encounter_risk_tier_status", "encounter", ["risk_tier", "status"]
    )
    op.create_index("ix_encounter_deleted_at", "encounter", ["deleted_at"])

    # ── bed ───────────────────────────────────────────────────────────────
    op.create_table(
        "bed",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("bed_number", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("ward", sa.String(64), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="available"
        ),
        sa.Column(
            "current_encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "predicted_discharge_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unit", "bed_number", name="uq_bed_unit_number"),
    )
    op.create_index("ix_bed_unit_status", "bed", ["unit", "status"])

    # ── adt_event ─────────────────────────────────────────────────────────
    op.create_table(
        "adt_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_message_id",
            sa.String(128),
            nullable=False,
            comment="HL7 MSH-10 message control ID — unique constraint (DR-022)",
        ),
        sa.Column("event_type", sa.String(8), nullable=False),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sending_facility", sa.String(64), nullable=True),
        sa.Column("raw_message_path", sa.Text(), nullable=True),
        sa.Column(
            "processing_status",
            sa.String(32),
            nullable=False,
            server_default="received",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        # DR-022: Unique constraint on HL7 message ID for idempotency
        sa.UniqueConstraint("source_message_id", name="uq_adt_event_source_message_id"),
    )
    op.create_index(
        "ix_adt_event_source_message_id",
        "adt_event",
        ["source_message_id"],
        unique=True,
    )
    op.create_index("ix_adt_event_encounter_id", "adt_event", ["encounter_id"])
    op.create_index(
        "ix_adt_event_type_timestamp", "adt_event", ["event_type", "event_timestamp"]
    )

    # ── medication ────────────────────────────────────────────────────────
    op.create_table(
        "medication",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("drug_name", sa.String(255), nullable=False),
        sa.Column("rxcui", sa.String(32), nullable=True),
        sa.Column("dose", sa.String(64), nullable=True),
        sa.Column("route", sa.String(64), nullable=True),
        sa.Column("frequency", sa.String(64), nullable=True),
        sa.Column(
            "source", sa.String(32), nullable=False, server_default="admission"
        ),
        sa.Column("interaction_severity", sa.String(16), nullable=True),
        sa.Column(
            "reconciliation_status",
            sa.String(32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_medication_encounter_id", "medication", ["encounter_id"])
    op.create_index("ix_medication_rxcui", "medication", ["rxcui"])
    op.create_index(
        "ix_medication_severity", "medication", ["interaction_severity"]
    )

    # ── agent_task ────────────────────────────────────────────────────────
    op.create_table(
        "agent_task",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_type", sa.String(64), nullable=False),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="queued"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pubsub_message_id", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "retry_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "encounter_id",
            "agent_type",
            "pubsub_message_id",
            name="uq_agent_task_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_task_encounter_agent",
        "agent_task",
        ["encounter_id", "agent_type"],
    )
    op.create_index("ix_agent_task_status", "agent_task", ["status"])

    # ── document ──────────────────────────────────────────────────────────
    op.create_table(
        "document",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            comment="AES-256-GCM encrypted document body (US-007, DR-013)",
        ),
        sa.Column(
            "language_code", sa.String(8), nullable=False, server_default="en"
        ),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="draft"
        ),
        sa.Column(
            "generation_type",
            sa.String(16),
            nullable=False,
            server_default="LLM",
        ),
        sa.Column(
            "approved_by_id",
            sa.UUID(),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_encounter_type",
        "document",
        ["encounter_id", "document_type"],
    )
    op.create_index("ix_document_status", "document", ["status"])

    # ── audit_log ─────────────────────────────────────────────────────────
    # Append-only table. Row Security Policy added in migration 0002.
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_role", sa.String(32), nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column(
            "outcome", sa.String(16), nullable=False, server_default="success"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index(
        "ix_audit_log_resource",
        "audit_log",
        ["resource_type", "resource_id"],
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    # ── chatbot_transcript ────────────────────────────────────────────────
    op.create_table(
        "chatbot_transcript",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "encounter_id",
            sa.UUID(),
            sa.ForeignKey("encounter.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "message_content",
            sa.Text(),
            nullable=False,
            comment="AES-256-GCM encrypted chatbot message (DR-016)",
        ),
        sa.Column(
            "is_urgent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chatbot_encounter_id", "chatbot_transcript", ["encounter_id"]
    )
    op.create_index(
        "ix_chatbot_urgent",
        "chatbot_transcript",
        ["encounter_id", "is_urgent"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order to avoid FK violations
    op.drop_table("chatbot_transcript")
    op.drop_table("audit_log")
    op.drop_table("document")
    op.drop_table("agent_task")
    op.drop_table("medication")
    op.drop_table("adt_event")
    op.drop_table("bed")
    op.drop_table("encounter")
    op.drop_table("patient")
    op.drop_table("app_user")
