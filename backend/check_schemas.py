import psycopg2
conn = psycopg2.connect('dbname=smarthandoff user=postgres password=SmartHandoff@123 host=127.0.0.1 port=9432')
cursor = conn.cursor()

tables_to_check = ['medication', 'notification', 'document', 'agent_task', 'audit_log']

for table in tables_to_check:
    print(f'\n📋 {table.upper()} columns:')
    try:
        cursor.execute(f"SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position", (table,))
        for row in cursor.fetchall():
            nullable = "YES" if row[2] else "NO"
            print(f'  • {row[0]:25s} {row[1]:20s} NULL: {nullable}')
    except Exception as e:
        print(f'  Error: {e}')

cursor.close()
conn.close()
