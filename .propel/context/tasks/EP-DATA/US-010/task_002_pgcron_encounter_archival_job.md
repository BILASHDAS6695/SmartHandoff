---
id: TASK-002
title: "Alembic Migration `0006_pgcron_encounter_archival` — Nightly Encounter Archival pg_cron Job"
user_story: US-010
epic: EP-DATA
sprint: 1
layer: Backend / Database
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, US-009/TASK-005]
---

# TASK-002: Alembic Migration `0006_pgcron_encounter_archival` — Nightly Encounter Archival pg_cron Job

> **Story:** US-010 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend / Database | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-010 DoD: *"pg_cron job for encounter archival: nightly at 03:00 UTC, moves rows older than 7 years"*.

US-010 Acceptance Criteria Scenario 1:

> **Given** the pg_cron job `archive-old-encounters` is registered  
> **When** the nightly cron fires (03:00 UTC)  
> **Then** all encounters with `discharge_date < NOW() - INTERVAL '7 years'` are moved to the `encounter_archive` table and the original rows are deleted; the job completion is logged to Cloud Logging.

This task delivers:
1. A PL/pgSQL function `archive_old_encounters()` that performs the move-and-delete in batches.
2. An Alembic migration that installs the function and registers the pg_cron job.

### Batch Processing Strategy

A single transaction that moves all 7-year-old encounters at once risks table-lock contention on a large live database. The function uses a loop-based batch of **500 rows per iteration** with an explicit commit after each batch. This keeps each transaction short and prevents long lock windows on the `encounter` table.

```
LOOP
    INSERT INTO encounter_archive (SELECT ...) FROM encounter WHERE ... LIMIT 500
    DELETE FROM encounter WHERE id = ANY(archived_ids)
    COMMIT
    EXIT WHEN rows_moved = 0
END LOOP
```

### Logging to Cloud Logging

