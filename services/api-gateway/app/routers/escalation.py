"""FastAPI router for care team escalation endpoints (US-045).

Routes implemented in this module:
    POST /api/v1/chat/escalate (TASK-002)
    PATCH /api/v1/chat/escalation/{id}/acknowledge (TASK-003)
    GET /api/v1/chat/escalations (TASK-004)

Security (US-045 AC Scenario 4):
    Patient JWT encounter_id claim must match EscalationCreate.encounter_id.
    Mismatch → HTTP 403. No information about the target encounter is disclosed.

Audit logging (US-045 DoD / design.md §10.1):
    Only encounter_id, escalation_id, and event type written to HIPAA audit log.
    urgency_message MUST NOT appear in any log field.

PHI safety (design.md AIR-021):
    urgency_message is passed to EscalationService; it does NOT appear in
    any structured log field. patient_first_name is the minimum PHI needed
    for the nurse notification body.

Design refs:
    design.md §3.3 — middleware stack
    design.md §8.2 — patient JWT encounter scope
    design.md §8.3 — patient role: own encounter only
    design.md §10.1 — HIPAA audit log fields
    US-045 AC Scenarios 1, 2, 3, 4
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.patient_comm.escalation.models import ChatbotEscalation
from backend.app.agents.patient_comm.escalation.monitoring import emit_acknowledgement_metric
from backend.app.agents.patient_comm.escalation.schemas import (
    EscalationAcknowledge,
    EscalationCreate,
    EscalationRead,
)
from backend.app.agents.patient_comm.escalation.service import create_escalation
from backend.app.core.auth.dependencies import get_current_token_claims
from backend.app.core.audit import write_audit_event
from backend.app.core.signalr import signalr_hub
from backend.app.db.deps import get_read_db, get_write_db

router = APIRouter(prefix="/api/v1/chat", tags=["escalation"])
log = logging.getLogger(__name__)

# Staff roles authorized to acknowledge escalations (TASK-003)
_STAFF_ROLES = {"nurse", "physician", "admin", "pharmacist", "bed_manager"}

# Pagination defaults
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200

# Patient role constant
_PATIENT_ROLE = "patient"


def _enforce_encounter_scope(
    encounter_id_from_body: str,
    token_claims: dict,
) -> None:
    """Raise HTTP 403 if JWT encounter_id does not match request body.

    Called as the FIRST operation in every patient-scoped endpoint.
    No DB or Pub/Sub calls precede this check.

    Security note: The 403 body contains no information about whether
    the target encounter exists (prevents existence enumeration).
    """
    jwt_encounter_id = token_claims.get("encounter_id")
    if not jwt_encounter_id or jwt_encounter_id != encounter_id_from_body:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )


# ============================================================================
# TASK-002: POST /api/v1/chat/escalate
# ============================================================================


@router.post(
    "/escalate",
    response_model=EscalationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create care team escalation (patient-scoped)",
)
async def post_escalate(
    body: EscalationCreate,
    token_claims: dict = Depends(get_current_token_claims),
    session: AsyncSession = Depends(get_write_db),
) -> EscalationRead:
    """Create a ChatbotEscalation record and notify the on-call nurse.

    Steps:
        1. Scope enforcement (AC Scenario 4)
        2. Fetch encounter.unit_id and patient.first_name from DB
        3. Call EscalationService.create_escalation()
        4. Push EscalationConfirmedMessage to SignalR (AC Scenario 1)
        5. Write HIPAA audit event
        6. Return EscalationRead
    """
    # 1. Scope enforcement — first operation, before any DB query
    _enforce_encounter_scope(body.encounter_id, token_claims)

    # 2. Fetch encounter metadata needed for nurse resolution and notification
    result = await session.execute(
        sa.text(
            """
            SELECT e.unit_id, p.first_name
            FROM encounter e
            JOIN patient p ON p.id = e.patient_id
            WHERE e.id = :encounter_id
            """
        ),
        {"encounter_id": body.encounter_id},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found.",
        )
    unit_id = uuid.UUID(str(row[0]))
    patient_first_name: str = row[1]  # minimum PHI — first name only

    # 3. Create escalation record + fire-and-forget Pub/Sub publish
    escalation_row, confirmed_msg = await create_escalation(
        session=session,
        payload=body,
        patient_first_name=patient_first_name,
        encounter_unit_id=unit_id,
    )

    # 4. Push ESCALATION_CONFIRMED to patient's SignalR group (AC Scenario 1)
    await signalr_hub.send_to_group(
        group=f"encounter-{body.encounter_id}",
        method="ReceiveEscalationConfirmed",
        args=[confirmed_msg.model_dump()],
    )

    # 5. HIPAA audit log — no urgency_message content
    await write_audit_event(
        event_type="ESCALATION_CREATED",
        encounter_id=body.encounter_id,
        extra={"escalation_id": str(escalation_row.id)},
    )

    log.info(
        "escalation_created",
        extra={
            "escalation_id": str(escalation_row.id),
            "encounter_id": body.encounter_id,
            "channel": body.channel.value,
        },
    )

    return EscalationRead.model_validate(escalation_row)


# ============================================================================
# TASK-003: PATCH /api/v1/chat/escalation/{id}/acknowledge
# ============================================================================


@router.patch(
    "/escalation/{escalation_id}/acknowledge",
    response_model=EscalationRead,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge escalation (staff-only RBAC)",
)
async def patch_acknowledge_escalation(
    escalation_id: str,
    body: EscalationAcknowledge,
    token_claims: dict = Depends(get_current_token_claims),
    session: AsyncSession = Depends(get_write_db),
) -> EscalationRead:
    """Acknowledge a care team escalation and record SLA metric.

    Steps:
        1. Verify caller has staff role (AC Scenario 4)
        2. Fetch ChatbotEscalation by id
        3. Set acknowledged_at = now() if not already set (idempotent)
        4. Compute acknowledgement_time_minutes
        5. Emit SLA breach metric if >2 minutes
        6. Write HIPAA audit event with ack_time_minutes
        7. Return updated EscalationRead
    """
    # 1. RBAC check — staff-only
    caller_role: str = token_claims.get("role", "")
    if caller_role not in _STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )

    # 2. Fetch escalation record
    try:
        escalation_uuid = uuid.UUID(escalation_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="escalation_id must be a valid UUID.",
        )

    result = await session.execute(
        sa.select(ChatbotEscalation).where(ChatbotEscalation.id == escalation_uuid)
    )
    escalation = result.scalars().first()

    if escalation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escalation not found.",
        )

    # 3. Set acknowledged_at if not already set (idempotent)
    if escalation.acknowledged_at is None:
        escalation.acknowledged_at = datetime.now(timezone.utc)
        session.add(escalation)
        await session.commit()

    # 4. Compute acknowledgement_time_minutes
    if escalation.acknowledged_at is not None:
        delta = escalation.acknowledged_at - escalation.notified_at
        ack_time_minutes = round(delta.total_seconds() / 60, 2)

        # 5. Emit SLA metric (Phase 1: structured logging)
        emit_acknowledgement_metric(
            encounter_id=str(escalation.encounter_id),
            escalation_id=str(escalation.id),
            ack_time_minutes=ack_time_minutes,
        )

        # 6. HIPAA audit log
        await write_audit_event(
            event_type="ESCALATION_ACKNOWLEDGED",
            encounter_id=str(escalation.encounter_id),
            extra={
                "escalation_id": str(escalation.id),
                "ack_time_minutes": ack_time_minutes,
            },
        )

        log.info(
            "escalation_acknowledged",
            extra={
                "escalation_id": str(escalation.id),
                "encounter_id": str(escalation.encounter_id),
                "ack_time_minutes": ack_time_minutes,
            },
        )

    # 7. Return updated record
    return EscalationRead.model_validate(escalation)


# ============================================================================
# TASK-004: GET /api/v1/chat/escalations
# ============================================================================


@router.get(
    "/escalations",
    response_model=list[EscalationRead],
    status_code=status.HTTP_200_OK,
    summary="List care team escalations (patient-scoped or staff)",
)
async def get_escalations(
    encounter_id: Annotated[
        str | None,
        Query(description="Filter by encounter UUID"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=_MAX_PAGE_SIZE),
    ] = _DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
    token_claims: dict = Depends(get_current_token_claims),
    session: AsyncSession = Depends(get_read_db),
) -> list[EscalationRead]:
    """Return escalation records scoped to caller's role.

    Patient role:
        - Returns escalations for own encounter_id (from JWT claim) only.
        - If ?encounter_id provided and does not match JWT claim → 403.
        - Patient cannot discover other encounters' escalation IDs.

    Staff role:
        - Returns escalations filtered by ?encounter_id if provided.
        - Returns all escalations (paginated) if no filter provided.

    Results ordered by notified_at DESC (most recent first).
    """
    caller_role: str = token_claims.get("role", "")

    if caller_role == _PATIENT_ROLE:
        jwt_encounter_id: str | None = token_claims.get("encounter_id")
        if not jwt_encounter_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied.",
            )
        # If patient supplied ?encounter_id and it doesn't match their JWT → 403
        if encounter_id is not None and encounter_id != jwt_encounter_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied.",
            )
        # Force scope to patient's own encounter regardless of query param
        filter_encounter_id = jwt_encounter_id

    elif caller_role in _STAFF_ROLES:
        filter_encounter_id = encounter_id  # optional filter; None = all encounters

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )

    # Build query with optional encounter filter
    query = sa.select(ChatbotEscalation).order_by(
        ChatbotEscalation.notified_at.desc()
    )
    if filter_encounter_id is not None:
        try:
            filter_uuid = uuid.UUID(filter_encounter_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="encounter_id must be a valid UUID.",
            )
        query = query.where(ChatbotEscalation.encounter_id == filter_uuid)

    query = query.limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.scalars().all()

    # HIPAA audit log — PHI access recorded (no urgency_message content)
    await write_audit_event(
        event_type="ESCALATION_QUERIED",
        encounter_id=filter_encounter_id or "ALL",
        extra={
            "caller_role": caller_role,
            "result_count": len(rows),
            "limit": limit,
            "offset": offset,
        },
    )

    log.info(
        "escalations_queried",
        extra={
            "caller_role": caller_role,
            "encounter_id": filter_encounter_id,
            "result_count": len(rows),
        },
    )

    return [EscalationRead.model_validate(row) for row in rows]
