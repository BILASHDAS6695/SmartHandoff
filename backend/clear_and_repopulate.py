#!/usr/bin/env python3
"""Clear patient data and repopulate with correct encryption."""
import asyncio
import asyncpg
import os

async def clear_and_repopulate():
    # Set env vars
    os.environ["PYTHONPATH"] = "."
    os.environ["PHI_ENCRYPTION_KEY"] = "peF3ahNpMuTZD6tm-B9tNA5YKZlxYSQNYVZd2x6Ou3A="
    os.environ["PRIMARY_DATABASE_URL"] = "postgresql+asyncpg://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
    os.environ["REPLICA_DATABASE_URL"] = "postgresql+asyncpg://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
    os.environ["ALLOW_UNAUTHENTICATED_LOCALHOST"] = "true"
    
    # Connect and clear patient table
    conn = await asyncpg.connect(
        'postgresql://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff'
    )
    
    print("[*] Clearing existing patient and related data...")
    await conn.execute('DELETE FROM encounter')
    print("[OK] Cleared encounter table")
    await conn.execute('DELETE FROM patient')
    print("[OK] Cleared patient table")
    
    await conn.close()
    
    # Now run populate_test_data to reload with correct encryption
    print("\n[*] Repopulating with 100 realistic patients and encounters...")
    import populate_test_data
    
    populator = populate_test_data.TestDataPopulator(
        "postgresql+asyncpg://postgres:SmartHandoff%40123@127.0.0.1:9432/smarthandoff"
    )
    
    if await populator.connect():
        patients = await populator.populate_patients()
        print(f"[OK] {len(patients)} patients created")
        
        encounters = await populator.populate_encounters(patients)
        print(f"[OK] {len(encounters)} encounters created")
        
        print("[OK] Database repopulated successfully!")
        await populator.engine.dispose()
    else:
        print("[ERROR] Failed to connect to database")

if __name__ == "__main__":
    asyncio.run(clear_and_repopulate())
