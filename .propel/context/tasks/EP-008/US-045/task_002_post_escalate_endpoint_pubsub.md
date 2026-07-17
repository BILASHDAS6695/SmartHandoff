---
id: TASK-002
title: "POST /api/v1/chat/escalate — Create Escalation Record & Publish to Pub/Sub"
user_story: US-045
epic: EP-008
sprint: 2
layer: Backend / API
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-045/TASK-001, US-043, US-044]
---

# TASK-002: POST /api/v1/chat/escalate — Create Escalation Record & Publish to Pub/Sub

> **Story:** US-045 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements the `POST /api/v1/chat/escalate` endpoint that:
1. Receives an escalation trigger (from the urgency detector — US-044)
2. Resolves the on-call nurse from `app_user`
3. Writes a `ChatbotEscalation` row to Cloud SQL
4. Publishes an `EscalationAlertPayload` to the `notification-requests` Pub/Sub topic (fire-and-forget)
5. Pushes an `EscalationConfirmedMessage` (`{type: ESCALATION_CONFIRMED}`) to the patient's SignalR group
6. Returns an `EscalationRead` response to the caller

### Critical design constraint — fire-and-forget

> US-045 Technical Notes: **Do NOT block the chat response on escalation delivery.**  
> Pub/Sub publish is fire-and-forget. The `EscalationConfirmedMessage` is pushed to the
> patient's SignalR group immediately after the DB write succeeds — before Pub/Sub
> acknowledgement is received from the Notification Service.

### Endpoint behaviour

```
POST /api/v1/chat/escalate
Authorization: Bearer {patient_jwt}   ← patient scope; encounter_id verified
Body: EscalationCreate

1. Validate JWT (existing middleware — design.md §3.3)
2. Extract encounter_id claim from JWT
3. Compare claim with EscalationCreate.encounter_id → 403 if mismatch (AC Scenario 4)
4. Resolve on-call nurse: SELECT app_user WHERE role='nurse' AND unit matches encounter.unit AND on_call=true LIMIT 1
5. Write ChatbotEscalation row (encounter_id, transcript_message_id, notified_user_id, channel, urgency_message, notified_at=now())
6. Publish EscalationAlertPayload to 'notification-requests' Pub/Sub topic (asyncio.create_task — fire-and-forget)
7. Push EscalationConfirmedMessage to SignalR group 'encounter-{encounter_id}'
8. Write HIPAA audit event: {encounter_id, escalation_id, event='ESCALATION_CREATED'} — no urgency_message in log
9. Return EscalationRead
```

### On-call nurse resolution

The on-call nurse is resolved by querying `app_user` for staff with `role='nurse'` assigned to the same unit as the encounter and `on_call=True`. If no on-call nurse is found for the unit, fall back to any nurse with `on_call=True` hospital-wide. If still none, log a `P1 ESCALATION_NO_ONCALL_NURSE` metric and return the escalation record with `notified_user_id=None` so the care team dashboard alert fires via the monitoring layer.

**Design references:**
- design.md §3.1 — Patient Communication Agent: escalation routing
- design.md §3.3 — API middleware stack (JWT Validator → RBAC → PHI Log Sanitiser → HIPAA Audit Logger → Handler)
- design.md §7.5 AIR-040 — Notification Service reads `notification-requests` topic; `EscalationAlertPayload.channel` field required
- design.md §7.5 AIR-041 — Twilio webhook updates delivery status; this endpoint does not wait for it
- design.md §8.2 — patient JWT `encounter_id` claim; scope enforcement required before any DB write
- design.md §8.3 — RBAC: patient role can write escalations for own encounter only
- design.md §10.1 — HIPAA audit log: `encounter_id` + `escalation_id` + event type; no `urgency_message` content
- design.md §10.2 — fire-and-forget Pub/Sub: if Pub/Sub publish fails, log error metric; do not return 500 to patient
- US-045 AC Scenario 1 — `EscalationConfirmedMessage` displayed immediately after urgency detection
- US-045 AC Scenario 4 — patient cannot escalate for another patient's encounter (403)
- US-045 Technical Notes — `{type: ESCALATION_CONFIRMED}` is a special chat message type, not a regular chatbot reply

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `EscalationConfirmedMessage` pushed to SignalR group immediately after DB write |
| Scenario 2 | `notified_at` timestamp written; `acknowledged_at` starts as NULL |
| Scenario 3 | `ChatbotEscalation` row written with `transcript_message_id` FK |
| Scenario 4 | JWT `encounter_id` claim enforced before any write; mismatch → 403 |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p api-gateway/app/routers
mkdir -p backend/app/agents/patient_comm/escalation
touch api-gateway/app/routers/escalation.py
touch backend/app/agents/patient_comm/escalation/service.py
touch backend/app/agents/patient_comm/escalation/pubsub_publisher.py
touch backend/app/agents/patient_comm/escalation/oncall_resolver.py
```

### 2. Implement `backend/app/agents/patient_comm/escalation/oncall_resolver.py`

```python
"""Resolves the on-call nurse for a given encounter unit (US-045).

Design ref:
    US-045 Technical Notes — notified_user_id resolved from app_user table
    design.md §8.3 — nurse role scope
"""
from __future__ import annotations

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def resolve_oncall_nurse(
    session: AsyncSession,
    unit_id: uuid.UUID,
) -> uuid.UUID | None:
    """Return the app_user.id of the on-call nurse for `unit_id`.

    Resolution order:
        1. Nurse with on_call=True assigned to the specific unit
        2. Any nurse with on_call=True (hospital-wide fallback)
        3. None — caller must handle missing nurse scenario

    Returns:
        UUID of on-call nurse, or None if no on-call nurse is available.
    """
    # Attempt 1: unit-specific on-call nurse
    result = await session.execute(
        sa.text(
            """
            SELECT id FROM app_user
            WHERE role = 'nurse'
              AND unit_id = :unit_id
              AND on_call = TRUE
            LIMIT 1
            """
        ),
        {"unit_id": str(unit_id)},
    )
    row = result.fetchone()
    if row:
        return uuid.UUID(str(row[0]))

    # Attempt 2: any hospital-wide on-call nurse
    result = await session.execute(
        sa.text(
            """
            SELECT id FROM app_user
            WHERE role = 'nurse'
              AND on_call = TRUE
            LIMIT 1
            """
        )
    )
    row = result.fetchone()
    if row:
        log.warning(
            "oncall_nurse_unit_fallback",
            extra={"unit_id": str(unit_id)},
        )
        return uuid.UUID(str(row[0]))

    # No on-call nurse available — P1 metric logged by caller
    log.error("oncall_nurse_not_found", extra={"unit_id": str(unit_id)})
    return None
