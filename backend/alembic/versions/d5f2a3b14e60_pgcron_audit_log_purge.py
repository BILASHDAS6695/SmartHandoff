"""Register pg_cron job for audit log purge (6-year retention).

Revision ID: d5f2a3b14e60
Revises: c4e1f2a03d59
Create Date: 2026-07-21

Hand-authored per US-010 DoD requirement.
Creates the purge_exported_audit_logs() PL/pgSQL function and schedules
it via pg_cron to run weekly on Sunday at 04:00 UTC.

The function deletes audit_log rows (and corresponding queue rows) that
are both:
  1. Older than 6 years (created_at < NOW() - INTERVAL '2190 days'), AND
  2. Confirmed exported to GCS (audit_log_archive_queue.exported_at IS NOT NULL)

Rows not yet exported to GCS are NEVER purged, regardless of age.
This guarantees no audit log row is destroyed before its Cloud Storage
copy exists on the WORM bucket.

SECURITY DEFINER allows the function to bypass RLS on audit_log.
The pg_cron worker runs as a low-privilege role; SECURITY DEFINER
elevates to the migration-owner role only for the duration of the call.

Requires: pg_cron extension (cloudsql.enable_pgcron = on).

References:
  US-010 DoD: audit log purge weekly, exports to Cloud Storage first
  BR-023: 6-year audit log retention minimum
  HIPAA 45 CFR §164.312(b): audit control record-keeping
  WORM bucket: smarthandoff-audit-export-<project_id>-<env>
    (google_storage_bucket.audit_export in modules/storage/main.tf)
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "d5f2a3b14e60"
down_revision: Union[str, None] = "c4e1f2a03d59"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETENTION_DAYS: int = 2190   # 6 years × 365 days
_BATCH_SIZE: int = 1000

_PURGE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION purge_exported_audit_logs()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_cutoff        TIMESTAMPTZ := NOW() - INTERVAL '{_RETENTION_DAYS} days';
    v_purge_ids     UUID[];
    v_batch_count   INTEGER;
    v_total_purged  INTEGER := 0;
BEGIN
    LOOP
        -- Collect the next batch of audit_log IDs that are:
        --   (a) older than 6 years, AND
        --   (b) confirmed exported to GCS (exported_at IS NOT NULL).
        -- Rows with exported_at IS NULL are NEVER touched here — they must
        -- be exported by the GCS exporter service before they qualify.
        SELECT array_agg(al.id)
          INTO v_purge_ids
          FROM (
              SELECT al.id
                FROM audit_log al
                JOIN audit_log_archive_queue q ON q.audit_log_id = al.id
               WHERE al.created_at < v_cutoff
                 AND q.exported_at IS NOT NULL
               ORDER BY al.created_at ASC
               LIMIT {_BATCH_SIZE}
          ) al;

        EXIT WHEN v_purge_ids IS NULL OR array_length(v_purge_ids, 1) = 0;

        v_batch_count := array_length(v_purge_ids, 1);

        -- Delete audit_log rows first (queue rows are not referenced by anything
        -- else, so order here is safe either way, but deleting the primary record
        -- before its own FK-referencing queue row avoids any stale queue entry).
        DELETE FROM audit_log
         WHERE id = ANY(v_purge_ids);

        -- Clean up the corresponding queue rows.
        DELETE FROM audit_log_archive_queue
         WHERE audit_log_id = ANY(v_purge_ids);

        v_total_purged := v_total_purged + v_batch_count;

        RAISE NOTICE 'purge_exported_audit_logs: purged batch of % rows (total so far: %)',
            v_batch_count, v_total_purged;
    END LOOP;

    RAISE NOTICE 'purge_exported_audit_logs completed: % total rows purged', v_total_purged;
    RETURN v_total_purged;

EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'purge_exported_audit_logs FAILED: %  SQLSTATE: %', SQLERRM, SQLSTATE;
    RAISE;
END;
$$;
"""

_SCHEDULE_SQL = """
SELECT cron.schedule(
    'purge-old-audit-logs',
    '0 4 * * 0',
    $$SELECT purge_exported_audit_logs()$$
);
"""


def upgrade() -> None:
    # pg_cron extension is already installed by a prior migration
    # (d4b7e2f91c30_pgcron_retention). This is idempotent.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron;")

    # ── Create the PL/pgSQL purge function ────────────────────────────────────
    op.execute(_PURGE_FUNCTION_SQL)

    # ── Schedule: Sunday 04:00 UTC (after nightly archival jobs finish) ───────
    op.execute(_SCHEDULE_SQL)


def downgrade() -> None:
    # Unschedule the job before dropping the function it calls.
    op.execute("SELECT cron.unschedule('purge-old-audit-logs');")
    op.execute("DROP FUNCTION IF EXISTS purge_exported_audit_logs();")
    # NOTE: Do NOT drop pg_cron extension — shared with US-008 and US-009 jobs.
