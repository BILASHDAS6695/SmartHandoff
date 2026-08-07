import psycopg2

conn = psycopg2.connect(
    host="127.0.0.1",
    port=9432,
    dbname="smarthandoff",
    user="postgres",
    password="SmartHandoff@123",
)
cur = conn.cursor()

cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name='patient' ORDER BY ordinal_position")
print("patient columns:")
for row in cur.fetchall():
    print(" ", row)

# Drop existing incomplete view
cur.execute("DROP MATERIALIZED VIEW IF EXISTS mv_bed_board CASCADE")

cur.execute("""
    CREATE MATERIALIZED VIEW mv_bed_board AS
    SELECT
        b.id                              AS bed_id,
        b.unit                            AS unit,
        COALESCE(b.ward, '')              AS room,
        b.bed_number                      AS bed_number,
        'STANDARD'                        AS bed_type,
        CASE b.status
            WHEN 'AVAILABLE' THEN 'VACANT'
            ELSE b.status
        END                               AS status,
        false                             AS isolation_required,
        'UNISEX'                          AS gender_designation,
        b.predicted_discharge_at          AS predicted_discharge_time
    FROM bed b
    WITH DATA;
""")

cur.execute("DROP INDEX IF EXISTS mv_bed_board_bed_id_idx")
cur.execute("DROP INDEX IF EXISTS mv_bed_board_unit_idx")
cur.execute("CREATE UNIQUE INDEX mv_bed_board_bed_id_idx ON mv_bed_board (bed_id)")
cur.execute("CREATE INDEX mv_bed_board_unit_idx ON mv_bed_board (unit)")

cur.execute("""
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

cur.execute("""
    DROP TRIGGER IF EXISTS trg_refresh_mv_bed_board ON bed;
    CREATE TRIGGER trg_refresh_mv_bed_board
    AFTER INSERT OR UPDATE OR DELETE ON bed
    FOR EACH STATEMENT
    EXECUTE FUNCTION refresh_mv_bed_board();
""")

# Risk dashboard
cur.execute("DROP MATERIALIZED VIEW IF EXISTS mv_risk_dashboard CASCADE")
cur.execute("""
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
cur.execute("DROP INDEX IF EXISTS mv_risk_dashboard_unit_risk_idx")
cur.execute("CREATE UNIQUE INDEX mv_risk_dashboard_unit_risk_idx ON mv_risk_dashboard (unit, risk_tier)")

conn.commit()

cur.execute("SELECT matviewname FROM pg_matviews WHERE schemaname='public'")
print("Materialized views:", [r[0] for r in cur.fetchall()])

conn.close()
