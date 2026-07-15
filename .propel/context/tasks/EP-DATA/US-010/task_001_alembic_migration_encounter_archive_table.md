---
id: TASK-001
title: "Alembic Migration `0005_encounter_archive_table` — Create encounter_archive Table"
user_story: US-010
epic: EP-DATA
sprint: 1
layer: Backend / Database
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-006/TASK-007, US-009/TASK-005]
---

# TASK-001: Alembic Migration `0005_encounter_archive_table` — Create encounter_archive Table

> **Story:** US-010 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend / Database | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-010 DoD requires: *"encounter_archive table created with identical schema to encounter plus archived_at timestamp"*.

Before the pg_cron archival job (TASK-002) can move rows, the destination table must exist. This migration creates `encounter_archive` as a structural copy of the `encounter` table, extended with an `archived_at` timestamptz column to record when the row was moved.

Key design decisions:
- **No foreign keys** from `encounter_archive` back to `patient` or `bed` — archived data is self-contained, denormalised by intent. Referential integrity is irrelevant once data exceeds the retention boundary.
- **No RLS policy** on `encounter_archive` — the archive table is admin-write / compliance-read only; application roles (`app_write`) receive no INSERT/UPDATE/DELETE grants.
- **Soft-delete omitted** — `encounter_archive` is the final destination; rows are never "deleted" from it within the 7-year window.
- **CMEK encryption**: the `encounter_archive` table is created in the same Cloud SQL instance with CMEK already applied at the block level. The `EncryptedString` TypeDecorators on `patient_*` shadow columns carry their encrypted values as-is from `encounter`. No re-encryption step is needed during archival.

The migration follows the chain: `<rev4>` (US-009/TASK-005 pgcron_refresh_jobs) → this migration (`<rev5>`) → TASK-002 (`<rev6>`).

---

## Acceptance Criteria Addressed

| US-010 AC | Requirement |
|---|---|
| **DoD** | `encounter_archive` table created with identical schema to `encounter` plus `archived_at` timestamp |
| **Scenario 1** (pre-condition) | Destination table exists before archival job runs |

---

## Implementation Steps

### 1. Generate a Revision ID

```bash
cd backend
python -c "import uuid; print(uuid.uuid4().hex[:12])"
# e.g., f3a1c9e20b57
```

Name the file `backend/alembic/versions/f3a1c9e20b57_encounter_archive_table.py`.

### 2. Inspect the Current `encounter` Table Definition

Before authoring the migration, review the ORM model to confirm all columns:

```bash
# From backend/
grep -A 80 "class Encounter" app/models/encounter.py
```

The `encounter` table (from US-006/TASK-004 and US-006/TASK-007) has the following columns — **replicate all of them** in `encounter_archive`:

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | Primary key — preserved as-is (was the encounter's primary key) |
| `patient_id` | `UUID` | Original FK — stored as plain UUID (FK dropped in archive table) |
| `admit_date` | `TIMESTAMPTZ` | |
| `discharge_date` | `TIMESTAMPTZ` | Nullable |
| `status` | `VARCHAR(32)` | Final status at time of archival |
| `unit` | `VARCHAR(64)` | |
| `bed_id` | `UUID` | Original FK — stored as plain UUID (FK dropped in archive table) |
| `risk_tier` | `VARCHAR(16)` | |
| `risk_score` | `NUMERIC(5,2)` | Nullable |
| `source_message_id` | `VARCHAR(128)` | Unique in `encounter`; retains value in archive |
| `created_at` | `TIMESTAMPTZ` | |
| `updated_at` | `TIMESTAMPTZ` | |
| `deleted_at` | `TIMESTAMPTZ` | Nullable (soft-delete column — preserved as audit evidence) |
| **`archived_at`** | `TIMESTAMPTZ` | **New column** — set by archival function to `NOW()` |

### 3. Author the Migration File

```python
"""Create encounter_archive table for 7-year retention archival.

Revision ID: <rev5>
Revises: <rev4>
Create Date: 2026-07-15

Hand-authored per US-010 DoD requirement.
Creates encounter_archive as a denormalised copy of the encounter table,
extended with an archived_at column. No foreign keys — archived rows are
self-contained once beyond the 7-year active retention boundary.

References:
  DR-006: Archive encounters where discharge_date < NOW() - INTERVAL '7 years'
  US-010 DoD: encounter_archive table created with identical schema + archived_at
  BR-022: 7-year data retention requirement
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "<rev5>"
down_revision: Union[str, None] = "<rev4>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Create encounter_archive table ────────────────────────────────────────
    # Schema mirrors encounter exactly. Foreign keys are intentionally omitted:
    # archived rows are denormalised self-contained records. The archived_at
    # column records when the row was moved from encounter to this table.
    op.create_table(
        "encounter_archive",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admit_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discharge_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("bed_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("risk_tier", sa.String(16), nullable=True),
        sa.Column("risk_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("source_message_id", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
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
    # app_write must not be able to INSERT/UPDATE/DELETE archive records.
    # compliance_reader receives SELECT for audit purposes.
    op.execute("REVOKE ALL ON encounter_archive FROM app_write;")
    op.execute("GRANT SELECT ON encounter_archive TO compliance_reader;")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON encounter_archive FROM compliance_reader;")
    op.drop_index("ix_encounter_archive_discharge_date", table_name="encounter_archive")
    op.drop_index("ix_encounter_archive_archived_at", table_name="encounter_archive")
    op.drop_index("ix_encounter_archive_patient_id", table_name="encounter_archive")
    op.drop_table("encounter_archive")
```

### 4. Register the New Revision in Alembic's Chain

Confirm the `down_revision` value in this file matches the revision ID from US-009/TASK-005 (`pgcron_refresh_jobs`). You can verify with:

```bash
cd backend
alembic history --verbose | head -20
# The topmost migration should be the US-009 pgcron_refresh_jobs revision.
```

### 5. Verify Migration Up / Down

```bash
# Apply
cd backend
alembic upgrade head

# Verify table exists
psql $DATABASE_URL -c "\d encounter_archive"

# Verify grants: app_write should have no privileges
psql $DATABASE_URL -c "\dp encounter_archive"

# Rollback
alembic downgrade -1

# Verify table dropped
psql $DATABASE_URL -c "\d encounter_archive"
# Expected: "Did not find any relation named encounter_archive."
```

---

## File Checklist

| File | Action |
|---|---|
| `backend/alembic/versions/<rev5>_encounter_archive_table.py` | Create |

---

## Definition of Done Mapping

| DoD Item | Met By |
|---|---|
| `encounter_archive` table created with identical schema to `encounter` plus `archived_at` timestamp | This migration: `op.create_table("encounter_archive", ...)` with `archived_at` column |
| Migration reversible (`alembic downgrade -1`) | `downgrade()` drops table and indexes |
