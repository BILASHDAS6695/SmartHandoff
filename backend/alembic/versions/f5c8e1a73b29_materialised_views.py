"""Materialised views: mv_bed_board, mv_risk_dashboard, mv_kpi_daily.

Revision ID: f5c8e1a73b29
Revises: e1f8d3c92a47
Create Date: 2026-07-21

Hand-authored — autogenerate disabled for materialised views.
Materialised views are excluded from alembic autogenerate in env.py via
include_object() filter on names starting with 'mv_'.

Creates:
  mv_bed_board         — real-time bed occupancy (trigger-refreshed + 60s pg_cron)
  mv_risk_dashboard    — patient risk tier grouping (5-min pg_cron)
  mv_kpi_daily         — KPI aggregates (nightly pg_cron)
  refresh_mv_bed_board() — trigger function for event-driven refresh

References:
  DR-007: Materialised views spec
  TR-010: Read replica routing for dashboard GET requests
  ADR-006: CQRS — materialised views on read replica
  US-009 Scenario 4: mv_bed_board ≤60s, mv_risk_dashboard ≤5min
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "f5c8e1a73b29"
down_revision: Union[str, None] = "e1f8d3c92a47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. mv_bed_board ──────────────────────────────────────────────────────
    # Columns: unit, bed_id, bed_label, encounter_id, patient_id,
    #          patient_first_name_enc, patient_last_name_enc (encrypted ciphertext),
    #          admit_time, encounter_status, expected_discharge_date, risk_tier
    #
    # NOTE: patient_first_name_enc and patient_last_name_enc store encrypted
    # ciphertext from the patient table — no plaintext PHI in the view.
    # The application layer decrypts via ORM TypeDecorator on the read path.
    #
    # CONCURRENTLY: Not used on first CREATE (view must be populated first).
    # pg_cron and trigger-based REFRESH use CONCURRENTLY to avoid locking.
    op.execute("""
        CREATE MATERIALIZED VIEW mv_bed_board AS
        SELECT
            b.unit,
            b.id            AS bed_id,
            b.label         AS bed_label,
            e.id            AS encounter_id,
            e.patient_id,
            p.first_name    AS patient_first_name_enc,
            p.last_name     AS patient_last_name_enc,
            e.admit_time,
            e.status        AS encounter_status,
            e.expected_discharge_date,
            e.risk_tier
        FROM bed b
        LEFT JOIN encounter e
               ON e.bed_id = b.id
              AND e.status IN ('ADMITTED', 'TRANSFERRED')
              AND e.deleted_at IS NULL
        LEFT JOIN patient p
               ON p.id = e.patient_id
              AND p.deleted_at IS NULL
        WITH DATA;
    """)

    # Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
    op.execute("""
        CREATE UNIQUE INDEX mv_bed_board_bed_id_idx ON mv_bed_board (bed_id);
    """)

    # Index for filtering by unit (bed board queries filter by unit)
    op.execute("""
        CREATE INDEX mv_bed_board_unit_idx ON mv_bed_board (unit);
    """)

    # ── 2. Trigger function for event-driven mv_bed_board refresh ────────────
    # Fires on encounter INSERT/UPDATE/DELETE so the bed board reflects changes
    # faster than the 60-second pg_cron schedule during busy discharge periods.
    op.execute("""
        CREATE OR REPLACE FUNCTION refresh_mv_bed_board()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        BEGIN
            -- NOTE: CONCURRENTLY cannot run inside a transaction block (PostgreSQL restriction).
            -- This trigger fires AFTER the triggering statement's transaction commits, but
            -- the trigger body itself runs within that transaction. Use non-CONCURRENTLY here.
            -- The pg_cron job (TASK-005) runs CONCURRENTLY every minute for non-blocking refresh.
            REFRESH MATERIALIZED VIEW mv_bed_board;
            RETURN NULL;
        END;
        $$;
    """)

    op.execute("""
        CREATE TRIGGER trg_refresh_mv_bed_board
        AFTER INSERT OR UPDATE OR DELETE ON encounter
        FOR EACH STATEMENT
        EXECUTE FUNCTION refresh_mv_bed_board();
    """)

    # ── 3. mv_risk_dashboard ─────────────────────────────────────────────────
    # Columns: unit, risk_tier, patient_count, encounter_ids (array)
    # Refresh: every 5 minutes via pg_cron (TASK-005)
    op.execute("""
        CREATE MATERIALIZED VIEW mv_risk_dashboard AS
        SELECT
            e.unit,
            e.risk_tier,
            COUNT(e.id)                             AS patient_count,
            ARRAY_AGG(e.id ORDER BY e.admit_time)   AS encounter_ids
        FROM encounter e
        WHERE e.status IN ('ADMITTED', 'TRANSFERRED')
          AND e.deleted_at IS NULL
        GROUP BY e.unit, e.risk_tier
        WITH DATA;
    """)

    # Unique index for CONCURRENTLY refresh
    op.execute("""
        CREATE UNIQUE INDEX mv_risk_dashboard_unit_tier_idx
            ON mv_risk_dashboard (unit, risk_tier);
    """)

    # ── 4. mv_kpi_daily ──────────────────────────────────────────────────────
    # Columns: kpi_date, adt_event_count, admission_count, discharge_count,
    #          avg_los_hours, doc_generation_count, avg_readmission_risk_score
    # Refresh: nightly at 02:00 UTC via pg_cron (TASK-005)
    op.execute("""
        CREATE MATERIALIZED VIEW mv_kpi_daily AS
        SELECT
            DATE_TRUNC('day', e.admit_time)             AS kpi_date,
            COUNT(e.id)                                 AS adt_event_count,
            COUNT(e.id) FILTER (WHERE e.status != 'REGISTERED')
                                                        AS admission_count,
            COUNT(e.id) FILTER (WHERE e.status = 'DISCHARGED')
                                                        AS discharge_count,
            AVG(
                EXTRACT(EPOCH FROM (e.discharge_time - e.admit_time)) / 3600.0
            ) FILTER (WHERE e.discharge_time IS NOT NULL)
                                                        AS avg_los_hours,
            COUNT(d.id)                                 AS doc_generation_count,
            AVG(e.readmission_risk_score)
                FILTER (WHERE e.readmission_risk_score IS NOT NULL)
                                                        AS avg_readmission_risk_score
        FROM encounter e
        LEFT JOIN document d
               ON d.encounter_id = e.id
              AND d.deleted_at IS NULL
        WHERE e.deleted_at IS NULL
          AND e.admit_time >= CURRENT_DATE - INTERVAL '90 days'
        GROUP BY DATE_TRUNC('day', e.admit_time)
        WITH DATA;
    """)

    # Unique index for CONCURRENTLY refresh
    op.execute("""
        CREATE UNIQUE INDEX mv_kpi_daily_date_idx ON mv_kpi_daily (kpi_date);
    """)


def downgrade() -> None:
    # Drop trigger and function before the view (dependency order)
    op.execute(
        "DROP TRIGGER IF EXISTS trg_refresh_mv_bed_board ON encounter;"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS refresh_mv_bed_board();"
    )
    op.execute(
        "DROP MATERIALIZED VIEW IF EXISTS mv_bed_board;"
    )
    op.execute(
        "DROP MATERIALIZED VIEW IF EXISTS mv_risk_dashboard;"
    )
    op.execute(
        "DROP MATERIALIZED VIEW IF EXISTS mv_kpi_daily;"
    )