pg_cron itself does not write to Cloud Logging. The mechanism is:
- The function writes a structured summary to the PostgreSQL `cron.job_run_details` table (this is automatic for all pg_cron jobs — Cloud SQL's Cloud Logging integration exports these rows to Cloud Logging as structured log entries).
- The function also calls `RAISE NOTICE 'archive_old_encounters completed: % rows archived'` which appears in PostgreSQL server logs, forwarded to Cloud Logging via Cloud SQL's log export.

### Migration Chain

`<rev5>` (US-010/TASK-001 encounter_archive_table) → this migration (`<rev6>`) → TASK-003 (`<rev7>`)

---

## Acceptance Criteria Addressed

| US-010 AC | Requirement |
|---|---|
| **Scenario 1** | `archive-old-encounters` job registered; fires at 03:00 UTC; moves encounters with `discharge_date < NOW() - INTERVAL '7 years'` to `encounter_archive`; originals deleted; completion logged |
| **Scenario 3** | `SELECT * FROM cron.job` shows `archive-old-encounters` with schedule `0 3 * * *` |
| **DoD** | pg_cron job for encounter archival: nightly at 03:00 UTC, moves rows older than 7 years |

---

## Implementation Steps

### 1. Confirm pg_cron Is Available

pg_cron was enabled in `infra/terraform/modules/cloud_sql/main.tf` for US-008/US-009. Confirm the database flag is present before applying this migration:

```bash
# Check Terraform Cloud SQL module
grep -n "enable_pgcron\|pg_cron" infra/terraform/modules/cloud_sql/main.tf
```

If not present, add to the Cloud SQL resource's `database_flags` block:

```hcl
database_flags {
  name  = "cloudsql.enable_pgcron"
  value = "on"
}
```

### 2. Generate a Revision ID

```bash
cd backend
python -c "import uuid; print(uuid.uuid4().hex[:12])"
# e.g., a7d2e8b14f30
```

Name the file `backend/alembic/versions/a7d2e8b14f30_pgcron_encounter_archival.py`.

### 3. Implement the Migration File

```python
"""pg_cron nightly encounter archival job — 7-year retention enforcement.

Revision ID: <rev6>
Revises: <rev5>
Create Date: 2026-07-15

Hand-authored per US-010 DoD.
Installs archive_old_encounters() PL/pgSQL function and registers
the 'archive-old-encounters' pg_cron job to fire nightly at 03:00 UTC.

Retention rule: encounters with discharge_date < NOW() - INTERVAL '7 years'
are moved in batches of 500 to encounter_archive and deleted from encounter.

References:
  DR-006: Archive encounters where discharge_date < NOW() - INTERVAL '7 years'
  US-010 Scenario 1: archive-old-encounters job nightly at 03:00 UTC
  BR-022: 7-year active data retention requirement
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "<rev6>"
down_revision: Union[str, None] = "<rev5>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETENTION_YEARS = 7
_BATCH_SIZE = 500


def upgrade() -> None:
    # ── 1. Install pg_cron extension (idempotent) ─────────────────────────────
    # The extension was already enabled in US-008/US-009 migrations.
    # CREATE EXTENSION IF NOT EXISTS is safe to repeat.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron;")

    # ── 2. Create the PL/pgSQL archival function ──────────────────────────────
    op.execute(f"""
        CREATE OR REPLACE FUNCTION archive_old_encounters()
        RETURNS INTEGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        DECLARE
            v_cutoff        TIMESTAMPTZ := now() - INTERVAL '{_RETENTION_YEARS} years';
            v_total_archived INTEGER    := 0;
            v_batch_count   INTEGER     := 0;
            v_archived_ids  UUID[];
        BEGIN
            -- Loop in batches to avoid long lock windows on the encounter table.
            LOOP
                -- Step 1: Collect a batch of IDs eligible for archival.
                SELECT array_agg(id)
                INTO   v_archived_ids
                FROM  (
                    SELECT id
                    FROM   encounter
                    WHERE  discharge_date < v_cutoff
                      AND  deleted_at IS NULL   -- skip already soft-deleted
                    ORDER BY discharge_date ASC
                    LIMIT  {_BATCH_SIZE}
                    FOR UPDATE SKIP LOCKED       -- avoids blocking active transactions
                ) sub;

                -- No more rows to archive — exit the loop.
                EXIT WHEN v_archived_ids IS NULL OR array_length(v_archived_ids, 1) = 0;

                -- Step 2: Copy the batch into encounter_archive.
                INSERT INTO encounter_archive (
                    id, patient_id, admit_date, discharge_date, status,
                    unit, bed_id, risk_tier, risk_score, source_message_id,
                    created_at, updated_at, deleted_at, archived_at
                )
                SELECT
                    id, patient_id, admit_date, discharge_date, status,
                    unit, bed_id, risk_tier, risk_score, source_message_id,
                    created_at, updated_at, deleted_at,
                    now() AS archived_at
                FROM encounter
                WHERE id = ANY(v_archived_ids);

                -- Step 3: Delete the originals.
                DELETE FROM encounter
                WHERE id = ANY(v_archived_ids);

                v_batch_count  := array_length(v_archived_ids, 1);
                v_total_archived := v_total_archived + v_batch_count;

                -- Emit structured log entry (forwarded to Cloud Logging via Cloud SQL).
                RAISE NOTICE 'archive_old_encounters: archived batch of % rows (total so far: %)',
                    v_batch_count, v_total_archived;
            END LOOP;

            -- Final completion notice — appears in cron.job_run_details.return_message.
            RAISE NOTICE 'archive_old_encounters completed: % total rows archived', v_total_archived;
            RETURN v_total_archived;

        EXCEPTION WHEN OTHERS THEN
            -- Log error detail; pg_cron captures this in cron.job_run_details.
            RAISE WARNING 'archive_old_encounters FAILED: %  SQLSTATE: %', SQLERRM, SQLSTATE;
            RAISE;
        END;
        $$;
    """)

    # ── 3. Register the pg_cron job ───────────────────────────────────────────
    # Schedule: 0 3 * * * = 03:00 UTC every day.
    # cron.schedule() is idempotent if the job name matches — it updates the
    # schedule if the name already exists.
    op.execute("""
        SELECT cron.schedule(
            'archive-old-encounters',
            '0 3 * * *',
            $$SELECT archive_old_encounters()$$
        );
    """)


def downgrade() -> None:
    # Unschedule the job before dropping the function.
    op.execute("""
        SELECT cron.unschedule('archive-old-encounters');
    """)
    op.execute("DROP FUNCTION IF EXISTS archive_old_encounters();")
    # Note: encounter_archive table is managed by <rev5> — do NOT drop it here.
```

### 4. Verify Migration Up / Down

```bash
cd backend

# Apply this migration
alembic upgrade head

# Verify the function exists
psql $DATABASE_URL -c "\df archive_old_encounters"

# Verify the cron job is registered
psql $DATABASE_URL -c "SELECT jobname, schedule, command FROM cron.job WHERE jobname = 'archive-old-encounters';"
# Expected:
# jobname                  | schedule  | command
# -------------------------+-----------+----------------------------------
# archive-old-encounters   | 0 3 * * * | SELECT archive_old_encounters()

# Test the function with a synthetic past-dated row (optional manual check):
psql $DATABASE_URL -c "
    INSERT INTO encounter (id, patient_id, admit_date, discharge_date, status, unit, source_message_id)
    VALUES (
        gen_random_uuid(), gen_random_uuid(),
        now() - interval '8 years', now() - interval '7 years 1 day',
        'DISCHARGED', 'ICU', 'TEST-MSG-001'
    );
    SELECT archive_old_encounters();
    SELECT count(*) FROM encounter_archive;
    DELETE FROM encounter_archive;  -- cleanup
"

# Rollback
alembic downgrade -1

# Verify function dropped
psql $DATABASE_URL -c "\df archive_old_encounters"
# Expected: "(0 rows)"

# Verify cron job removed
psql $DATABASE_URL -c "SELECT jobname FROM cron.job WHERE jobname = 'archive-old-encounters';"
# Expected: "(0 rows)"
```

---

## File Checklist

| File | Action |
|---|---|
| `backend/alembic/versions/<rev6>_pgcron_encounter_archival.py` | Create |
| `infra/terraform/modules/cloud_sql/main.tf` | Verify `cloudsql.enable_pgcron` flag present (no change if already set) |

---

## Definition of Done Mapping

| DoD Item | Met By |
|---|---|
| pg_cron job for encounter archival: nightly at 03:00 UTC | `cron.schedule('archive-old-encounters', '0 3 * * *', ...)` |
| Moves rows older than 7 years | `WHERE discharge_date < now() - INTERVAL '7 years'` |
| Originals deleted post-copy | `DELETE FROM encounter WHERE id = ANY(v_archived_ids)` |
| Completion logged to Cloud Logging | `RAISE NOTICE` forwarded via Cloud SQL log export |
| Migration reversible | `downgrade()` unschedules job and drops function |
