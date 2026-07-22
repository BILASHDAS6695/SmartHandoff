---
id: TASK-003
title: "Alembic Migration `0007_pgcron_audit_log_purge` — Weekly Audit Log Export-and-Purge pg_cron Job"
user_story: US-010
epic: EP-DATA
sprint: 1
layer: Backend / Database
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-002, US-008/TASK-003]
---

# TASK-003: Alembic Migration `0007_pgcron_audit_log_purge` — Weekly Audit Log Export-and-Purge pg_cron Job

> **Story:** US-010 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend / Database | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-010 DoD: *"pg_cron job for audit log purge: weekly, exports to Cloud Storage then deletes rows older than 6 years"* and *"Cloud Storage export uses WORM (retention policy locked) bucket for audit log archives"*.

US-010 Acceptance Criteria Scenario 2:

> **Given** the pg_cron job `purge-old-audit-logs` is registered  
> **When** the weekly cron fires  
> **Then** all `audit_log` rows with `created_at < NOW() - INTERVAL '6 years'` are exported to Cloud Storage WORM bucket and then deleted; rows within the retention window are untouched.

### Relationship to US-008/TASK-003

US-008/TASK-003 created:
- An `audit_log_archive_queue` staging table.
- A `archive_expired_audit_logs()` function that inserts expired rows into the queue and emits `pg_notify('audit_archive_trigger', ...)`.
- A pg_cron job `archive-expired-audit-logs` (nightly at 02:00 UTC).

That mechanism is the **export trigger**. The actual GCS write is performed by an `audit-archiver` Cloud Run job (EP-TECH scope, Phase 1 deferred).

US-010/TASK-003 provides the **purge** step: a second pg_cron job `purge-old-audit-logs` that:
1. Checks `audit_log_archive_queue` for rows that have been successfully exported (`exported_at IS NOT NULL`).
2. Deletes those confirmed-archived rows from `audit_log`.

This two-step design ensures audit logs are **never deleted before GCS export is confirmed**. The audit-archiver sets `exported_at` and `gcs_object_path` on each queue row upon successful export.

### WORM Bucket Reminder

The Cloud Storage WORM bucket (`audit-log-archive-{env}`) is provisioned in Terraform with an Object Retention Lock policy. Ensuring the bucket exists with a 6-year retention lock is a Terraform concern (tracked in `infra/terraform/modules/storage/`), not this migration's responsibility. This migration only manages the PostgreSQL side.

### Migration Chain

`<rev6>` (US-010/TASK-002 pgcron_encounter_archival) → this migration (`<rev7>`)

---

## Acceptance Criteria Addressed

| US-010 AC | Requirement |
|---|---|
| **Scenario 2** | `purge-old-audit-logs` job registered; weekly; rows with `created_at < NOW() - INTERVAL '6 years'` exported to Cloud Storage WORM then deleted; rows within window untouched |
| **Scenario 3** | `SELECT * FROM cron.job` shows `purge-old-audit-logs` alongside the other registered jobs |
| **DoD** | pg_cron job for audit log purge: weekly, exports to Cloud Storage then deletes rows older than 6 years |
| **DoD** | Cloud Storage export uses WORM (retention policy locked) bucket for audit log archives |

---

## Implementation Steps

### 1. Verify the audit_log_archive_queue Exists

This task depends on US-008/TASK-003 having been applied. Confirm:

```bash
psql $DATABASE_URL -c "\d audit_log_archive_queue"
# Should show: id, audit_log_id, queued_at, exported_at, gcs_object_path, payload
```

If the table does not exist, apply US-008 migrations first:

```bash
cd backend
alembic upgrade head  # should include US-008 chain
```

### 2. Generate a Revision ID

```bash
cd backend
python -c "import uuid; print(uuid.uuid4().hex[:12])"
# e.g., b2c5d9a71e84
```

Name the file `backend/alembic/versions/b2c5d9a71e84_pgcron_audit_log_purge.py`.

### 3. Implement the Migration File

