"""Register pg_cron job for encounter archival (7-year retention).

Revision ID: c4e1f2a03d59
Revises: b3d0e1f92c48
Create Date: 2026-07-21

Hand-authored per US-010 DoD requirement.
Creates the archive_old_encounters() PL/pgSQL function and schedules
it via pg_cron to run nightly at 03:00 UTC.

The function moves all encounters with discharge_date < NOW() - 7 years
into encounter_archive in batches of 500, then deletes originals.
SECURITY DEFINER allows the function to bypass RLS (the pg_cron worker
runs as a low-privilege user).

Requires: pg_cron extension installed on the Cloud SQL instance
  (cloudsql.enable_pgcron = on in database flags).

References:
  DR-006: 7-year encounter retention
  US-010 DoD: pg_cron job for encounter archival at 03:00 UTC nightly
  BR-022: HIPAA 45 CFR §164.530(j) record retention
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c4e1f2a03d59"
down_revision: Union[str, None] = "b3d0e1f92c48"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RETENTION_YEARS: int = 7
_BATCH_SIZE: int = 500

_ARCHIVE_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION archive_old_encounters()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_cutoff          TIMESTAMPTZ := NOW() - INTERVAL '{_RETENTION_YEARS} years';
    v_batch_ids       UUID[];
    v_batch_count     INTEGER;
    v_total_archived  INTEGER := 0;
BEGIN
    LOOP
        -- Select the next batch of expired encounter IDs.
        -- FOR UPDATE SKIP LOCKED avoids blocking concurrent transactions and
        -- allows parallel batch processing if ever needed in future.
        SELECT array_agg(id)
          INTO v_batch_ids
          FROM (
              SELECT id
                FROM encounter
               WHERE discharge_date < v_cutoff
                 AND deleted_at IS NULL
               ORDER BY discharge_date ASC
               LIMIT {_BATCH_SIZE}
               FOR UPDATE SKIP LOCKED
          ) sub;

        EXIT WHEN v_batch_ids IS NULL OR array_length(v_batch_ids, 1) = 0;

        v_batch_count := array_length(v_batch_ids, 1);

        -- INSERT before DELETE guarantees no data loss if the transaction is
        -- interrupted mid-batch (the archive copy survives, original is untouched).
        INSERT INTO encounter_archive (
            id, patient_id, status, admit_date, discharge_date,
            admitting_diagnosis, attending_physician_id, unit,
            risk_tier, risk_score, visit_number,
            created_at, updated_at, deleted_at,
            archived_at
        )
        SELECT
            id, patient_id, status, admit_date, discharge_date,
            admitting_diagnosis, attending_physician_id, unit,
            risk_tier, risk_score, visit_number,
            created_at, updated_at, deleted_at,
            NOW()
          FROM encounter
         WHERE id = ANY(v_batch_ids);

        DELETE FROM encounter
         WHERE id = ANY(v_batch_ids);

        v_total_archived := v_total_archived + v_batch_count;

        RAISE NOTICE 'archive_old_encounters: archived batch of % rows (total so far: %)',
            v_batch_count, v_total_archived;
    END LOOP;

    RAISE NOTICE 'archive_old_encounters completed: % total rows archived', v_total_archived;
    RETURN v_total_archived;

EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'archive_old_encounters FAILED: %  SQLSTATE: %', SQLERRM, SQLSTATE;
    RAISE;
END;
$$;
"""

_SCHEDULE_SQL = """
SELECT cron.schedule(
    'archive-old-encounters',
    '0 3 * * *',
    $$SELECT archive_old_encounters()$$
);
"""


def upgrade() -> None:
    # ── 1. Ensure pg_cron extension is installed (Cloud SQL: enable via flag) ─
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron;")

    # ── 2. Create the PL/pgSQL archival function ──────────────────────────────
    op.execute(_ARCHIVE_FUNCTION_SQL)

    # ── 3. Register the nightly 03:00 UTC cron job ────────────────────────────
    op.execute(_SCHEDULE_SQL)


def downgrade() -> None:
    # Unschedule the job before dropping the function it calls.
    op.execute("SELECT cron.unschedule('archive-old-encounters');")
    op.execute("DROP FUNCTION IF EXISTS archive_old_encounters();")
    # NOTE: Do NOT drop pg_cron extension — shared with US-008 and US-009 jobs.
