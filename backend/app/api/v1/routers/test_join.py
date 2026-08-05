"""Minimal debug endpoint for patient/encounter JOIN diagnostic."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.deps import get_write_db
from app.models import Patient, Encounter

router = APIRouter(tags=["debug"])


@router.get("/test-join")
async def test_join_diagnostic(session: AsyncSession = Depends(get_write_db)):
    """Test the INNER JOIN logic to diagnose why GET returns 0."""
    try:
        # Query 1: Count all patients
        p_count = await session.execute(select(func.count()).select_from(Patient))
        total_patients = p_count.scalar() or 0
        
        # Query 2: Count active patients
        ap_count = await session.execute(
            select(func.count()).select_from(Patient).where(Patient.deleted_at.is_(None))
        )
        active_patients = ap_count.scalar() or 0
        
        # Query 3: Count all encounters
        e_count = await session.execute(select(func.count()).select_from(Encounter))
        total_encounters = e_count.scalar() or 0
        
        # Query 4: Count active encounters
        ae_count = await session.execute(
            select(func.count()).select_from(Encounter).where(Encounter.deleted_at.is_(None))
        )
        active_encounters = ae_count.scalar() or 0
        
        # Query 5: Count successful JOINs
        join_count = await session.execute(
            select(func.count()).select_from(Patient).join(
                Encounter, Patient.id == Encounter.patient_id
            ).where(and_(Patient.deleted_at.is_(None), Encounter.deleted_at.is_(None)))
        )
        join_total = join_count.scalar() or 0
        
        return {
            "total_patients": total_patients,
            "active_patients": active_patients,
            "total_encounters": total_encounters,
            "active_encounters": active_encounters,
            "join_success": join_total,
            "diagnosis": (
                "✓ OK" if join_total > 0 else
                "✗ PROBLEM: No successful JOINs despite active records"
            )
        }
    except Exception as e:
        return {"error": str(e)}
