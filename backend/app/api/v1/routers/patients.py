"""Patient resource router — RBAC-protected endpoints."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_write_db
from app.models.bed import Bed
from app.models.encounter import Encounter
from app.models.patient import Patient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("")
async def list_patients(
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "list"))],
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    unit: str = Query(""),
    # NOTE: Uses get_write_db for local dev — both read and write point to same database
    db: AsyncSession = Depends(get_write_db),
) -> dict:
    """List all patients with encounter-level data — requires patient:list permission.
    
    Returns encounter records (not patient records) to include room_number and admission_date.
    """
    try:
        logger.info(f"Fetching patients: page={page}, page_size={page_size}, unit={unit}")
        
        # Step 1: Get total count first
        count_query = (
            select(func.count(Encounter.id))
            .join(Patient, Encounter.patient_id == Patient.id)
            .where(Patient.deleted_at.is_(None))
            .where(Encounter.deleted_at.is_(None))
        )
        if unit:
            count_query = count_query.where(Encounter.unit == unit)
        
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0
        logger.info(f"Total encounters: {total}")
        
        # Step 2: Fetch paginated encounter data
        data_query = (
            select(
                Encounter.id.label("encounter_id"),
                Patient.id.label("patient_id"),
                Patient.first_name,
                Patient.last_name,
                Patient.date_of_birth,
                Patient.mrn_encrypted,
                Encounter.unit.label("current_unit"),
                Bed.bed_number.label("room_number"),
                Encounter.risk_tier,
                Encounter.created_at.label("admission_date"),
            )
            .join(Patient, Encounter.patient_id == Patient.id)
            .outerjoin(Bed, Bed.current_encounter_id == Encounter.id)
            .where(Patient.deleted_at.is_(None))
            .where(Encounter.deleted_at.is_(None))
        )
        
        if unit:
            data_query = data_query.where(Encounter.unit == unit)
        
        # Apply pagination
        offset = (page - 1) * page_size
        data_query = data_query.offset(offset).limit(page_size).order_by(Encounter.created_at.desc())
        
        logger.info(f"Executing data query with offset={offset}, limit={page_size}")
        result = await db.execute(data_query)
        rows = result.all()
        logger.info(f"Fetched {len(rows)} rows")
        
        # Step 3: Convert rows to response format
        patient_items = []
        for row in rows:
            # Mask MRN to last 4 digits for HIPAA compliance
            mrn = row.mrn_encrypted or ""
            mrn_masked = f"****{mrn[-4:]}" if mrn and len(str(mrn)) >= 4 else "****"
            
            patient_items.append({
                "encounter_id": str(row.encounter_id),
                "patient_id": str(row.patient_id),
                "first_name": row.first_name or "",
                "last_name": row.last_name or "",
                "date_of_birth": row.date_of_birth or "",
                "current_unit": row.current_unit or "",
                "room_number": row.room_number or "",
                "mrn_masked": mrn_masked,
                "risk_tier": row.risk_tier or "UNKNOWN",
                "risk_score": None,
                "admission_date": row.admission_date.isoformat() if row.admission_date else "",
            })
        
        logger.info(f"Returning {len(patient_items)} patient items")
        return {
            "items": patient_items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        # Log the error and re-raise for proper HTTP error response
        logger.error(f"❌ Error fetching patients: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch patients: {str(e)}")


@router.get("/{patient_id}")
async def get_patient(
    patient_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "read"))],
) -> dict:
    """Get a single patient — requires patient:read permission."""
    # TODO: implement patient detail query
    return {"patient_id": str(patient_id), "user": current_user.sub}


@router.patch("/{patient_id}")
async def update_patient(
    patient_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("patient", "write"))],
) -> dict:
    """Update a patient — requires patient:write permission."""
    # TODO: implement patient update
    return {"patient_id": str(patient_id), "user": current_user.sub}
