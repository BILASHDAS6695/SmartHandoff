"""Medication resource router — RBAC-protected endpoints."""
from __future__ import annotations

import logging
import uuid
from typing import Annotated
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims, sub_to_uuid
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db, get_write_db
from app.models.encounter import Encounter
from app.models.medication import (
    Medication,
    MedicationListSource,
)
from app.repositories.medication_repository import (
    get_all_medications,
    get_medication_history_for_patient,
    get_reconciliation_completed_at,
    get_reconciliation_results,
)
from app.services.medication_generator import (
    generate_alerts_for_reconciliation,
    generate_medications_for_encounter,
)
from app.schemas.medication import (
    MedicationAnalysisResponse,
    MedicationCreateRequest,
    MedicationHistoryEncounter,
    MedicationHistoryResponse,
    MedicationReconciliationResponse,
    MedicationReconciliationResult,
    MedicationUpdateRequest,
)
from app.services.medication_analysis_service import MedicationAnalysisService

router = APIRouter(prefix="/medications", tags=["medications"])

# US-030: Encounter-scoped medication reconciliation endpoints
encounters_medications_router = APIRouter(
    prefix="/encounters",
    tags=["medications"],
)


@router.get("")
async def list_medications(
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "list"))],
    db: AsyncSession = Depends(get_read_db),
) -> dict:
    """List all medications — requires medication:list permission.

    Returns every medication record in the system across all encounters,
    mapped to the standard reconciliation result schema.
    """
    medications = await get_all_medications(db)
    return {
        "medications": [_to_result(m) for m in medications],
        "total": len(medications),
        "user": current_user.sub,
    }


@router.get("/{medication_id}")
async def get_medication(
    medication_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "read"))],
) -> dict:
    """Get a single medication — requires medication:read permission."""
    return {"medication_id": str(medication_id), "user": current_user.sub}


@router.post("", response_model=MedicationReconciliationResult, status_code=status.HTTP_201_CREATED)
async def create_medication(
    payload: MedicationCreateRequest,
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "write"))],
    db: AsyncSession = Depends(get_write_db),
) -> Medication:
    """Create a medication on an encounter — requires medication:write permission.

    Used by the physician medication management dialog to add medications
    surfaced by a physician review alert.
    """
    encounter = await db.get(Encounter, payload.encounter_id)
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

    sources: list[MedicationListSource] = []
    if payload.pre_admit:
        sources.append(MedicationListSource.PRE_ADMIT)
    if payload.inpatient:
        sources.append(MedicationListSource.INPATIENT)
    if payload.discharge:
        sources.append(MedicationListSource.DISCHARGE)

    medication = Medication(
        encounter_id=payload.encounter_id,
        drug_name=payload.name,
        rxnorm_cui=payload.rxnorm_cui,
        dose=payload.dose,
        route=payload.route,
        frequency=payload.frequency,
        sources=sources,
        reconciliation_category=payload.reconciliation_category,
        interaction_severity=payload.interaction_severity,
        reconciliation_status="reconciled",
    )
    db.add(medication)
    await db.commit()
    await db.refresh(medication)
    return _to_result(medication)


@router.patch("/{medication_id}", response_model=MedicationReconciliationResult)
async def update_medication(
    medication_id: uuid.UUID,
    payload: MedicationUpdateRequest,
    current_user: Annotated[TokenClaims, Depends(require_permission("medication", "write"))],
    db: AsyncSession = Depends(get_write_db),
) -> Medication:
    """Update a medication — requires medication:write permission.

    Used by the physician medication management dialog to edit medications
    surfaced by a physician review alert.
    """
    medication: Medication | None = await db.get(Medication, medication_id)
    if medication is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication not found")

    if payload.name is not None:
        medication.drug_name = payload.name
    if payload.rxnorm_cui is not None:
        medication.rxnorm_cui = payload.rxnorm_cui
    if payload.dose is not None:
        medication.dose = payload.dose
    if payload.route is not None:
        medication.route = payload.route
    if payload.frequency is not None:
        medication.frequency = payload.frequency
    if payload.reconciliation_category is not None:
        medication.reconciliation_category = payload.reconciliation_category
    if payload.interaction_severity is not None:
        medication.interaction_severity = payload.interaction_severity

    if payload.pre_admit is not None or payload.inpatient is not None or payload.discharge is not None:
        sources: list[MedicationListSource] = []
        if payload.pre_admit if payload.pre_admit is not None else MedicationListSource.PRE_ADMIT in medication.sources:
            sources.append(MedicationListSource.PRE_ADMIT)
        if payload.inpatient if payload.inpatient is not None else MedicationListSource.INPATIENT in medication.sources:
            sources.append(MedicationListSource.INPATIENT)
        if payload.discharge if payload.discharge is not None else MedicationListSource.DISCHARGE in medication.sources:
            sources.append(MedicationListSource.DISCHARGE)
        medication.sources = sources

    db.add(medication)
    await db.commit()
    await db.refresh(medication)
    return _to_result(medication)


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
            detail={
                "status": "pending",
                "message": "Medication reconciliation has not been generated yet.",
            },
        )

    # 4. Map ORM records to response schema (must happen within the open session)
    results = [_to_result(m) for m in medications]

    return MedicationReconciliationResponse(
        encounter_id=encounter_id,
        total_medications=len(results),
        reconciliation_completed_at=(
            completed_at.isoformat() if completed_at else None
        ),
        reconciliation_completed_by=(
            str(encounter.reconciliation_completed_by)
            if encounter.reconciliation_completed_by
            else None
        ),
        medications=results,
    )


