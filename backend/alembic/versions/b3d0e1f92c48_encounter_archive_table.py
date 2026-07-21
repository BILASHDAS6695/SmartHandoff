"""Create encounter_archive table for 7-year retention archival.

Revision ID: b3d0e1f92c48
Revises: a6d9c2b48e51
Create Date: 2026-07-21

Hand-authored per US-010 DoD requirement.
Creates encounter_archive as a denormalised copy of the encounter table,
extended with an archived_at column. No foreign keys — archived rows are
self-contained once beyond the 7-year active retention boundary.

Column set mirrors the encounter table definition exactly (a3f9e2c10b4d
initial schema), so any new column added to encounter must also be added
here for the archival INSERT to remain complete.

References:
  DR-006: Archive encounters where discharge_date < NOW() - INTERVAL '7 years'
  US-010 DoD: encounter_archive table created with identical schema + archived_at
  BR-022: 7-year data retention requirement
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3d0e1f92c48"
down_revision: Union[str, None] = "a6d9c2b48e51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Create encounter_archive table ────────────────────────────────────────
    # Schema mirrors encounter exactly (from a3f9e2c10b4d initial_schema).
    # Foreign keys are intentionally omitted: archived rows are denormalised
    # self-contained records. The archived_at column records when the row was
    # moved from encounter to this table by archive_old_encounters().
    op.create_table(
        "encounter_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            comment="Final encounter status at time of archival",
        ),
        sa.Column("admit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discharge_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admitting_diagnosis", sa.Text(), nullable=True),
        sa.Column(
            "attending_physician_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Original FK value — stored as plain UUID (FK dropped in archive)",
        ),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column("risk_tier", sa.String(16), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("visit_number", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # Soft-delete column preserved as audit evidence even in archive
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        # ── Extension column ──────────────────────────────────────────────────
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp when this encounter was moved from the live table",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_encounter_archive"),
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    # patient_id — enables compliance queries: "all archived encounters for patient X"
    op.create_index(
        "ix_encounter_archive_patient_id",
        "encounter_archive",
        ["patient_id"],
    )
    # archived_at — supports range queries on archive date; used by monitoring
    op.create_index(
        "ix_encounter_archive_archived_at",
        "encounter_archive",
        ["archived_at"],
    )
    # discharge_date — used by archival function's WHERE clause internally
    op.create_index(
        "ix_encounter_archive_discharge_date",
        "encounter_archive",
        ["discharge_date"],
    )

    # ── Restrict grants: no app_write access ─────────────────────────────────
    # app_write must not INSERT/UPDATE/DELETE archive records.
    # compliance_reader receives SELECT for audit purposes only.
    op.execute("REVOKE ALL ON encounter_archive FROM app_write;")
    op.execute("GRANT SELECT ON encounter_archive TO compliance_reader;")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON encounter_archive FROM compliance_reader;")
    op.drop_index("ix_encounter_archive_discharge_date", table_name="encounter_archive")
    op.drop_index("ix_encounter_archive_archived_at", table_name="encounter_archive")
    op.drop_index("ix_encounter_archive_patient_id", table_name="encounter_archive")
    op.drop_table("encounter_archive")
