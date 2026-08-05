#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect('dbname=smarthandoff user=postgres password=SmartHandoff@123 host=127.0.0.1 port=9432')
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
tables = [row[0] for row in cursor.fetchall()]

print('\n📋 Database Tables Found:')
print('=' * 60)
for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    emoji = '✅' if count > 0 else '⚠️ '
    print(f'{emoji} {table:30s}: {count:6d} records')
print('=' * 60)

total = sum([cursor.execute(f"SELECT COUNT(*) FROM {table}") or cursor.fetchone()[0] for table in tables])
print(f'\n🎉 TOTAL RECORDS: {total}\n')

conn.close()
