"""pg_cron scheduled refresh jobs for materialised views.

Revision ID: a6d9c2b48e51
Revises: f5c8e1a73b29
Create Date: 2026-07-21

Hand-authored — schedules pg_cron jobs for materialised view refresh.
Must be applied AFTER the Cloud SQL instance has cloudsql.enable_pgcron=on.

Schedules:
  mv_bed_board         — every minute (sub-minute handled by encounter trigger)
  mv_risk_dashboard    — every 5 minutes
  mv_kpi_daily         — nightly at 02:00 UTC

References:
  DR-007: Refresh intervals for materialised views
  US-009 DoD: pg_cron jobs scheduled
  US-009 Technical Notes: cloudsql.enable_pgcron flag required
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "a6d9c2b48e51"
down_revision: Union[str, None] = "f5c8e1a73b29"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enable pg_cron extension ──────────────────────────────────────────────
    # Idempotent — safe to run on re-deploy.
    # US-008/TASK-003 may have already created this extension; IF NOT EXISTS
    # ensures this migration is safe to apply in any order.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_cron;")

    # ── Schedule mv_bed_board refresh — every 1 minute ───────────────────────
    # CONCURRENTLY avoids locking reads during refresh.
    # The job runs as the database superuser on Cloud SQL (pg_cron limitation).
    op.execute("""
        SELECT cron.schedule(
            'refresh_mv_bed_board',
            '*/1 * * * *',
            $$REFRESH MATERIALIZED VIEW CONCURRENTLY mv_bed_board$$
        );
    """)

    # ── Schedule mv_risk_dashboard refresh — every 5 minutes ─────────────────
    op.execute("""
        SELECT cron.schedule(
            'refresh_mv_risk_dashboard',
            '*/5 * * * *',
            $$REFRESH MATERIALIZED VIEW CONCURRENTLY mv_risk_dashboard$$
        );
    """)

    # ── Schedule mv_kpi_daily refresh — nightly at 02:00 UTC ─────────────────
    op.execute("""
        SELECT cron.schedule(
            'refresh_mv_kpi_daily',
            '0 2 * * *',
            $$REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kpi_daily$$
        );
    """)


def downgrade() -> None:
    # Unschedule all three jobs before attempting extension removal
    op.execute("SELECT cron.unschedule('refresh_mv_bed_board');")
    op.execute("SELECT cron.unschedule('refresh_mv_risk_dashboard');")
    op.execute("SELECT cron.unschedule('refresh_mv_kpi_daily');")

    # Do NOT drop the pg_cron extension — US-008/TASK-003 also uses it for the
    # audit log retention job. Only unschedule our specific jobs.