@encounters_medications_router.post(
    "/{encounter_id}/medications/reconciliation",
    response_model=MedicationReconciliationResponse,
    summary="Generate medication reconciliation for an encounter",
    description=(
        "Generates and persists a three-way medication reconciliation for the encounter "
        "if one does not already exist. Returns the existing or newly created results."
    ),
    responses={
        200: {"description": "Reconciliation results"},
        403: {"description": "Insufficient permissions"},
        404: {"description": "Encounter not found"},
    },
)
async def generate_medication_reconciliation(
    encounter_id: uuid.UUID,
    current_user: Annotated[
        TokenClaims, Depends(require_permission("medication", "read"))
    ],
    db: AsyncSession = Depends(get_read_db),
) -> MedicationReconciliationResponse:
    """Generate or retrieve medication reconciliation for an encounter.

    If reconciliation results already exist, returns them. Otherwise generates
    realistic medication data based on the encounter's risk tier, persists it,
    and returns the results.

    Args:
        encounter_id: UUID of the encounter to reconcile.
        current_user: JWT claims from authenticated user.
        db: Write database session.

    Returns:
        MedicationReconciliationResponse with reconciliation results.
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

    # 2. Check for existing reconciliation
    existing = await get_reconciliation_results(encounter_id, db)
    completed_at = await get_reconciliation_completed_at(encounter_id, db)

    if existing:
        return MedicationReconciliationResponse(
            encounter_id=encounter_id,
            total_medications=len(existing),
            reconciliation_completed_at=(
                completed_at.isoformat() if completed_at else None
            ),
            reconciliation_completed_by=(
                str(encounter.reconciliation_completed_by)
                if encounter.reconciliation_completed_by
                else None
            ),
            medications=[_to_result(m) for m in existing],
        )

    # 3. Generate realistic medication reconciliation data
    generated = generate_medications_for_encounter(encounter_id, encounter.risk_tier)
    now = datetime.now(timezone.utc)
    for med in generated:
        med.reconciliation_completed_at = now
        db.add(med)

    # 4. Generate pharmacist alerts from reconciliation results
    generate_alerts_for_reconciliation(db, encounter_id, generated)

    await db.commit()

    # 5. Refresh and return
    medications = await get_reconciliation_results(encounter_id, db)
    return MedicationReconciliationResponse(
        encounter_id=encounter_id,
        total_medications=len(medications),
        reconciliation_completed_at=now.isoformat(),
        reconciliation_completed_by=None,
        medications=[_to_result(m) for m in medications],
    )


@encounters_medications_router.post(
    "/{encounter_id}/medications/reconciliation/complete",
    response_model=MedicationReconciliationResponse,
    summary="Mark medication reconciliation as complete",
    description=(
        "Records the current user as having completed medication reconciliation "
        "for the encounter. Idempotent — safe to call multiple times."
    ),
    responses={
        200: {"description": "Reconciliation marked complete"},
        403: {"description": "Insufficient permissions"},
        404: {"description": "Encounter not found"},
    },
)
async def complete_medication_reconciliation(
    encounter_id: uuid.UUID,
    current_user: Annotated[
        TokenClaims, Depends(require_permission("medication", "read"))
    ],
    db: AsyncSession = Depends(get_write_db),
) -> MedicationReconciliationResponse:
    """Mark medication reconciliation as complete for an encounter.

    Args:
        encounter_id: UUID of the encounter.
        current_user: Authenticated user completing the reconciliation.
        db: Write database session.

    Returns:
        MedicationReconciliationResponse with updated completion status.
    """
    stmt = select(Encounter).where(Encounter.id == encounter_id)
    result = await db.execute(stmt)
    encounter = result.scalar_one_or_none()

    if not encounter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    encounter.reconciliation_completed_by = sub_to_uuid(current_user.sub)
    db.add(encounter)
    await db.commit()
    await db.refresh(encounter)

    medications = await get_reconciliation_results(encounter_id, db)
    completed_at = await get_reconciliation_completed_at(encounter_id, db)

    return MedicationReconciliationResponse(
        encounter_id=encounter_id,
        total_medications=len(medications),
        reconciliation_completed_at=(
            completed_at.isoformat() if completed_at else None
        ),
        reconciliation_completed_by=str(sub_to_uuid(current_user.sub)),
        medications=[_to_result(m) for m in medications],
    )


@encounters_medications_router.get(
    "/{encounter_id}/medications/history",
    response_model=MedicationHistoryResponse,
    summary="Medication history across patient's prior encounters",
    description=(
        "Returns medication reconciliation results for the patient's prior encounters, "
        "ordered from most recent to oldest. Excludes the current encounter so the caller "
        "can compare the current medication list against historical snapshots."
    ),
    responses={
        200: {"description": "Medication history retrieved"},
        403: {"description": "Insufficient permissions"},
        404: {"description": "Encounter not found"},
    },
)
async def get_medication_history(
    encounter_id: uuid.UUID,
    current_user: Annotated[
        TokenClaims, Depends(require_permission("medication", "read"))
    ],
    db: AsyncSession = Depends(get_read_db),
) -> MedicationHistoryResponse:
    """Return medication history for the same patient across prior encounters.

    Args:
        encounter_id: UUID of the current encounter being viewed.
        current_user: JWT claims from authenticated user.
        db: Database session (read replica).

    Returns:
        MedicationHistoryResponse containing prior encounter snapshots.

    Raises:
        404: Encounter not found or not linked to a patient.
        403: User lacks medication:read permission.
    """
    stmt = select(Encounter).where(Encounter.id == encounter_id)
    result = await db.execute(stmt)
    encounter = result.scalar_one_or_none()

    if not encounter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    if not encounter.patient_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter is not linked to a patient",
        )

    history = await get_medication_history_for_patient(
        encounter_id,
        encounter.patient_id,
        db,
        limit=10,
    )

    return MedicationHistoryResponse(
        current_encounter_id=encounter_id,
        patient_id=encounter.patient_id,
        history=[
            MedicationHistoryEncounter(
                encounter_id=enc.id,
                status=enc.status,
                created_at=enc.created_at.isoformat() if enc.created_at else None,
                total_medications=len(meds),
                medications=[_to_result(m) for m in meds],
            )
            for enc, meds in history
        ],
    )


@encounters_medications_router.get(
    "/{encounter_id}/medications/analysis",
    response_model=MedicationAnalysisResponse,
    summary="AI medication change analysis and readmission prediction",
    description=(
        "Analyses the encounter's medication reconciliation results and active pharmacist "
        "alerts to produce a realtime readmission-risk prediction, safety score, and "
        "actionable recommendations."
    ),
    responses={
        200: {"description": "Analysis generated"},
        403: {"description": "Insufficient permissions"},
        404: {"description": "Encounter not found"},
    },
)
async def analyze_medications(
    encounter_id: uuid.UUID,
    current_user: Annotated[
        TokenClaims, Depends(require_permission("medication", "read"))
    ],
    db: AsyncSession = Depends(get_read_db),
) -> MedicationAnalysisResponse:
    """Generate AI medication analysis for an encounter.

    Args:
        encounter_id: UUID of the encounter to analyse.
        current_user: JWT claims from authenticated user.
        db: Database session (read replica).

    Returns:
        MedicationAnalysisResponse with prediction and recommendations.

    Raises:
        404: Encounter not found.
        403: User lacks medication:read permission.
    """
    stmt = select(Encounter).where(Encounter.id == encounter_id)
    result = await db.execute(stmt)
    encounter = result.scalar_one_or_none()

    if not encounter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        )

    service = MedicationAnalysisService(db)
    analysis = await service.analyze(encounter_id)

    return MedicationAnalysisResponse(
        encounter_id=encounter_id,
        summary=analysis.summary,
        readmission_risk=analysis.readmission_risk,
        confidence=analysis.confidence,
        safety_score=analysis.safety_score,
        risks=analysis.risks,
        recommendations=analysis.recommendations,
        predicted_issues=analysis.predicted_issues,
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
            else med.dose
        ),
        route=med.route,
        frequency=med.frequency,
        interaction_severity=med.interaction_severity,
    )


