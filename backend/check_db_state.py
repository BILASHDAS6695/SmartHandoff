#!/usr/bin/env python3
"""Check current database state."""
import asyncio
import asyncpg

async def check_data():
    conn = await asyncpg.connect('postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff')
    
    # Count patients
    count = await conn.fetchval('SELECT COUNT(*) FROM patient')
    print(f'Total patients: {count}')
    
    # Count encounters  
    enc_count = await conn.fetchval('SELECT COUNT(*) FROM encounter')
    print(f'Total encounters: {enc_count}')
    
    # Show first patient
    patient = await conn.fetchrow('SELECT id, first_name, mrn_encrypted FROM patient LIMIT 1')
    if patient:
        print(f'\nFirst patient ID: {patient["id"]}')
        print(f'First name (encrypted): {str(patient["first_name"])[:80]}...')
        print(f'MRN (encrypted): {str(patient["mrn_encrypted"])[:80]}...')
    else:
        print('\nNo patients found!')
    
    await conn.close()

asyncio.run(check_data())
