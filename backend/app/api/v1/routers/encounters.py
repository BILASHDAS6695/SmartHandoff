"""Encounter resource router — RBAC-protected endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_write_db
from app.db.encryption import _decrypt
from app.exceptions import EncounterNotFoundError, EncounterStateTransitionError
from app.models.bed import Bed
from app.models.encounter import Encounter, EncounterStatus
from app.models.patient import Patient
from app.schemas.encounter_request import (
    EncounterCreateRequest,
    EncounterUpdateRequest,
    EncounterWriteResponse,
)
from app.api.v1.routers.signalr_hub import get_signalr_broadcaster_optional
from app.services.adt_event_publisher import AdtEventPublisher
from app.services.agent_runner import run_agent_task
from app.services.cancellation_service import CancellationService
from app.services.cancellation_dispatcher import CancellationDispatcher
from app.services.encounter_orchestrator import EncounterOrchestratorService
from app.services.patient_notification_publisher import PatientNotificationPublisher
from app.services.physician_alert_service import create_physician_medication_review_alert
from app.signalr import SignalRHub
from app.signalr.broadcaster import SignalRBroadcaster
from app.signalr.schemas import BedStatusChangedPayload

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/encounters", tags=["encounters"])

# ---------------------------------------------------------------------------
# Cancellation endpoint helpers
# ---------------------------------------------------------------------------

class CancelEventRequest(BaseModel):
    """Request body for ADT cancellation events (A11, A12, A13)."""

    event_type: Literal["A11", "A12", "A13"]


class CancelEventResponse(BaseModel):
    """Response body for ADT cancellation events."""

    encounter_id: uuid.UUID
    event_type: str
    tasks_cancelled: int
    docs_cancelled: int


# Sprint 1 stub — full wiring in EP-002 (SignalR + ADTEventPublisher deps)
def _get_cancellation_service() -> CancellationService:
    return CancellationService()


def _get_cancellation_dispatcher() -> CancellationDispatcher:
    """Return a best-effort CancellationDispatcher with stub hub.

    ADTEventPublisher is provided as ``None`` for Sprint 1; the dispatcher
    logs a warning and skips Pub/Sub when publisher is absent.  Full wiring
    (real publisher + SignalR endpoint) is done in EP-002.
    """
    hub = SignalRHub()
    return CancellationDispatcher(publisher=None, hub=hub)


def _safe_decrypt(ciphertext: str | None) -> str:
    """Decrypt PHI, falling back to plaintext if the value was stored unencrypted."""
    if not ciphertext:
        return ""
    try:
        return _decrypt(ciphertext).decode("utf-8")
    except Exception:
        logger.warning("Failed to decrypt PHI value; treating as plaintext.")
        return ciphertext


@router.get("")
async def list_encounters(
    current_user: Annotated[TokenClaims, Depends(require_permission("encounter", "list"))],
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    unit: str = Query(""),
    search: str = Query(""),
    status: str = Query(""),
    patient_id: uuid.UUID | None = Query(None, description="Filter encounters by patient UUID"),
    mrn: str = Query("", description="Filter encounters by patient MRN (partial match on masked MRN)"),
    db: AsyncSession = Depends(get_write_db),
) -> dict:
    """List encounter-level records — requires encounter:list permission.

    This is the canonical endpoint for encounter/registration rows (one row per
    encounter). Use ``GET /api/v1/patients?unique=true`` for de-duplicated
    patient rows.
    """
    search_term = search.strip().lower()
    mrn_term = mrn.strip().lower()

    def _base_filter(query):
        query = (
            query.join(Patient, Encounter.patient_id == Patient.id)
            .where(Patient.deleted_at.is_(None))
            .where(Encounter.deleted_at.is_(None))
        )
        if unit:
            query = query.where(Encounter.unit == unit)
        if status:
            query = query.where(Encounter.status == status.upper())
        if patient_id:
            query = query.where(Encounter.patient_id == patient_id)
        return query

    count_query = _base_filter(select(func.count(Encounter.id)))
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    data_query = _base_filter(
        select(
            Encounter.id.label("encounter_id"),
            Patient.id.label("patient_id"),
            Patient.first_name,
            Patient.last_name,
            Patient.date_of_birth,
            Patient.mrn_encrypted,
            Encounter.unit.label("current_unit"),
            Encounter.status.label("status"),
            Bed.bed_number.label("room_number"),
            Encounter.risk_tier,
            Encounter.risk_score,
            Encounter.created_at.label("admission_date"),
            Encounter.updated_at.label("updated_at"),
        )
        .outerjoin(Bed, Bed.current_encounter_id == Encounter.id)
    )

    filter_term = search_term or mrn_term
    offset = 0
    if not filter_term:
        offset = (page - 1) * page_size
        data_query = data_query.offset(offset).limit(page_size)
    data_query = data_query.order_by(Encounter.updated_at.desc())

    result = await db.execute(data_query)
    rows = result.all()

    encounter_items = []
    for row in rows:
        first_name = _safe_decrypt(row.first_name)
        last_name = _safe_decrypt(row.last_name)
        mrn_plain = _safe_decrypt(row.mrn_encrypted)
        mrn_masked = f"****{mrn_plain[-4:]}" if mrn_plain and len(mrn_plain) >= 4 else "****"

        encounter_items.append({
            "encounter_id": str(row.encounter_id),
            "patient_id": str(row.patient_id),
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": _safe_decrypt(row.date_of_birth),
            "current_unit": row.current_unit or "",
            "room_number": row.room_number or "",
            "mrn_masked": mrn_masked,
            "risk_tier": row.risk_tier or "UNKNOWN",
            "risk_score": row.risk_score,
            "admission_date": row.admission_date.isoformat() if row.admission_date else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            "status": row.status or "",
        })

    if search_term or mrn_term:
        filtered_items = []
        for item in encounter_items:
            full_name = f"{item.get('first_name', '')} {item.get('last_name', '')}".lower()
            mrn_display = item.get("mrn_masked", "").lower()
            match = True
            if search_term and search_term not in full_name and search_term not in mrn_display:
                match = False
            if mrn_term and mrn_term not in mrn_display:
                match = False
            if match:
                filtered_items.append(item)
        total = len(filtered_items)
        offset = (page - 1) * page_size
        encounter_items = filtered_items[offset:offset + page_size]

    return {
        "items": encounter_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{encounter_id}")
async def get_encounter(
    encounter_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("encounter", "read"))],
) -> dict:
    """Get a single encounter — requires encounter:read permission."""
    return {"encounter_id": str(encounter_id), "user": current_user.sub}


@router.post("", response_model=EncounterWriteResponse)
async def create_encounter(
    body: EncounterCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[TokenClaims, Depends(require_permission("encounter", "write"))],
    db: AsyncSession = Depends(get_write_db),
    broadcaster: SignalRBroadcaster | None = Depends(get_signalr_broadcaster_optional),
) -> Encounter:
    """Create an encounter — requires encounter:write permission.

    Also records an ADT event, broadcasts it to the unit's SignalR group,
    and creates the initial set of agent tasks for the ADT event type.
    """
    patient = await db.get(Patient, body.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Prevent duplicate active encounters for the same patient. A patient may only
    # have one active (non-discharged) encounter at a time; discharges close the
    # active episode before a new one can be created.
    active_statuses = [
        EncounterStatus.REGISTERED.value,
        EncounterStatus.PRE_ADMISSION.value,
        EncounterStatus.ADMITTED.value,
        EncounterStatus.TRANSFERRED.value,
    ]
    active_check = await db.execute(
        select(func.count(Encounter.id))
        .where(Encounter.patient_id == body.patient_id)
        .where(Encounter.status.in_(active_statuses))
        .where(Encounter.deleted_at.is_(None))
    )
    active_count = active_check.scalar() or 0
    if active_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "This patient already has an active encounter. "
                "Discharge or cancel the existing encounter before creating a new one."
            ),
        )

    encounter = Encounter(
        patient_id=body.patient_id,
        status=body.status.value,
        unit=body.unit,
        risk_tier=body.risk_tier,
    )
    db.add(encounter)
    await db.flush([encounter])

    publisher = AdtEventPublisher()
    await publisher.publish_for_encounter(db, encounter, patient)

    await db.commit()
    await db.refresh(encounter)

    # Create agent tasks driven by the ADT event type (or encounter status fallback).
    orchestrator = EncounterOrchestratorService(broadcaster=broadcaster)
    tasks = await orchestrator.create_tasks_for_adt_event(
        db=db,
        encounter=encounter,
        event_type=body.event_type.value if body.event_type else None,
    )

    # Run each new agent task asynchronously after the response is sent.
    for task in tasks:
        background_tasks.add_task(run_agent_task, task.id, broadcaster)

    # Notify patient of admission (US-064)
    if encounter.status == EncounterStatus.ADMITTED.value and not patient.notification_opt_out:
        notifier = PatientNotificationPublisher()
        await notifier.send_both(
            phone=patient.phone,
            email=patient.email,
            subject="You've been admitted",
            body=(
                f"Hi {patient.first_name or 'there'}, you've been admitted to "
                f"{encounter.unit or 'the hospital'}. We'll send updates through SmartHandoff."
            ),
            patient_id=str(patient.id),
        )

    return encounter


@router.patch("/{encounter_id}", response_model=EncounterWriteResponse)
async def update_encounter(
    encounter_id: uuid.UUID,
    body: EncounterUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[TokenClaims, Depends(require_permission("encounter", "write"))],
    db: AsyncSession = Depends(get_write_db),
    broadcaster: SignalRBroadcaster | None = Depends(get_signalr_broadcaster_optional),
) -> Encounter:
    """Update an encounter — requires encounter:write permission.

    Records an ADT event and broadcasts it when the status or unit changes.
    Also creates any additional agent tasks implied by the new encounter state.
    """
    encounter = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(status_code=404, detail="Encounter not found")

    patient = await db.get(Patient, encounter.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    status_changed = body.status is not None and body.status.value != encounter.status
    unit_changed = body.unit is not None and body.unit != encounter.unit

    if body.status is not None:
        encounter.transition_to(EncounterStatus(body.status.value))
    if body.unit is not None:
        encounter.unit = body.unit
    if body.risk_tier is not None:
        encounter.risk_tier = body.risk_tier

    discharged = False
    released_bed_id: str | None = None
    if status_changed or unit_changed:
        publisher = AdtEventPublisher()
        await publisher.publish_for_encounter(db, encounter, patient)
        discharged = (
            status_changed and encounter.status == EncounterStatus.DISCHARGED.value
        )

    # Whenever the encounter status or unit changes, physicians must review
    # medications for the updated encounter state.
    if status_changed or unit_changed:
        try:
            await create_physician_medication_review_alert(
                db=db,
                encounter=encounter,
                broadcaster=broadcaster,
            )
        except Exception as exc:
            logger.warning(
                "Failed to auto-create physician alert for encounter update %s: %s",
                encounter.id,
                exc,
            )

    # If the patient is being discharged, release the occupied bed so
    # housekeeping can clean it and the bed board reflects availability.
    if discharged:
        bed_result = await db.execute(
            select(Bed).where(Bed.current_encounter_id == encounter.id)
        )
        occupied_bed = bed_result.scalar_one_or_none()
        if occupied_bed is not None:
            occupied_bed.status = "cleaning"
            occupied_bed.current_encounter_id = None
            released_bed_id = str(occupied_bed.id)
            db.add(occupied_bed)
            logger.info(
                "Bed %s released for discharged encounter %s",
                occupied_bed.id,
                encounter.id,
            )

    await db.commit()
    await db.refresh(encounter)

    # Broadcast bed status change immediately so the bed board refreshes.
    if released_bed_id and occupied_bed is not None and broadcaster is not None:
        try:
            await broadcaster.broadcast_bed_status_changed(
                BedStatusChangedPayload(
                    bed_id=released_bed_id,
                    bed_number=occupied_bed.bed_number,
                    patient_unit=occupied_bed.unit or encounter.unit or "unknown",
                    status="CLEANING",
                    encounter_id=None,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception as exc:
            logger.warning(
                "Failed to broadcast bed status change for discharged encounter %s: %s",
                encounter.id,
                exc,
            )

    # Create/update agent tasks when the encounter changed.
    if status_changed or unit_changed:
        orchestrator = EncounterOrchestratorService(broadcaster=broadcaster)
        tasks = await orchestrator.create_tasks_for_adt_event(
            db=db,
            encounter=encounter,
            event_type=body.event_type.value if body.event_type else None,
        )

        # Run newly created agent tasks asynchronously after the response is sent.
        for task in tasks:
            background_tasks.add_task(run_agent_task, task.id, broadcaster)

    # Notify patient of discharge (US-064)
    if discharged and not patient.notification_opt_out:
        notifier = PatientNotificationPublisher()
        await notifier.send_both(
            phone=patient.phone,
            email=patient.email,
            subject="You've been discharged",
            body=(
                f"Hi {patient.first_name or 'there'}, you've been discharged. "
                "Your care team will follow up via SmartHandoff."
            ),
            patient_id=str(patient.id),
        )

    return encounter


@router.post(
    "/{encounter_id}/cancel-event",
    response_model=CancelEventResponse,
    status_code=200,
    summary="Process ADT cancellation event (A11 / A12 / A13)",
    description=(
        "Applies an HL7 ADT cancellation event to the encounter state machine. "
        "Cancels queued agent tasks and (for A11/A13) soft-cancels open documents. "
        "Post-commit: publishes WORKFLOW_CANCELLED to Pub/Sub and broadcasts an "
        "ENCOUNTER_CANCELLED SignalR notification to the care team dashboard."
    ),
)
async def cancel_encounter_event(
    encounter_id: uuid.UUID,
    body: CancelEventRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_write_db),
    svc: CancellationService = Depends(_get_cancellation_service),
    dispatcher: CancellationDispatcher = Depends(_get_cancellation_dispatcher),
) -> CancelEventResponse:
    """Apply ADT cancellation event to encounter state machine.

    Requires encounter:write permission (enforced at API gateway level).

    Args:
        encounter_id: UUID of the target encounter.
        body:         ``{"event_type": "A11"|"A12"|"A13"}``

    Returns:
        ``CancelEventResponse`` with counts of cancelled tasks and documents.

    Raises:
        404: Encounter not found.
        409: State transition is not allowed from the current encounter status.
    """
    try:
        async with db.begin():
            match body.event_type:
                case "A11":
                    result = await svc.handle_cancel_admit(
                        encounter_id=encounter_id, db=db
                    )
                case "A12":
                    result = await svc.handle_cancel_transfer(
                        encounter_id=encounter_id, db=db
                    )
                case "A13":
                    result = await svc.handle_cancel_discharge(
                        encounter_id=encounter_id, db=db
                    )
    except EncounterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EncounterStateTransitionError:
        # EncounterStateTransitionError is already an HTTPException (409)
        raise

    # Dispatch post-commit side effects (Pub/Sub + SignalR) as background task.
    # Failures are logged but do not affect the HTTP response (TR-015).
    background_tasks.add_task(dispatcher.dispatch_post_commit, result)

    return CancelEventResponse(
        encounter_id=result.encounter_id,
        event_type=result.event_type,
        tasks_cancelled=result.tasks_cancelled,
        docs_cancelled=result.docs_cancelled,
    )
