"""Encounter resource router — RBAC-protected endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_write_db
from app.exceptions import EncounterNotFoundError, EncounterStateTransitionError
from app.models.encounter import Encounter, EncounterStatus
from app.models.patient import Patient
from app.schemas.encounter_request import (
    EncounterCreateRequest,
    EncounterUpdateRequest,
    EncounterWriteResponse,
)
from app.services.adt_event_publisher import AdtEventPublisher
from app.services.cancellation_service import CancellationService
from app.services.cancellation_dispatcher import CancellationDispatcher
from app.signalr import SignalRHub

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


@router.get("")
async def list_encounters(
    current_user: Annotated[TokenClaims, Depends(require_permission("encounter", "list"))],
) -> dict:
    """List encounters — requires encounter:list permission."""
    return {"encounters": [], "user": current_user.sub}


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
    current_user: Annotated[TokenClaims, Depends(require_permission("encounter", "write"))],
    db: AsyncSession = Depends(get_write_db),
) -> Encounter:
    """Create an encounter — requires encounter:write permission.

    Also records an ADT event and broadcasts it to the unit's SignalR group.
    """
    patient = await db.get(Patient, body.patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

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
    return encounter


@router.patch("/{encounter_id}", response_model=EncounterWriteResponse)
async def update_encounter(
    encounter_id: uuid.UUID,
    body: EncounterUpdateRequest,
    current_user: Annotated[TokenClaims, Depends(require_permission("encounter", "write"))],
    db: AsyncSession = Depends(get_write_db),
) -> Encounter:
    """Update an encounter — requires encounter:write permission.

    Records an ADT event and broadcasts it when the status or unit changes.
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

    if status_changed or unit_changed:
        publisher = AdtEventPublisher()
        await publisher.publish_for_encounter(db, encounter, patient)

    await db.commit()
    await db.refresh(encounter)
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