```python
"""pg_cron weekly audit log purge — post-export deletion after 6-year retention.

Revision ID: <rev7>
Revises: <rev6>
Create Date: 2026-07-15

Hand-authored per US-010 DoD.
Installs purge_exported_audit_logs() PL/pgSQL function and registers
the 'purge-old-audit-logs' pg_cron job to fire weekly (Sunday 04:00 UTC).

The purge function deletes audit_log rows that meet BOTH conditions:
  1. created_at < NOW() - INTERVAL '6 years'  (beyond retention window)
  2. The corresponding audit_log_archive_queue row has exported_at IS NOT NULL
     (GCS export was confirmed by the audit-archiver Cloud Run job)

This ensures no audit log row is deleted before its GCS copy is confirmed.
The export enqueue step is handled by archive_expired_audit_logs() from
US-008/TASK-003 (nightly at 02:00 UTC via 'archive-expired-audit-logs' job).

References:
  DR-006: audit_logs retained 6 years minimum
  BR-023: HIPAA audit log retention requirement
  US-010 Scenario 2: weekly purge with Cloud Storage WORM export
  US-008/TASK-003: upstream export-queue mechanism
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "<rev7>"
down_revision: Union[str, None] = "<rev6>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETENTION_DAYS = 2190   # 6 years × 365 days
_BATCH_SIZE = 1000


def upgrade() -> None:
    # ── 1. pg_cron extension (idempotent) ─────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron;")

    # ── 2. Create PL/pgSQL purge function ─────────────────────────────────────
    op.execute(f"""
        CREATE OR REPLACE FUNCTION purge_exported_audit_logs()
        RETURNS INTEGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        DECLARE
            v_cutoff         TIMESTAMPTZ := now() - INTERVAL '{_RETENTION_DAYS} days';
            v_total_purged   INTEGER     := 0;
            v_batch_count    INTEGER     := 0;
            v_purge_ids      UUID[];
        BEGIN
            -- Loop in batches to keep transactions short.
            LOOP
                -- Collect IDs eligible for deletion:
                --   • Beyond 6-year retention boundary.
                --   • GCS export confirmed (exported_at IS NOT NULL in queue).
                SELECT array_agg(al.id)
                INTO   v_purge_ids
                FROM   audit_log al
                JOIN   audit_log_archive_queue q ON q.audit_log_id = al.id
                WHERE  al.created_at < v_cutoff
                  AND  q.exported_at IS NOT NULL
                ORDER BY al.created_at ASC
                LIMIT  {_BATCH_SIZE};

                EXIT WHEN v_purge_ids IS NULL OR array_length(v_purge_ids, 1) = 0;

                -- Delete confirmed-exported rows from audit_log.
                -- The RLS RESTRICTIVE policy on audit_log blocks app_write;
                -- SECURITY DEFINER runs as the function owner (superuser),
                -- which bypasses RLS — this is intentional for the purge operation.
                DELETE FROM audit_log
                WHERE id = ANY(v_purge_ids);

                -- Clean up the corresponding archive queue rows.
                DELETE FROM audit_log_archive_queue
                WHERE audit_log_id = ANY(v_purge_ids);

                v_batch_count  := array_length(v_purge_ids, 1);
                v_total_purged := v_total_purged + v_batch_count;

                RAISE NOTICE 'purge_exported_audit_logs: purged batch of % rows (total: %)',
                    v_batch_count, v_total_purged;
            END LOOP;

            RAISE NOTICE 'purge_exported_audit_logs completed: % total rows purged', v_total_purged;
            RETURN v_total_purged;

        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'purge_exported_audit_logs FAILED: %  SQLSTATE: %', SQLERRM, SQLSTATE;
            RAISE;
        END;
        $$;
    """)

    # ── 3. Register the weekly pg_cron job ────────────────────────────────────
    # Schedule: 0 4 * * 0 = Sunday at 04:00 UTC.
    # Runs after the nightly archive-expired-audit-logs job (02:00 UTC) and
    # after the audit-archiver Cloud Run job has confirmed GCS exports.
    op.execute("""
        SELECT cron.schedule(
            'purge-old-audit-logs',
            '0 4 * * 0',
            $$SELECT purge_exported_audit_logs()$$
        );
    """)


def downgrade() -> None:
    op.execute("SELECT cron.unschedule('purge-old-audit-logs');")
    op.execute("DROP FUNCTION IF EXISTS purge_exported_audit_logs();")
```

### 4. Verify the WORM Bucket Configuration (Terraform)

Confirm the Cloud Storage bucket for audit log archives has an Object Retention Lock. This is a Terraform concern but the backend engineer must verify before considering this task complete:

```bash
# Review the storage module
cat infra/terraform/modules/storage/main.tf | grep -A 10 "audit"
```

The bucket should have a retention policy configured. If not, add to `infra/terraform/modules/storage/main.tf`:

```hcl
resource "google_storage_bucket" "audit_log_archive" {
  name     = "audit-log-archive-${var.environment}"
  location = var.region

  retention_policy {
    retention_period = 189216000  # 6 years in seconds (6 * 365 * 24 * 3600)
    is_locked        = true       # WORM — cannot be shortened once locked
  }

  uniform_bucket_level_access = true

  labels = {
    environment = var.environment
    managed_by  = "terraform"
    phi_data    = "true"
  }
}
```

### 5. Verify Migration Up / Down

```bash
cd backend

# Apply
alembic upgrade head

# Verify function
psql $DATABASE_URL -c "\df purge_exported_audit_logs"

# Verify all 3 retention-related cron jobs are registered (Scenario 3)
psql $DATABASE_URL -c "
  SELECT jobname, schedule
  FROM cron.job
  WHERE jobname IN (
    'archive-old-encounters',
    'archive-expired-audit-logs',
    'purge-old-audit-logs'
  )
  ORDER BY jobname;
"
# Expected 3 rows

# Rollback
alembic downgrade -1
psql $DATABASE_URL -c "SELECT jobname FROM cron.job WHERE jobname = 'purge-old-audit-logs';"
# Expected: (0 rows)
```

---

## File Checklist

| File | Action |
|---|---|
| `backend/alembic/versions/<rev7>_pgcron_audit_log_purge.py` | Create |
| `infra/terraform/modules/storage/main.tf` | Verify WORM retention policy on audit archive bucket |

---

## Definition of Done Mapping

| DoD Item | Met By |
|---|---|
| pg_cron job for audit log purge: weekly, exports to Cloud Storage then deletes rows older than 6 years | `cron.schedule('purge-old-audit-logs', '0 4 * * 0', ...)` + `purge_exported_audit_logs()` function |
| Cloud Storage export uses WORM (retention policy locked) bucket | Terraform retention policy with `is_locked = true` |
| Rows within retention window untouched | `WHERE created_at < v_cutoff AND q.exported_at IS NOT NULL` |
| Migration reversible | `downgrade()` unschedules and drops function |
