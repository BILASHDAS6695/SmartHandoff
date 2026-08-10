"""Medication resource router — RBAC-protected endpoints."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims, sub_to_uuid
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db
from app.models.encounter import Encounter
from app.models.medication import MedicationListSource
from app.repositories.medication_repository import (
    get_reconciliation_completed_at,
    get_reconciliation_results,
)
from app.schemas.medication import (
    MedicationReconciliationResponse,
    MedicationReconciliationResult,
)

router = APIRouter(prefix="/medications", tags=["medications"])

# US-030: Encounter-scoped medication reconciliation endpoints
encounters_medications_router = APIRouter(
    prefix="/encounters",
    tags=["medications"],
)


@router.get("")
async def list_medications(
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "list"))],
) -> dict:
    """List medications — requires medication:list permission."""
    return {"medications": [], "user": current_user.sub}


@router.get("/{medication_id}")
async def get_medication(
    medication_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "read"))],
) -> dict:
    """Get a single medication — requires medication:read permission."""
    return {"medication_id": str(medication_id), "user": current_user.sub}


@router.post("")
async def create_medication(
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "write"))],
) -> dict:
    """Create a medication — requires medication:write permission."""
    return {"created": True, "user": current_user.sub}


@router.patch("/{medication_id}")
async def update_medication(
    medication_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "write"))],
) -> dict:
    """Update a medication — requires medication:write permission."""
    return {"medication_id": str(medication_id), "user": current_user.sub}


# ============================================================================
# US-030: Medication Reconciliation Endpoint
# ============================================================================

@encounters_medications_router.get(
    "/{encounter_id}/medications/reconciliation",
    response_model=MedicationReconciliationResponse,
    summary="Get medication reconciliation results for an encounter",
    description=(
        "Returns a three-way medication comparison (pre-admission, inpatient, discharge) "
        "with each drug categorised as CONTINUED, NEW, STOPPED, or DOSE_CHANGED. "
        "Flags include DUPLICATE and STOPPED_WITHOUT_ORDER. "
        "Returns 202 if reconciliation is still in progress."
    ),
    responses={
        200: {"description": "Reconciliation results"},
        202: {"description": "Reconciliation in progress"},
        403: {"description": "Insufficient permissions"},
        404: {"description": "Encounter not found"},
    },
)
async def get_medication_reconciliation(
    encounter_id: uuid.UUID,
    current_user: Annotated[
        TokenClaims, Depends(require_permission("medication", "read"))
    ],
    db: AsyncSession = Depends(get_read_db),
) -> MedicationReconciliationResponse:
    """Retrieve medication reconciliation results for a specific encounter.
    
    This endpoint returns the stored reconciliation results produced by the
    MedicationReconciliationAgent (TASK-004). It queries the medication table
    for all medications associated with the encounter and returns them formatted
    according to the reconciliation schema.
    
    Args:
        encounter_id: UUID of the encounter to retrieve reconciliation for.
        current_user: JWT claims from authenticated user (via RBAC dependency).
        db: Database session (read replica for GET optimization).
    
    Returns:
        MedicationReconciliationResponse with reconciliation metadata and results.
    
    Raises:
        404: Encounter not found in database.
        202: Encounter exists but reconciliation has not completed yet.
        403: User lacks medication:read permission (enforced by RBAC).
    """
    # 1. Verify encounter exists
    stmt = select(Encounter).where(Encounter.id == encounter_id)
    result = await db.execute(stmt)
    encounter = result.scalar_one_or_none()
    
    if not encounter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    # 2. Fetch reconciliation results
    medications = await get_reconciliation_results(encounter_id, db)

    # 3. Check if reconciliation has completed
    completed_at = await get_reconciliation_completed_at(encounter_id, db)

    logger.warning("DEBUG: medications=%s completed_at=%s", len(medications), completed_at)
    
    # Return 202 if encounter exists but reconciliation hasn't run yet
    if not medications and not completed_at:
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Reconciliation in progress",
        )

    # 4. Map ORM records to response schema (must happen within the open session)
    results = [_to_result(m) for m in medications]

    return MedicationReconciliationResponse(
        encounter_id=encounter_id,
        total_medications=len(results),
        reconciliation_completed_at=(
            completed_at.isoformat() if completed_at else None
        ),
        medications=results,
    )


def _to_result(med) -> MedicationReconciliationResult:
    """Map Medication ORM record to API response schema.
    
    Handles field name mapping (drug_name → name) and constructs source flags
    from the ARRAY column. This helper is kept private and co-located with the
    endpoint to avoid circular imports with the schema layer.
    
    Args:
        med: Medication ORM instance from database query.
    
    Returns:
        MedicationReconciliationResult schema instance.
    """
    return MedicationReconciliationResult(
        id=med.id,
        name=med.drug_name,  # ORM field is drug_name, schema expects name
        rxnorm_cui=med.rxnorm_cui,
        reconciliation_category=med.reconciliation_category,
        pre_admit=MedicationListSource.PRE_ADMIT in (med.sources or []),
        inpatient=MedicationListSource.INPATIENT in (med.sources or []),
        discharge=MedicationListSource.DISCHARGE in (med.sources or []),
        flags=med.flags or [],
        dose=(
            f"{med.dose_value} {med.dose_unit}".strip()
            if med.dose_value
            else None
        ),
        route=med.route,
        frequency=med.frequency,
        interaction_severity=med.interaction_severity,
    )
