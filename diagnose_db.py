#!/usr/bin/env python3
"""Diagnose GET /patients issue by checking database state."""
import asyncio
import os
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Import models
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.models.patient import Patient
from app.models.encounter import Encounter

async def main():
    """Check database state."""
    # Connection string (use Cloud SQL proxy)
    db_url = "postgresql+asyncpg://postgres:SmartHandoff%40123@localhost:5432/smarthandoff"
    
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        try:
            # Count all patients
            patient_result = await session.execute(
                select(func.count()).select_from(Patient)
            )
            total_patients = patient_result.scalar() or 0
            
            # Count non-deleted patients
            non_deleted_patients = await session.execute(
                select(func.count()).select_from(Patient).where(Patient.deleted_at.is_(None))
            )
            active_patients = non_deleted_patients.scalar() or 0
            
            # Count all encounters
            encounter_result = await session.execute(
                select(func.count()).select_from(Encounter)
            )
            total_encounters = encounter_result.scalar() or 0
            
            # Count non-deleted encounters
            non_deleted_encounters = await session.execute(
                select(func.count()).select_from(Encounter).where(Encounter.deleted_at.is_(None))
            )
            active_encounters = non_deleted_encounters.scalar() or 0
            
            # Count valid JOIN results
            join_result = await session.execute(
                select(func.count()).select_from(Patient).join(
                    Encounter, Patient.id == Encounter.patient_id
                ).where(and_(Patient.deleted_at.is_(None), Encounter.deleted_at.is_(None)))
            )
            valid_join = join_result.scalar() or 0
            
            # Sample some patient and encounter records
            patients = await session.execute(
                select(Patient.id, Patient.first_name, Patient.mrn_encrypted).limit(3)
            )
            patient_samples = patients.fetchall()
            
            encounters = await session.execute(
                select(Encounter.id, Encounter.patient_id, Encounter.deleted_at).limit(3)
            )
            encounter_samples = encounters.fetchall()
            
            print("=" * 60)
            print("DATABASE DIAGNOSTIC REPORT")
            print("=" * 60)
            print(f"Total Patients: {total_patients}")
            print(f"Active Patients (deleted_at IS NULL): {active_patients}")
            print(f"Total Encounters: {total_encounters}")
            print(f"Active Encounters (deleted_at IS NULL): {active_encounters}")
            print(f"Valid JOIN results (both deleted_at IS NULL): {valid_join}")
            print()
            print("Sample Patients:")
            for p_id, fname, mrn in patient_samples:
                print(f"  {p_id}: {fname} (MRN: {mrn})")
            print()
            print("Sample Encounters:")
            for e_id, p_id, deleted_at in encounter_samples:
                print(f"  {e_id} -> Patient {p_id} (deleted_at: {deleted_at})")
            print()
            print("DIAGNOSIS:")
            if active_patients > 0 and valid_join == 0:
                print("  ✗ PROBLEM: Patients exist but JOIN returns 0")
                print("    - Possible causes:")
                print("      1. Encounter records not created during sync")
                print("      2. Encounter.patient_id is NULL")
                print("      3. Encounter records are soft-deleted")
            elif active_patients == 0:
                print("  ✗ PROBLEM: No active patients in database")
                print("    - Sync may not be working or all patients were deleted")
            elif valid_join > 0:
                print("  ✓ SUCCESS: Database contains valid JOIN results")
                print(f"    - GET /patients should return {valid_join} records")
            print("=" * 60)
            
        finally:
            await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