```

### 3. Implement `backend/app/agents/patient_comm/escalation/pubsub_publisher.py`

```python
"""Pub/Sub publisher for care team escalation alerts (US-045).

Publishes to the 'notification-requests' topic consumed by the
Notification Service (design.md §7.5 AIR-040).

Fire-and-forget pattern:
    Called via asyncio.create_task() from the escalation endpoint.
    Publish failures are logged as error metrics but do NOT propagate
    a 500 to the patient (US-045 Technical Notes).
"""
from __future__ import annotations

import json
import logging

from google.cloud import pubsub_v1

from backend.app.agents.patient_comm.escalation.schemas import EscalationAlertPayload
from backend.app.core.config import settings  # GCP_PROJECT_ID, NOTIFICATION_TOPIC_ID

log = logging.getLogger(__name__)


async def publish_escalation_alert(payload: EscalationAlertPayload) -> None:
    """Publish escalation alert to 'notification-requests' Pub/Sub topic.

    Uses the Pub/Sub PublisherClient. Runs as a background asyncio task
    so it does NOT block the HTTP response returned to the patient.

    Error handling:
        Pub/Sub errors are caught and logged as 'escalation_pubsub_error'
        metric — the escalation DB row has already been committed at this
        point so the record exists regardless of publish outcome.
    """
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(
        settings.GCP_PROJECT_ID,
        settings.NOTIFICATION_TOPIC_ID,  # 'notification-requests'
    )
    message_data = json.dumps(
        payload.model_dump(mode="json")
    ).encode("utf-8")

    try:
        future = publisher.publish(topic_path, data=message_data)
        future.result(timeout=10)
        log.info(
            "escalation_pubsub_published",
            extra={
                "escalation_id": payload.escalation_id,
                "encounter_id": payload.encounter_id,
                "channel": payload.channel,
            },
        )
    except Exception:
        # Log error metric; do NOT raise — fire-and-forget
        log.exception(
            "escalation_pubsub_error",
            extra={
                "escalation_id": payload.escalation_id,
                "encounter_id": payload.encounter_id,
            },
        )
