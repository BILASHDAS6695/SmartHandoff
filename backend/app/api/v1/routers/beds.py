"""Bed board REST API router.

Endpoints:
    GET  /api/v1/beds                       — Filtered bed board (read replica, mv_bed_board)
    GET  /api/v1/beds/suggestions           — Pending bed-management suggestions
    POST /api/v1/beds/suggestions/{id}/assign  — Bed manager approves a suggestion
    POST /api/v1/beds/suggestions/{id}/decline — Bed manager declines a suggestion
    PATCH /api/v1/beds/{id}/status          — Manual bed status override (BedManager role)

Design refs:
    US-035 AC Scenario 3    — GET filter; p95 <500ms
    US-035 DoD              — PATCH requires BedManager role
    design.md §3.3          — FastAPI API layer structure
    design.md §8.3          — RBAC: BedManager and Admin only for bed board
    ADR-006                 — CQRS: reads to replica, writes to primary
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bed_management.boarding_resolver import resolve_boarding_alert
from app.agents.bed_management.refresh_service import BedBoardRefreshService
from app.agents.bed_management.schemas import BedStatus
from app.api.v1.routers.signalr_hub import get_signalr_broadcaster_optional
from app.core.auth.jwt import TokenClaims, sub_to_uuid
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db, get_write_db
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.bed import Bed
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.schemas.agent_task import AgentTaskResponse
from app.services.audit_service import write_audit_log
from app.services.medication_analysis_service import MedicationAnalysisService
from app.services.task_status_service import TaskStatusTransitionService
from app.signalr.broadcaster import SignalRBroadcaster
from app.signalr.schemas import BedStatusChangedPayload, TaskUpdatedPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/beds", tags=["beds"])


# ───────────────────────────────────────────────────────────────────────────
# Response / request schemas
# ───────────────────────────────────────────────────────────────────────────


class BedBoardEntry(BaseModel):
    """Single bed entry returned by GET /api/v1/beds.

    Sourced from mv_bed_board (read replica) — no PHI included.
    """

    bed_id: str
    unit: str
    room: str
    bed_number: str
    bed_type: str
    status: BedStatus
    isolation_required: bool
    gender_designation: str
    predicted_discharge_time: str | None = None  # populated by US-036


class BedStatusPatchRequest(BaseModel):
    """Request body for PATCH /api/v1/beds/{id}/status."""

    status: BedStatus = Field(..., description="Target bed status")
    reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Reason for manual override (audit log)",
    )
    encounter_id: uuid.UUID | None = Field(
        None,
        description="Encounter ID for bed assignment (required when status=RESERVED)",
    )


class BedStatusPatchResponse(BaseModel):
    """Response for PATCH /api/v1/beds/{id}/status."""

    bed_id: str
    previous_status: BedStatus
    new_status: BedStatus


class BedSuggestionEntry(BaseModel):
    """Single pending bed suggestion returned to the bed board."""

    task_id: str
    encounter_id: str
    patient_name: str
    current_unit: str | None
    acuity: str
    minutes_waiting: int | None
    best_bed_id: str
    best_bed_number: str
    best_bed_unit: str
    suggestions: list[dict]
    created_at: datetime


class AssignSuggestionRequest(BaseModel):
    """Request body for assigning a suggested bed."""

    bed_id: uuid.UUID = Field(..., description="UUID of the bed to assign")
    reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Reason for the assignment (audit log)",
    )
    isolation_confirmed: bool = Field(
        default=False,
        description="Bed manager confirms isolation requirements are met",
    )
    notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional free-text notes for the assignment",
    )


class AssignSuggestionResponse(BaseModel):
    """Response for assigning a suggested bed."""

    task_id: str
    encounter_id: str
    bed_id: str
    bed_number: str
    unit: str
    status: BedStatus
    previous_status: BedStatus


class DeclineSuggestionRequest(BaseModel):
    """Request body for declining a suggested bed."""

    reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Reason for declining the suggestion (audit log)",
    )


class DeclineSuggestionResponse(BaseModel):
    """Response for declining a suggested bed."""

    task_id: str
    encounter_id: str
    status: str


class BedOccupant(BaseModel):
    """Patient/encounter details for an occupied bed."""

    encounter_id: str
    patient_id: str
    first_name: str
    last_name: str
    date_of_birth: str | None = None
    mrn_masked: str
    encounter_status: str
    unit: str | None = None
    risk_tier: str
    admission_date: datetime | None = None


class WaitingPatientForBed(BaseModel):
    """A patient waiting for bed allocation from a pending suggestion."""

    task_id: str
    encounter_id: str
    patient_name: str
    current_unit: str | None = None
    acuity: str
    minutes_waiting: int | None = None
    best_bed_id: str
    best_bed_number: str
    best_bed_unit: str


class MedicationAnalysisSnapshot(BaseModel):
    """AI medication analysis snapshot embedded in bed details."""

    readmission_risk: str
    confidence: str
    safety_score: int
    summary: str
    risks: list[str] = []
    recommendations: list[str] = []
    predicted_issues: list[str] = []


class BedDetailResponse(BaseModel):
    """Response for GET /api/v1/beds/{bed_id}/details."""

    bed_id: str
    bed_number: str
    unit: str
    room: str | None = None
    bed_type: str
    status: BedStatus
    isolation_required: bool
    gender_designation: str
    predicted_discharge_time: str | None = None
    occupant: BedOccupant | None = None
    waiting_patients: list[WaitingPatientForBed] = []
    medication_analysis: MedicationAnalysisSnapshot | None = None


# ───────────────────────────────────────────────────────────────────────────
# GET /api/v1/beds
# ───────────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[BedBoardEntry],
    summary="Retrieve filtered bed board entries",
    description=(
        "Returns bed records from mv_bed_board (read replica). "
        "Filter by unit, status, and/or bed_type. "
        "Requires bed:list permission (Physician, Nurse, BedManager, or Admin role)."
    ),
)
async def list_beds(
    unit: Annotated[
        str | None, Query(description="Filter by unit code, e.g. '3A'")
    ] = None,
    status: Annotated[
        BedStatus | None, Query(description="Filter by bed status")
    ] = None,
    bed_type: Annotated[
        str | None, Query(description="Filter by bed type, e.g. 'ICU'")
    ] = None,
    current_user: TokenClaims = Depends(require_permission("bed", "list")),
    read_db: AsyncSession = Depends(get_read_db),
) -> list[BedBoardEntry]:
    """Query mv_bed_board with optional filters; routes to read replica.
    
    Performance: p95 <500ms (US-035 AC Scenario 3, TR-001).
    """
    # Build dynamic SQL query with filters
    query = "SELECT * FROM mv_bed_board WHERE 1=1"
    params: dict = {}

    if unit is not None:
        query += " AND unit = :unit"
        params["unit"] = unit
    if status is not None:
        query += " AND status = :status"
        params["status"] = status.value.lower()
    if bed_type is not None:
        query += " AND bed_type = :bed_type"
        params["bed_type"] = bed_type

    result = await read_db.execute(text(query), params)
    rows = result.mappings().all()

    return [
        BedBoardEntry(
            bed_id=str(row["bed_id"]),
            unit=row["unit"],
            room=row["room"],
            bed_number=row["bed_number"],
            bed_type=row["bed_type"],
            status=BedStatus(row["status"]),
            isolation_required=row["isolation_required"],
            gender_designation=row["gender_designation"],
            predicted_discharge_time=(
                row["predicted_discharge_time"].isoformat()
                if row.get("predicted_discharge_time")
                else None
            ),
        )
        for row in rows
    ]


# ───────────────────────────────────────────────────────────────────────────
# GET /api/v1/beds/{bed_id}/details
# ───────────────────────────────────────────────────────────────────────────


@router.get(
    "/{bed_id}/details",
    response_model=BedDetailResponse,
    summary="Detailed bed information with occupant and waiting patients",
    description=(
        "Returns a single bed's details. For occupied beds, includes the "
        "current patient/encounter summary. For all beds, includes the list "
        "of patients waiting for bed allocation from pending suggestions. "
        "bed_id may be the bed UUID or the human-readable bed_number. "
        "Requires bed:read permission."
    ),
)
async def get_bed_details(
    bed_id: str,
    current_user: Annotated[TokenClaims, Depends(require_permission("bed", "read"))],
    read_db: AsyncSession = Depends(get_read_db),
) -> BedDetailResponse:
    """Fetch bed details, occupant, and waiting patients for assignment decisions."""
    # Accept either UUID or bed_number for caller convenience.
    bed: Bed | None = None
    try:
        bed_uuid = uuid.UUID(bed_id)
        result = await read_db.execute(select(Bed).where(Bed.id == bed_uuid))
        bed = result.scalar_one_or_none()
    except ValueError:
        bed = None

    if bed is None:
        result = await read_db.execute(select(Bed).where(Bed.bed_number == bed_id))
        bed = result.scalar_one_or_none()

    if bed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bed {bed_id} not found",
        )

    occupant: BedOccupant | None = None
    try:
        bed_status = BedStatus(bed.status)
    except ValueError:
        bed_status = BedStatus.AVAILABLE
    if bed_status == BedStatus.OCCUPIED and bed.current_encounter_id:
        occupant_result = await read_db.execute(
            select(Encounter, Patient, Bed)
            .join(Patient, Encounter.patient_id == Patient.id)
            .outerjoin(Bed, Bed.current_encounter_id == Encounter.id)
            .where(Encounter.id == bed.current_encounter_id)
            .where(Patient.deleted_at.is_(None))
            .where(Encounter.deleted_at.is_(None))
        )
        row = occupant_result.one_or_none()
        if row:
            encounter, patient, _ = row
            mrn = patient.mrn_encrypted or ""
            occupant = BedOccupant(
                encounter_id=str(encounter.id),
                patient_id=str(patient.id),
                first_name=patient.first_name or "",
                last_name=patient.last_name or "",
                date_of_birth=patient.date_of_birth or None,
                mrn_masked=f"****{mrn[-4:]}" if mrn and len(str(mrn)) >= 4 else "****",
                encounter_status=encounter.status,
                unit=encounter.unit,
                risk_tier=encounter.risk_tier,
                admission_date=encounter.created_at,
            )

    waiting: list[WaitingPatientForBed] = []
    task_result = await read_db.execute(
        select(AgentTask, Encounter, Patient)
        .join(Encounter, AgentTask.encounter_id == Encounter.id)
        .join(Patient, Encounter.patient_id == Patient.id)
        .where(AgentTask.agent_type == "bed_management")
        .where(AgentTask.status == AgentTaskStatus.PENDING_APPROVAL.value)
        .order_by(AgentTask.created_at.asc())
    )
    for task, encounter, patient in task_result.all():
        output = task.output or {}
        best = (output.get("suggestions") or [{}])[0]
        patient_name = output.get("patient_name") or (
            f"{patient.first_name or ''} {patient.last_name or ''}".strip()
            or "Unknown"
        )
        waiting.append(
            WaitingPatientForBed(
                task_id=str(task.id),
                encounter_id=str(task.encounter_id),
                patient_name=patient_name,
                current_unit=encounter.unit,
                acuity=output.get("acuity") or "Unknown",
                minutes_waiting=output.get("minutes_waiting"),
                best_bed_id=output.get("best_bed_id") or best.get("bed_id", ""),
                best_bed_number=output.get("best_bed_number")
                or best.get("bed_number", ""),
                best_bed_unit=output.get("best_bed_unit") or best.get("unit", ""),
            )
        )

    medication_analysis: MedicationAnalysisSnapshot | None = None
    if occupant is not None:
        try:
            analysis_service = MedicationAnalysisService(read_db)
            analysis = await analysis_service.analyze(uuid.UUID(occupant.encounter_id))
            medication_analysis = MedicationAnalysisSnapshot(
                readmission_risk=analysis.readmission_risk,
                confidence=analysis.confidence,
                safety_score=analysis.safety_score,
                summary=analysis.summary,
                risks=analysis.risks,
                recommendations=analysis.recommendations,
                predicted_issues=analysis.predicted_issues,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Medication analysis failed for encounter %s: %s",
                occupant.encounter_id,
                exc,
            )

    return BedDetailResponse(
        bed_id=str(bed.id),
        bed_number=bed.bed_number,
        unit=bed.unit,
        room=getattr(bed, "room", None),
        bed_type=getattr(bed, "bed_type", "standard"),
        status=bed_status,
        isolation_required=getattr(bed, "isolation_required", False),
        gender_designation=getattr(bed, "gender_designation", "Unknown"),
        predicted_discharge_time=(
            bed.predicted_discharge_at.isoformat() if bed.predicted_discharge_at else None
        ),
        occupant=occupant,
        waiting_patients=waiting,
        medication_analysis=medication_analysis,
    )


# ───────────────────────────────────────────────────────────────────────────
# GET /api/v1/beds/suggestions
# ───────────────────────────────────────────────────────────────────────────


@router.get(
    "/suggestions",
    response_model=list[BedSuggestionEntry],
    summary="List pending bed-management suggestions",
    description=(
        "Returns bed-management AgentTasks in PENDING_APPROVAL status with "
        "ranked bed suggestions. Requires bed:read permission."
    ),
)
async def list_bed_suggestions(
    current_user: Annotated[TokenClaims, Depends(require_permission("bed", "read"))],
    read_db: AsyncSession = Depends(get_read_db),
) -> list[BedSuggestionEntry]:
    """List pending bed suggestions for the bed manager dashboard.

    Queries agent_task for bed_management tasks in PENDING_APPROVAL status,
    joins encounter + patient for display names, and returns the suggestion
    payload stored by the Bed Management Agent.
    """
    stmt = (
        select(AgentTask, Encounter, Patient)
        .join(Encounter, AgentTask.encounter_id == Encounter.id)
        .join(Patient, Encounter.patient_id == Patient.id)
        .where(AgentTask.agent_type == "bed_management")
        .where(AgentTask.status == AgentTaskStatus.PENDING_APPROVAL.value)
        .order_by(AgentTask.created_at.asc())
    )
    result = await read_db.execute(stmt)
    rows = result.all()

    suggestions: list[BedSuggestionEntry] = []
    for task, encounter, patient in rows:
        output = task.output or {}
        if not output.get("suggested"):
            continue

        patient_name = output.get("patient_name") or (
            f"{patient.first_name or ''} {patient.last_name or ''}".strip()
            or "Unknown"
        )
        best = (output.get("suggestions") or [{}])[0]
        suggestions.append(
            BedSuggestionEntry(
                task_id=str(task.id),
                encounter_id=str(task.encounter_id),
                patient_name=patient_name,
                current_unit=encounter.unit,
                acuity=output.get("acuity") or "Unknown",
                minutes_waiting=output.get("minutes_waiting"),
                best_bed_id=output.get("best_bed_id") or best.get("bed_id", ""),
                best_bed_number=output.get("best_bed_number")
                or best.get("bed_number", ""),
                best_bed_unit=output.get("best_bed_unit") or best.get("unit", ""),
                suggestions=output.get("suggestions") or [],
                created_at=task.created_at or datetime.now(UTC),
            )
        )

    return suggestions


# ───────────────────────────────────────────────────────────────────────────
# POST /api/v1/beds/suggestions/{task_id}/assign
# ───────────────────────────────────────────────────────────────────────────


@router.post(
    "/suggestions/{task_id}/assign",
    response_model=AssignSuggestionResponse,
    summary="Assign a suggested bed to an encounter",
    description=(
        "Bed manager approves a bed suggestion. Marks the bed RESERVED, "
        "updates the encounter, resolves any active boarding alert, marks "
        "the agent task COMPLETED, and broadcasts real-time updates."
    ),
)
async def assign_suggested_bed(
    task_id: uuid.UUID,
    body: AssignSuggestionRequest,
    current_user: Annotated[TokenClaims, Depends(require_permission("bed", "write"))],
    write_db: AsyncSession = Depends(get_write_db),
    broadcaster: SignalRBroadcaster | None = Depends(get_signalr_broadcaster_optional),
) -> AssignSuggestionResponse:
    """Approve a bed suggestion and complete the assignment workflow."""
    result = await write_db.execute(
        select(AgentTask)
        .where(AgentTask.id == task_id)
        .where(AgentTask.agent_type == "bed_management")
    )
    task: AgentTask | None = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bed suggestion task {task_id} not found",
        )
    if task.status != AgentTaskStatus.PENDING_APPROVAL.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is not awaiting approval (status={task.status})",
        )

    output = task.output or {}
    suggestions = output.get("suggestions") or []
    suggested_bed_ids = {s.get("bed_id") for s in suggestions if s.get("bed_id")}
    if str(body.bed_id) not in suggested_bed_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected bed is not one of the agent's suggestions",
        )

    bed_result = await write_db.execute(select(Bed).where(Bed.id == body.bed_id))
    bed: Bed | None = bed_result.scalar_one_or_none()
    if bed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bed {body.bed_id} not found",
        )
    if bed.status not in {"available", "cleaning", "vacant"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Bed {bed.bed_number} is no longer available (status={bed.status})",
        )

    encounter_result = await write_db.execute(
        select(Encounter).where(Encounter.id == task.encounter_id)
    )
    encounter: Encounter | None = encounter_result.scalar_one_or_none()
    if encounter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Encounter {task.encounter_id} not found",
        )

    previous_status = BedStatus(bed.status)
    bed.status = BedStatus.RESERVED.value.lower()
    bed.current_encounter_id = task.encounter_id
    if encounter.unit is None:
        encounter.unit = bed.unit

    await write_db.flush()

    # Resolve any active ED boarding alert for this encounter.
    await resolve_boarding_alert(str(task.encounter_id), session=write_db)

    # Update task output with assignment details and mark COMPLETED.
    task.output = {
        **output,
        "action": "bed_assignment",
        "assigned": True,
        "assigned_bed_id": str(bed.id),
        "bed_number": bed.bed_number,
        "unit": bed.unit,
        "room": getattr(bed, "room", None) or getattr(bed, "ward", None) or bed.unit,
        "previous_status": previous_status.value,
        "new_status": bed.status,
        "assigned_by": current_user.sub,
        "assigned_reason": body.reason,
        "isolation_confirmed": body.isolation_confirmed,
        "notes": body.notes,
    }

    transition = TaskStatusTransitionService(broadcaster=broadcaster)
    await transition.transition(write_db, task, AgentTaskStatus.COMPLETED)

    # Audit log the assignment decision.
    try:
        performer_id = sub_to_uuid(current_user.sub)
    except ValueError:
        performer_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    await write_audit_log(
        db=write_db,
        action="BED_SUGGESTION_ASSIGNED",
        resource_type="Bed",
        resource_id=bed.id,
        performed_by=performer_id,
        metadata={
            "task_id": str(task_id),
            "encounter_id": str(task.encounter_id),
            "previous_status": previous_status.value,
            "new_status": bed.status,
            "reason": body.reason,
            "isolation_confirmed": body.isolation_confirmed,
        },
    )

    # Broadcast bed status change so the board refreshes live.
    if broadcaster is not None:
        await broadcaster.broadcast_bed_status_changed(
            BedStatusChangedPayload(
                bed_id=str(bed.id),
                bed_number=bed.bed_number,
                patient_unit=bed.unit,
                status=bed.status.upper(),
                encounter_id=str(task.encounter_id),
            )
        )

    return AssignSuggestionResponse(
        task_id=str(task.id),
        encounter_id=str(task.encounter_id),
        bed_id=str(bed.id),
        bed_number=bed.bed_number,
        unit=bed.unit,
        status=BedStatus(bed.status),
        previous_status=previous_status,
    )


# ───────────────────────────────────────────────────────────────────────────
# POST /api/v1/beds/suggestions/{task_id}/decline
# ───────────────────────────────────────────────────────────────────────────


@router.post(
    "/suggestions/{task_id}/decline",
    response_model=DeclineSuggestionResponse,
    summary="Decline a suggested bed",
    description=(
        "Bed manager declines a bed suggestion. Marks the agent task CANCELLED, "
        "records the decline reason, and broadcasts the status update."
    ),
)
async def decline_suggested_bed(
    task_id: uuid.UUID,
    body: DeclineSuggestionRequest,
    current_user: Annotated[TokenClaims, Depends(require_permission("bed", "write"))],
    write_db: AsyncSession = Depends(get_write_db),
    broadcaster: SignalRBroadcaster | None = Depends(get_signalr_broadcaster_optional),
) -> DeclineSuggestionResponse:
    """Decline a bed suggestion and record the reason."""
    result = await write_db.execute(
        select(AgentTask)
        .where(AgentTask.id == task_id)
        .where(AgentTask.agent_type == "bed_management")
    )
    task: AgentTask | None = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bed suggestion task {task_id} not found",
        )
    if task.status != AgentTaskStatus.PENDING_APPROVAL.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Task {task_id} is not awaiting approval (status={task.status})",
        )

    output = task.output or {}
    task.output = {
        **output,
        "action": "bed_suggestion_declined",
        "assigned": False,
        "declined_by": current_user.sub,
        "decline_reason": body.reason,
    }

    transition = TaskStatusTransitionService(broadcaster=broadcaster)
    await transition.transition(write_db, task, AgentTaskStatus.CANCELLED)

    try:
        performer_id = sub_to_uuid(current_user.sub)
    except ValueError:
        performer_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    await write_audit_log(
        db=write_db,
        action="BED_SUGGESTION_DECLINED",
        resource_type="AgentTask",
        resource_id=task.id,
        performed_by=performer_id,
        metadata={
            "task_id": str(task_id),
            "encounter_id": str(task.encounter_id),
            "reason": body.reason,
        },
    )

    return DeclineSuggestionResponse(
        task_id=str(task.id),
        encounter_id=str(task.encounter_id),
        status=task.status,
    )


# ───────────────────────────────────────────────────────────────────────────
# PATCH /api/v1/beds/{id}/status
# ───────────────────────────────────────────────────────────────────────────


@router.patch(
    "/{bed_id}/status",
    response_model=BedStatusPatchResponse,
    summary="Manual bed status override",
    description=(
        "Allows a BedManager to manually set a bed's status "
        "(e.g. MAINTENANCE, RESERVED). "
        "Restricted to BedManager and Admin roles. Triggers mv_bed_board refresh."
    ),
)
async def patch_bed_status(
    bed_id: uuid.UUID,
    body: BedStatusPatchRequest,
    current_user: TokenClaims = Depends(require_permission("bed", "write")),
    write_db: AsyncSession = Depends(get_write_db),
) -> BedStatusPatchResponse:
    """Override bed status; write to primary; trigger mv_bed_board refresh.
    
    Access control: bed:write permission (BedManager and Admin roles only).
    Audit logging: All status overrides are logged to audit_log table (HIPAA).
    """
    # Load current bed status from primary for accurate previous_status
    result = await write_db.execute(select(Bed).where(Bed.id == bed_id))
    bed = result.scalar_one_or_none()
    if bed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bed {bed_id} not found",
        )

    previous_status = BedStatus(bed.status)

    # Update bed status in primary DB (store lowercase to match bed.status schema)
    await write_db.execute(
        update(Bed).where(Bed.id == bed_id).values(status=body.status.value.lower())
    )

    # US-038: Resolve boarding alert when bed is RESERVED
    if body.status == BedStatus.RESERVED and body.encounter_id:
        await resolve_boarding_alert(
            encounter_id=str(body.encounter_id),
            session=write_db,
        )

    # Write audit log entry (HIPAA compliance — all PHI access and mutations)
    try:
        performer_id = uuid.UUID(current_user.sub)
    except ValueError:
        performer_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    await write_audit_log(
        db=write_db,
        action="BED_STATUS_OVERRIDE",
        resource_type="Bed",
        resource_id=bed_id,
        performed_by=performer_id,
        metadata={
            "previous": previous_status.value,
            "new": body.status.value,
            "reason": body.reason,
        },
    )

    # Commit all changes (bed update + audit log)
    await write_db.commit()

    logger.info(
        "Manual bed status override bed_id=%s %s → %s user_id=%s",
        bed_id,
        previous_status,
        body.status,
        current_user.sub,
    )

    # Non-blocking mv_bed_board refresh (fire-and-forget)
    # Note: Requires write session factory to be injected (pending integration)
    # refresh_service = BedBoardRefreshService(write_session_factory=get_write_db)
    # await refresh_service.refresh_async()

    return BedStatusPatchResponse(
        bed_id=str(bed_id),
        previous_status=previous_status,
        new_status=body.status,
    )

