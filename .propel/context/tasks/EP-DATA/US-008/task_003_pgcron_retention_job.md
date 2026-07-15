---
id: TASK-003
title: "Author Alembic Migration `0003_pgcron_retention` — 6-Year Audit Log Archival to Cloud Storage"
user_story: US-008
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001]
---

# TASK-003: Author Alembic Migration `0003_pgcron_retention` — 6-Year Audit Log Archival to Cloud Storage

> **Story:** US-008 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-008 DoD item: *"pg_cron job scheduled to enforce 6-year retention by archiving rows older than 2,190 days to Cold Storage and deleting post-archive"*.

HIPAA requires audit logs to be retained for **6 years** (45 CFR §164.530(j)). DR-006 specifies: *"archive encounters where discharge_date < NOW() - INTERVAL '7 years' to Cloud Storage; audit_logs retained 6 years minimum"*. For `audit_log` the boundary is `created_at < NOW() - INTERVAL '2190 days'` (6 × 365).

The retention mechanism is a two-phase pg_cron job:

1. **Archive phase** — `pg_cron` calls a PostgreSQL function that exports eligible rows to Cloud Storage (via `pg_notify` + a sidecar Cloud Run job, described below).
2. **Delete phase** — After confirming the archive write, delete the archived rows from `audit_log`.

### Architecture — Export via `pg_notify` + Cloud Run Sidecar

Cloud SQL PostgreSQL does not support direct `COPY TO 'gs://...'` syntax (no `file_fdw` to GCS). The standard pattern is:

- pg_cron calls `archive_expired_audit_logs()` PL/pgSQL function
- Function writes eligible rows to a staging table `audit_log_archive_queue` and emits `pg_notify('audit_archive_trigger', payload)`
- A lightweight Cloud Run job (`audit-archiver`) subscribes via `LISTEN audit_archive_trigger` and exports rows from the queue to Cloud Storage (WORM bucket), then calls back to acknowledge
- pg_cron also schedules a second job to clean up acknowledged rows from the queue

For Sprint 1, this task delivers:
- The `0003_pgcron_retention` Alembic migration (pg_cron schedule, archive queue table, trigger function)
- The PL/pgSQL `archive_expired_audit_logs()` function

The Cloud Run `audit-archiver` sidecar is out of scope for this task (tracked under EP-TECH).

---

## Acceptance Criteria Addressed

| US-008 AC | Requirement |
|---|---|
| **DoD** | pg_cron job scheduled to enforce 6-year retention by archiving rows older than 2,190 days and deleting post-archive |

---

## Implementation Steps

### 1. Generate a Revision ID for the New Migration

```bash
cd backend
python -c "import uuid; print(uuid.uuid4().hex[:12])"
# e.g., d4b7e2f91c30
```

Name the file `backend/alembic/versions/d4b7e2f91c30_pgcron_retention.py`.

### 2. Verify pg_cron is Available on Cloud SQL

Cloud SQL for PostgreSQL supports `pg_cron` as a first-class extension. Confirm it is enabled in the Terraform Cloud SQL module:

```hcl
# In infra/terraform/modules/cloud_sql/main.tf — database_flags block
# Add if not present:
{
  name  = "cloudsql.enable_pg_cron"
  value = "on"
}
```

### 3. Author the Migration File

