"""pg_cron 6-year audit log retention — archive queue and nightly jobs.

Revision ID: d4b7e2f91c30
Revises: c2e5f8a91d3b
Create Date: 2026-07-15

Hand-authored per US-008/TASK-003 (autogenerate disabled).

Implements BR-023: audit_log rows must be retained for at least 6 years
(2 190 days). Rows older than that are moved to an archive queue and
eventually exported to GCS, then deleted from the hot table.

pg_cron jobs (Cloud SQL managed — enabled via cloudsql.enable_pg_cron flag):
  - 02:00 UTC daily → archive_expired_audit_logs()
  - 03:00 UTC daily → delete_archived_audit_logs()

IMPORTANT: This migration requires the pg_cron extension which is only
available in Cloud SQL for PostgreSQL or a managed Postgres >= 12 instance
with pg_cron installed. Do NOT run against the testcontainers postgres:15
image used in integration tests — it will fail. The test suite excludes
tests that depend on this migration (see pytest mark 'requires_pgcron').
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4b7e2f91c30"
down_revision: Union[str, None] = "c2e5f8a91d3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Retention window in days (6 years = 6 × 365)
_RETENTION_DAYS = 2190


def upgrade() -> None:
    # ── 1. Enable pg_cron extension ───────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron;")
    op.execute("GRANT USAGE ON SCHEMA cron TO CURRENT_USER;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON cron.job TO CURRENT_USER;")

    # ── 2. Create audit_log_archive_queue table ───────────────────────────
    # Rows land here when they age out of the hot audit_log table.
    # A downstream GCS exporter sets exported_at + gcs_object_path once
    # the payload has been durably written to cold storage.
    op.create_table(
        "audit_log_archive_queue",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("audit_log_id", sa.UUID(), nullable=False),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gcs_object_path", sa.String(512), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_archive_queue_audit_log_id",
        "audit_log_archive_queue",
        ["audit_log_id"],
    )
    op.create_index(
        "ix_archive_queue_queued_at",
        "audit_log_archive_queue",
        ["queued_at"],
    )
    op.create_index(
        "ix_archive_queue_exported_at",
        "audit_log_archive_queue",
        ["exported_at"],
    )

    # ── 3. archive_expired_audit_logs() function ──────────────────────────
    # SECURITY DEFINER so pg_cron worker (cron role) has INSERT privileges
    # on the archive queue even when running as a low-privilege role.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION archive_expired_audit_logs()
        RETURNS INTEGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        DECLARE
            _cutoff TIMESTAMP WITH TIME ZONE;
            _batch_id TEXT;
            _rows_archived INTEGER;
        BEGIN
            _cutoff := NOW() - INTERVAL '{_RETENTION_DAYS} days';
            _batch_id := gen_random_uuid()::TEXT;

            INSERT INTO audit_log_archive_queue (
                id, audit_log_id, queued_at, exported_at, gcs_object_path, payload
            )
            SELECT
                gen_random_uuid(),
                al.id,
                NOW(),
                NULL,
                NULL,
                row_to_json(al)
            FROM audit_log al
            WHERE al.created_at < _cutoff
              AND al.id NOT IN (
                  SELECT audit_log_id FROM audit_log_archive_queue
              );

            GET DIAGNOSTICS _rows_archived = ROW_COUNT;

            -- Only notify when rows were actually queued (avoids spurious wakeups)
            IF _rows_archived > 0 THEN
                PERFORM pg_notify(
                    'audit_archive_trigger',
                    json_build_object(
                        'batch_id', _batch_id,
                        'rows_archived', _rows_archived,
                        'cutoff', _cutoff
                    )::TEXT
                );
            END IF;

            RETURN _rows_archived;
        END;
        $$;
    """)

    # ── 4. delete_archived_audit_logs() function ──────────────────────────
    # Deletes rows from audit_log and the archive queue only after the
    # GCS exporter has confirmed export (exported_at IS NOT NULL).
    op.execute("""
        CREATE OR REPLACE FUNCTION delete_archived_audit_logs()
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        DECLARE
            _rows_deleted INTEGER;
        BEGIN
            -- Remove confirmed-exported rows from the hot table
            DELETE FROM audit_log
            WHERE id IN (
                SELECT audit_log_id
                FROM audit_log_archive_queue
                WHERE exported_at IS NOT NULL
            );

            GET DIAGNOSTICS _rows_deleted = ROW_COUNT;

            -- Clean up confirmed queue entries
            DELETE FROM audit_log_archive_queue
            WHERE exported_at IS NOT NULL;
        END;
        $$;
    """)

    # ── 5. Schedule nightly pg_cron jobs ──────────────────────────────────
    op.execute("""
        SELECT cron.schedule(
            'archive-expired-audit-logs',
            '0 2 * * *',
            'SELECT archive_expired_audit_logs()'
        );
    """)
    op.execute("""
        SELECT cron.schedule(
            'delete-archived-audit-logs',
            '0 3 * * *',
            'SELECT delete_archived_audit_logs()'
        );
    """)


def downgrade() -> None:
    # ── Unschedule pg_cron jobs ───────────────────────────────────────────
    op.execute("""
        SELECT cron.unschedule('delete-archived-audit-logs');
    """)
    op.execute("""
        SELECT cron.unschedule('archive-expired-audit-logs');
    """)

    # ── Drop functions ────────────────────────────────────────────────────
    op.execute("DROP FUNCTION IF EXISTS delete_archived_audit_logs();")
    op.execute("DROP FUNCTION IF EXISTS archive_expired_audit_logs();")

    # ── Drop archive queue table ──────────────────────────────────────────
    op.drop_index("ix_archive_queue_exported_at", table_name="audit_log_archive_queue")
    op.drop_index("ix_archive_queue_queued_at", table_name="audit_log_archive_queue")
    op.drop_index("ix_archive_queue_audit_log_id", table_name="audit_log_archive_queue")
    op.drop_table("audit_log_archive_queue")

    # ── Drop pg_cron extension ────────────────────────────────────────────
    op.execute("REVOKE USAGE ON SCHEMA cron FROM CURRENT_USER;")
    op.execute("DROP EXTENSION IF EXISTS pg_cron;")