```

### 4. Implement `backend/app/agents/patient_comm/escalation/service.py`

```python
"""EscalationService — domain logic for creating escalation records (US-045).

Coordinates:
    - on-call nurse resolution (oncall_resolver)
    - ChatbotEscalation DB write
    - Pub/Sub alert publish (fire-and-forget via asyncio.create_task)
    - SignalR push of EscalationConfirmedMessage

Design ref:
    US-045 Technical Notes — fire-and-forget pattern
    design.md §7.5 AIR-040 — EscalationAlertPayload format
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.patient_comm.escalation.models import ChatbotEscalation
from backend.app.agents.patient_comm.escalation.oncall_resolver import resolve_oncall_nurse
from backend.app.agents.patient_comm.escalation.pubsub_publisher import publish_escalation_alert
from backend.app.agents.patient_comm.escalation.schemas import (
    EscalationAlertPayload,
    EscalationConfirmedMessage,
    EscalationCreate,
    EscalationRead,
    NotificationChannel,
)
from backend.app.core.signalr import signalr_hub  # existing SignalR hub client

log = logging.getLogger(__name__)

# P1 Cloud Monitoring metric name for missing on-call nurse
_METRIC_NO_ONCALL_NURSE = "escalation_no_oncall_nurse"


async def create_escalation(
    session: AsyncSession,
    payload: EscalationCreate,
    patient_first_name: str,
    encounter_unit_id: uuid.UUID,
) -> tuple[ChatbotEscalation, EscalationConfirmedMessage]:
    """Create a ChatbotEscalation record and trigger nurse notification.

    Returns:
        Tuple of (ORM row, EscalationConfirmedMessage) for the caller to:
            - return EscalationRead to the HTTP client
            - push EscalationConfirmedMessage to SignalR

    Steps:
        1. Resolve on-call nurse
        2. Write ChatbotEscalation row
        3. Schedule Pub/Sub publish as background task (fire-and-forget)
        4. Build EscalationConfirmedMessage for SignalR push
    """
    notified_at = datetime.now(timezone.utc)
    notified_user_id = await resolve_oncall_nurse(session, encounter_unit_id)

    if notified_user_id is None:
        log.error(_METRIC_NO_ONCALL_NURSE, extra={"encounter_id": payload.encounter_id})

    row = ChatbotEscalation(
        encounter_id=uuid.UUID(payload.encounter_id),
        transcript_message_id=uuid.UUID(payload.transcript_message_id),
        notified_user_id=notified_user_id,
        notified_at=notified_at,
        acknowledged_at=None,
        channel=payload.channel.value,
        urgency_message=payload.urgency_message,
    )
    session.add(row)
    await session.flush()  # populate row.id without committing the outer transaction
    await session.commit()

    # Fire-and-forget Pub/Sub publish
    alert_payload = EscalationAlertPayload(
        escalation_id=str(row.id),
        encounter_id=payload.encounter_id,
        notified_user_id=str(notified_user_id) if notified_user_id else "UNRESOLVED",
        patient_first_name=patient_first_name,
        urgency_message_summary=payload.urgency_message,
        channel=payload.channel,
        timestamp=notified_at,
    )
    asyncio.create_task(publish_escalation_alert(alert_payload))

    confirmed_msg = EscalationConfirmedMessage(
        encounter_id=payload.encounter_id,
        escalation_id=str(row.id),
    )

    return row, confirmed_msg
```

### 5. Implement `api-gateway/app/routers/escalation.py` — POST /escalate

```python
"""FastAPI router for care team escalation endpoints (US-045).

Routes implemented in this task:
    POST /api/v1/chat/escalate

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

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.patient_comm.escalation.schemas import (
    EscalationCreate,
    EscalationRead,
)
from backend.app.agents.patient_comm.escalation.service import create_escalation
from backend.app.core.audit import write_audit_event
from backend.app.core.auth import get_current_patient_token
from backend.app.core.signalr import signalr_hub
from backend.app.db.session import get_async_session

router = APIRouter(prefix="/api/v1/chat", tags=["Escalation"])
log = logging.getLogger(__name__)


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


@router.post(
    "/escalate",
    response_model=EscalationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create care team escalation (patient-scoped)",
)
async def post_escalate(
    body: EscalationCreate,
    token_claims: dict = Depends(get_current_patient_token),
    session: AsyncSession = Depends(get_async_session),
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
```

### 6. Register router in FastAPI app

```python
# In api-gateway/app/main.py — add alongside existing routers
from api_gateway.app.routers.escalation import router as escalation_router

app.include_router(escalation_router)
```

---

## Validation Checklist

- [ ] `python -m py_compile api-gateway/app/routers/escalation.py` — zero errors
- [ ] `python -m py_compile backend/app/agents/patient_comm/escalation/service.py` — zero errors
- [ ] `POST /api/v1/chat/escalate` with matching JWT `encounter_id` → HTTP 201 + `EscalationRead`
- [ ] `POST /api/v1/chat/escalate` with mismatched JWT `encounter_id` → HTTP 403 `{"detail": "Access denied."}`
- [ ] `POST /api/v1/chat/escalate` with non-UUID `encounter_id` → HTTP 422 (Pydantic validation)
- [ ] `chatbot_escalation` row written to DB with `acknowledged_at=NULL`
- [ ] `EscalationConfirmedMessage` message text contains "2 minutes" and "911" (AC Scenario 1)
- [ ] `signalr_hub.send_to_group` called with group `encounter-{encounter_id}`
- [ ] Pub/Sub publish uses `asyncio.create_task` (fire-and-forget; does not block HTTP response)
- [ ] HIPAA audit log written with `encounter_id` + `escalation_id`; no `urgency_message` field

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-045/TASK-001 | Task | `ChatbotEscalation` ORM model and Pydantic schemas |
| US-043/TASK-004 | Task | `get_current_patient_token` dependency and `write_audit_event` utility |
| `backend/app/core/signalr.py` | Module | SignalR hub client for `send_to_group` |
| `notification-requests` Pub/Sub topic | Infra | Must exist in GCP (provisioned by Terraform) |
