import psycopg2

conn = psycopg2.connect(
    host="127.0.0.1",
    port=9432,
    dbname="smarthandoff",
    user="postgres",
    password="SmartHandoff@123",
)
cur = conn.cursor()
cur.execute("SELECT matviewname FROM pg_matviews WHERE schemaname='public'")
print("Materialized views:", [r[0] for r in cur.fetchall()])
cur.execute("SELECT version_num FROM alembic_version")
print("Alembic versions:", [r[0] for r in cur.fetchall()])
conn.close()
