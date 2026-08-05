#!/usr/bin/env python3
"""Check what's stored in the patient table."""
import asyncio
import asyncpg
import os

async def check_data():
    conn = await asyncpg.connect(
        'postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff'
    )
    
    # Check encrypted fields
    patient = await conn.fetchrow(
        'SELECT id, first_name, first_name_encrypted, mrn_encrypted FROM patient LIMIT 1'
    )
    
    if patient:
        print('First patient row:')
        print(f'  id: {patient["id"]}')
        print(f'  first_name (plain if stored): {patient.get("first_name", "N/A")}')
        encrypted_sample = str(patient.get("first_name_encrypted", "N/A"))
        print(f'  first_name_encrypted (first 80 chars): {encrypted_sample[:80]}...')
        print(f'  first_name_encrypted length: {len(encrypted_sample) if encrypted_sample != "N/A" else "N/A"}')
        mrn_sample = str(patient.get("mrn_encrypted", "N/A"))
        print(f'  mrn_encrypted (first 80 chars): {mrn_sample[:80]}...')
        print(f'  mrn_encrypted length: {len(mrn_sample) if mrn_sample != "N/A" else "N/A"}')
    else:
        print("No patient records found in database!")
    
    await conn.close()

asyncio.run(check_data())
