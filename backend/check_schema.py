#!/usr/bin/env python3
"""Check patient table schema."""
import asyncio
import asyncpg

async def check_schema():
    conn = await asyncpg.connect('postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff')
    columns = await conn.fetch(
        'SELECT column_name, data_type FROM information_schema.columns WHERE table_name = \'patient\' ORDER BY ordinal_position'
    )
    print('Patient table columns:')
    for col in columns:
        print(f'  {col["column_name"]}: {col["data_type"]}')
    
    # Also get the first patient record to see what data looks like
    print('\nFirst patient sample:')
    patient = await conn.fetchrow('SELECT id, first_name, last_name, mrn_encrypted FROM patient LIMIT 1')
    if patient:
        for key, value in patient.items():
            if isinstance(value, bytes):
                print(f'  {key}: {value[:50]}... (bytes, length={len(value)})')
            else:
                print(f'  {key}: {value}')
    
    await conn.close()

asyncio.run(check_schema())
