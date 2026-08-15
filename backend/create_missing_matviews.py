"""Create/recreate materialized views used by the bed board and dashboards.

Uses asyncpg so it can run inside the project virtualenv without psycopg2.
"""
from __future__ import annotations

import asyncio
import socket

import asyncpg

DB_HOST = socket.gethostbyname("localhost")
DB_DSN = f"postgresql://postgres:SmartHandoff%40123@{DB_HOST}:9432/smarthandoff"


async def main() -> None:
    conn = await asyncpg.connect(DB_DSN, ssl=False)

    rows = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='patient' ORDER BY ordinal_position"
    )
    print("patient columns:")
    for row in rows:
        print(" ", row)

    # Drop existing incomplete view
    await conn.execute("DROP MATERIALIZED VIEW IF EXISTS mv_bed_board CASCADE")

    await conn.execute("""
        CREATE MATERIALIZED VIEW mv_bed_board AS
        SELECT
            b.id                              AS bed_id,
            b.unit                            AS unit,
            COALESCE(b.ward, '')              AS room,
            b.bed_number                      AS bed_number,
            'STANDARD'                        AS bed_type,
            CASE UPPER(b.status)
                WHEN 'AVAILABLE' THEN 'VACANT'
                ELSE UPPER(b.status)
            END                               AS status,
            false                             AS isolation_required,
            'UNISEX'                          AS gender_designation,
            b.predicted_discharge_at          AS predicted_discharge_time,
            p.first_name                       AS patient_first_name_enc,
            p.last_name                        AS patient_last_name_enc
        FROM bed b
        LEFT JOIN encounter e
               ON e.id = b.current_encounter_id
              AND e.deleted_at IS NULL
        LEFT JOIN patient p
               ON p.id = e.patient_id
              AND p.deleted_at IS NULL
        WITH DATA;
    """)

    await conn.execute("DROP INDEX IF EXISTS mv_bed_board_bed_id_idx")
    await conn.execute("DROP INDEX IF EXISTS mv_bed_board_unit_idx")
    await conn.execute("CREATE UNIQUE INDEX mv_bed_board_bed_id_idx ON mv_bed_board (bed_id)")
    await conn.execute("CREATE INDEX mv_bed_board_unit_idx ON mv_bed_board (unit)")

    await conn.execute("""
        CREATE OR REPLACE FUNCTION refresh_mv_bed_board()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW mv_bed_board;
            RETURN NULL;
        END;
        $$;
    """)

    await conn.execute("""
        DROP TRIGGER IF EXISTS trg_refresh_mv_bed_board ON bed;
        CREATE TRIGGER trg_refresh_mv_bed_board
        AFTER INSERT OR UPDATE OR DELETE ON bed
        FOR EACH STATEMENT
        EXECUTE FUNCTION refresh_mv_bed_board();
    """)

    # Risk dashboard
    await conn.execute("DROP MATERIALIZED VIEW IF EXISTS mv_risk_dashboard CASCADE")
    await conn.execute("""
        CREATE MATERIALIZED VIEW mv_risk_dashboard AS
        SELECT
            e.unit,
            e.risk_tier,
            COUNT(e.id)                             AS patient_count,
            ARRAY_AGG(e.id ORDER BY e.admit_date)   AS encounter_ids
        FROM encounter e
        WHERE e.status IN ('ADMITTED', 'TRANSFERRED')
          AND e.deleted_at IS NULL
        GROUP BY e.unit, e.risk_tier
        WITH DATA;
    """)
    await conn.execute("DROP INDEX IF EXISTS mv_risk_dashboard_unit_risk_idx")
    await conn.execute("CREATE UNIQUE INDEX mv_risk_dashboard_unit_risk_idx ON mv_risk_dashboard (unit, risk_tier)")

    rows = await conn.fetch("SELECT matviewname FROM pg_matviews WHERE schemaname='public'")
    print("Materialized views:", [r[0] for r in rows])

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