```python
"""pg_cron 6-year audit log retention schedule and archive queue.

Revision ID: <rev3>
Revises: <rev2>
Create Date: 2026-07-15

Hand-authored per US-008 DoD retention requirement.
Installs pg_cron extension, creates audit_log_archive_queue staging table,
defines archive_expired_audit_logs() PL/pgSQL function, and schedules
a nightly cron job at 02:00 UTC.

Retention policy: audit_log rows older than 2,190 days (6 years) are
moved to the archive queue and notified for export to Cloud Storage.
Rows are deleted from audit_log only after successful export acknowledgement.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "<rev3>"
down_revision: Union[str, None] = "<rev2>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETENTION_DAYS = 2190  # 6 years × 365 days


def upgrade() -> None:
    # ── 1. Install pg_cron extension ──────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron;")

    # ── 2. Create archive queue staging table ─────────────────────────────
    # Rows are written here by the cron function, exported by audit-archiver
    # Cloud Run, then deleted once the archiver sets exported_at.
    op.create_table(
        "audit_log_archive_queue",
        sa.Column("id", sa.UUID(), nullable=False, primary_key=True),
        sa.Column("audit_log_id", sa.UUID(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gcs_object_path", sa.String(512), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_archive_queue_exported_at",
        "audit_log_archive_queue",
        ["exported_at"],
    )

    # ── 3. Create PL/pgSQL archive function ───────────────────────────────
    op.execute(f"""
        CREATE OR REPLACE FUNCTION archive_expired_audit_logs()
        RETURNS INTEGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        DECLARE
            v_count INTEGER := 0;
            v_cutoff TIMESTAMPTZ := now() - INTERVAL '{_RETENTION_DAYS} days';
            v_row audit_log%ROWTYPE;
        BEGIN
            -- Insert expired rows into the archive queue
            INSERT INTO audit_log_archive_queue (id, audit_log_id, payload)
            SELECT
                gen_random_uuid(),
                al.id,
                jsonb_build_object(
                    'id',          al.id,
                    'user_id',     al.user_id,
                    'action',      al.action,
                    'entity_type', al.entity_type,
                    'entity_id',   al.entity_id,
                    'ip_address',  al.ip_address,
                    'endpoint',    al.endpoint,
                    'created_at',  al.created_at
                )
            FROM audit_log al
            WHERE al.created_at < v_cutoff
              AND al.id NOT IN (
                  SELECT audit_log_id FROM audit_log_archive_queue
              )
            RETURNING 1 INTO v_row;

            GET DIAGNOSTICS v_count = ROW_COUNT;

            -- Notify the audit-archiver Cloud Run listener
            IF v_count > 0 THEN
                PERFORM pg_notify(
                    'audit_archive_trigger',
                    json_build_object('queued_count', v_count, 'cutoff', v_cutoff)::text
                );
            END IF;

            RETURN v_count;
        END;
        $$;
    """)

    # ── 4. Create PL/pgSQL cleanup function (called by archiver post-export)
    op.execute("""
        CREATE OR REPLACE FUNCTION delete_archived_audit_logs()
        RETURNS INTEGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        DECLARE
            v_count INTEGER := 0;
        BEGIN
            -- Delete audit_log rows that have been confirmed exported
            DELETE FROM audit_log
            WHERE id IN (
                SELECT audit_log_id
                FROM audit_log_archive_queue
                WHERE exported_at IS NOT NULL
            );

            GET DIAGNOSTICS v_count = ROW_COUNT;

            -- Remove from queue after successful delete
            DELETE FROM audit_log_archive_queue WHERE exported_at IS NOT NULL;

            RETURN v_count;
        END;
        $$;
    """)

    # ── 5. Schedule nightly pg_cron jobs ──────────────────────────────────
    # Phase 1: archive expired rows at 02:00 UTC daily
    op.execute("""
        SELECT cron.schedule(
            'archive-expired-audit-logs',
            '0 2 * * *',
            $$SELECT archive_expired_audit_logs()$$
        );
    """)
    # Phase 2: delete confirmed-exported rows at 03:00 UTC daily
    # (1 hour after archive phase to allow audit-archiver time to export)
    op.execute("""
        SELECT cron.schedule(
            'delete-archived-audit-logs',
            '0 3 * * *',
            $$SELECT delete_archived_audit_logs()$$
        );
    """)


def downgrade() -> None:
    # ── Unschedule cron jobs ──────────────────────────────────────────────
    op.execute("SELECT cron.unschedule('delete-archived-audit-logs');")
    op.execute("SELECT cron.unschedule('archive-expired-audit-logs');")

    # ── Drop functions ────────────────────────────────────────────────────
    op.execute("DROP FUNCTION IF EXISTS delete_archived_audit_logs();")
    op.execute("DROP FUNCTION IF EXISTS archive_expired_audit_logs();")

    # ── Drop archive queue table ──────────────────────────────────────────
    op.drop_index("ix_archive_queue_exported_at", table_name="audit_log_archive_queue")
    op.drop_table("audit_log_archive_queue")

    # ── Drop pg_cron extension ────────────────────────────────────────────
    # Note: only drop if no other cron jobs are scheduled.
    op.execute("DROP EXTENSION IF EXISTS pg_cron;")
```

### 4. Enable pg_cron in Terraform Cloud SQL Module

Open `infra/terraform/modules/cloud_sql/main.tf` and add the `cloudsql.enable_pg_cron` database flag:

```hcl
resource "google_sql_database_instance" "primary" {
  # ... existing config ...

  settings {
    # ... existing settings ...

    database_flags {
      name  = "cloudsql.enable_pg_cron"
      value = "on"
    }
  }
}
```

### 5. Grant cron.job Permissions to Migration Role

The pg_cron extension requires the migration role to have permission to call `cron.schedule`:

```sql
-- Run once post-extension install (included in the migration via op.execute):
GRANT USAGE ON SCHEMA cron TO <migration_role>;
GRANT SELECT, INSERT, UPDATE, DELETE ON cron.job TO <migration_role>;
```

Add these grants to the `upgrade()` function after `CREATE EXTENSION IF NOT EXISTS pg_cron;`:

```python
op.execute("""
    GRANT USAGE ON SCHEMA cron TO CURRENT_USER;
    GRANT SELECT, INSERT, UPDATE, DELETE ON cron.job TO CURRENT_USER;
""")
```

---

## Files Affected

| File | Action |
|---|---|
| `backend/alembic/versions/<rev3>_pgcron_retention.py` | Create |
| `infra/terraform/modules/cloud_sql/main.tf` | Add `cloudsql.enable_pg_cron` database flag |

---

## Definition of Done

- [ ] `pg_cron` extension created by migration
- [ ] `audit_log_archive_queue` table created with correct columns and index
- [ ] `archive_expired_audit_logs()` function enqueues rows older than 2,190 days and emits `pg_notify`
- [ ] `delete_archived_audit_logs()` function removes confirmed-exported rows from `audit_log` and queue
- [ ] pg_cron jobs scheduled: archive at `0 2 * * *`, cleanup at `0 3 * * *`
- [ ] `cloudsql.enable_pg_cron = on` database flag added to Terraform Cloud SQL module
- [ ] `alembic downgrade -1` reverses all changes cleanly (unschedules jobs, drops functions, drops extension)
