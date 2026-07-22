---
id: TASK-004
title: "Create `hl7-listener/app/handlers/cancellation_handlers.py` — Register A11/A12/A13 Handlers in ADTRouter with Backend API Call & Unknown Encounter Guard"
user_story: US-015
epic: EP-001
sprint: 2
layer: Backend
estimate: 2.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-012/TASK-003, US-015/TASK-001, US-015/TASK-002, US-015/TASK-003]
---

# TASK-004: Create `hl7-listener/app/handlers/cancellation_handlers.py` — Register A11/A12/A13 Handlers in ADTRouter with Backend API Call & Unknown Encounter Guard

> **Story:** US-015 | **Epic:** EP-001 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2.5 h
> **Status:** Done | **Date:** 2026-07-22

---

## Context

US-012/TASK-003 registered stub handlers for all `EventType` values including `CANCEL_ADMIT` (A11), `CANCEL_TRANSFER` (A12), and `CANCEL_DISCHARGE` (A13). US-014 replaced those stubs with `ADTEventPublisher.publish()` for all event types.

US-015 requires **additional** handling for cancellation events: beyond publishing to Pub/Sub (already done by US-014), the hl7-listener must also invoke the backend API to **immediately** trigger encounter status revert and agent task cancellation. Immediate processing is critical for patient safety — the US-015 user story note states:

> *"An A11 (cancel admit) means the patient was never actually admitted and agents should not generate discharge summaries or medication reconciliation for a non-existent encounter."*

Waiting for the Pub/Sub → Coordinator Agent → API path would introduce latency during which agents could complete work on a cancelled encounter. The hl7-listener therefore makes a direct HTTP call to the `api-gateway` cancellation endpoint within the same MLLP message processing cycle.

**Execution order within `process_message()` for A11/A12/A13 (extending TASK-003 from US-014):**

```
1.  Archive raw HL7 to GCS                   (US-013)
2.  Idempotency check                        (US-013)
3.  Parse HL7 to ADTEvent                    (US-012)
4.  Route to handler                         (US-012)
5a. For A01/A02/A03/A04/A08: Publish Pub/Sub (US-014) → ACK
5b. For A11/A12/A13: Call cancellation API   ← NEW (this task)
                   + Publish Pub/Sub         (US-014, unchanged)
                   → ACK
```

**Unknown encounter handling (Scenario 4):**

> *"an A11 arrives for encounter `ENC-UNKNOWN` that does not exist... ACK (AA) is returned, a warning log entry is created with `unknown_encounter_id=ENC-UNKNOWN`, and no state changes are made."*

The cancellation handler calls the backend API; the API responds with 404 if the encounter is not found. The handler catches 404, logs a warning, and returns normally (does not raise). MLLP ACK is still sent — the HL7 spec requires an ACK regardless of application-level outcome.

Design decisions:

| Decision | Rationale |
|----------|-----------|
| HTTP call to api-gateway (not direct ORM access) | HL7 listener is a separate Cloud Run service with no direct DB access; the api-gateway is the system's write API (ADR-002, TR-022) |
| `httpx.AsyncClient` with timeout=5s | Cancellation API call must complete within the 5s MLLP processing SLA (NFR-003); 5s timeout leaves buffer for DB write + Pub/Sub dispatch |
| 404 → warning log + ACK (no raise) | US-015 Scenario 4: unknown encounter is not an error from the HL7 spec perspective; the MLLP standard requires ACK regardless |
| Pub/Sub publish still runs after API call | US-014 pipeline step is unchanged; coordinator agent (EP-003) still receives the A11 via Pub/Sub for its own drain logic |
| Service account JWT in `Authorization` header | Zero-trust: hl7-listener authenticates to api-gateway via GCP Workload Identity signed JWT (SEC-001) |

Design refs: AIR-001, FR-006, NFR-003, SEC-001, TR-022, US-012/TASK-003, US-014/TASK-003, US-015 SC-1 to SC-4.

---

## Acceptance Criteria Addressed

| US-015 AC | Requirement |
|---|---|
| **Scenario 1 (A11)** | `cancel_admit_handler` invoked; backend API called; 5 AgentTasks cancelled; encounter → PRE_ADMISSION |
| **Scenario 2 (A12)** | `cancel_transfer_handler` invoked; backend API called; encounter unit reverted |
| **Scenario 3 (A13)** | `cancel_discharge_handler` invoked; backend API called; encounter → ADMITTED; discharge docs cancelled |
| **Scenario 4** | 404 from API → warning log with `unknown_encounter_id`; ACK returned; no state changes |
| **DoD** | Cancellation event handlers implemented for A11, A12, A13 in the event routing map |

---

## Implementation Steps

### 1. Scaffold the handlers package

```
hl7-listener/
└── app/
    └── handlers/
        ├── __init__.py
        └── cancellation_handlers.py   ← THIS TASK
```

```bash
mkdir -p hl7-listener/app/handlers
touch hl7-listener/app/handlers/__init__.py
```

### 2. Create `hl7-listener/app/handlers/cancellation_handlers.py`

```python
"""ADT cancellation event handlers for A11, A12, A13.

Registered into the ``ADTRouter`` to replace the stub handlers for
``EventType.CANCEL_ADMIT``, ``EventType.CANCEL_TRANSFER``, and
``EventType.CANCEL_DISCHARGE``.

Execution flow (per handler):
  1. Extract encounter_id from the ADTEvent.
  2. POST to api-gateway /api/v1/encounters/{id}/cancel-event with the
     cancellation event type.
  3. On success (2xx): log confirmation.
  4. On 404: log warning (unknown_encounter_id); return normally.
  5. On other HTTP error: log error; raise so the MLLP pipeline can
     nack and retry.
  The Pub/Sub publish step (US-014) runs separately after the handler
  returns.

PHI safety (BR-020 / ADR-007):
  Handler logs include only encounter_id (UUID) and event_type string.
  No patient name, MRN, or DOB is logged.

Environment variable:
  API_GATEWAY_BASE_URL — base URL of the FastAPI api-gateway service
                         (e.g. https://api-gateway-xxx.run.app)

Design refs:
    AIR-001  — MLLP ACK within 200ms of receipt; handler must be fast
    FR-006   — halt in-progress agent workflows on A11/A12/A13
    NFR-003  — <5s end-to-end ADT processing
    SEC-001  — service-to-service JWT authentication (Workload Identity)
    US-015   — SC-1 to SC-4, DoD
"""
from __future__ import annotations

import logging
import os
from uuid import UUID

import httpx

from app.models.adt_event import ADTEvent, EventType
from app.parser.router import ADTRouter, default_router

logger = logging.getLogger(__name__)

_API_BASE_URL: str = os.environ.get("API_GATEWAY_BASE_URL", "")
_CANCEL_TIMEOUT_S: float = 5.0

# ------------------------------------------------------------------
# Internal HTTP helper
# ------------------------------------------------------------------


async def _call_cancel_api(
    encounter_id: UUID,
    event_type: str,
    client: httpx.AsyncClient,
) -> None:
    """POST to /api/v1/encounters/{id}/cancel-event.

    Args:
        encounter_id: The encounter to cancel.
        event_type: "A11", "A12", or "A13".
        client: Shared ``httpx.AsyncClient`` (caller provides for pooling).

    Raises:
        httpx.HTTPStatusError: On non-404, non-2xx responses (caller nacks).
    """
    url = f"{_API_BASE_URL}/api/v1/encounters/{encounter_id}/cancel-event"
    payload = {"event_type": event_type}

    try:
        response = await client.post(
            url,
            json=payload,
            timeout=_CANCEL_TIMEOUT_S,
        )

        if response.status_code == 404:
            logger.warning(
                "cancellation_handler.unknown_encounter",
                extra={
                    "unknown_encounter_id": str(encounter_id),
                    "event_type": event_type,
                },
            )
            return  # Scenario 4: unknown encounter — ACK, no state change

        response.raise_for_status()  # raises on 4xx (except 404) and 5xx

        logger.info(
            "cancellation_handler.api_call_success",
            extra={
                "encounter_id": str(encounter_id),
                "event_type": event_type,
                "http_status": response.status_code,
            },
        )

    except httpx.TimeoutException:
        logger.error(
            "cancellation_handler.api_call_timeout",
            extra={
                "encounter_id": str(encounter_id),
                "event_type": event_type,
                "timeout_s": _CANCEL_TIMEOUT_S,
            },
        )
        raise  # re-raise so MLLP pipeline can nack


# ------------------------------------------------------------------
# Handler factory
# ------------------------------------------------------------------


def _make_cancellation_handler(event_type: str):
    """Return an async handler for the given cancellation event type.

    Produces handlers for A11, A12, and A13 with the same logic, differing
    only in the ``event_type`` string passed to the API.
    """

    async def _handler(event: ADTEvent, client: httpx.AsyncClient) -> None:
        encounter_id: UUID = event.encounter_id
        await _call_cancel_api(
            encounter_id=encounter_id,
            event_type=event_type,
            client=client,
        )

    _handler.__name__ = f"cancel_{event_type.lower()}_handler"
    return _handler


cancel_admit_handler    = _make_cancellation_handler("A11")
cancel_transfer_handler = _make_cancellation_handler("A12")
cancel_discharge_handler = _make_cancellation_handler("A13")

# ------------------------------------------------------------------
# Register handlers with the default ADT router
# ------------------------------------------------------------------


def register_cancellation_handlers(router: ADTRouter = default_router) -> None:
    """Register A11, A12, A13 cancellation handlers on the given router.

    Replaces any previously registered handlers for these event types
    (idempotent — safe to call multiple times, last write wins).

    Args:
        router: Target ``ADTRouter``; defaults to ``default_router``.

    Example::

        # Called once at application startup, after the router is created:
        register_cancellation_handlers()
    """
    router.register(EventType.CANCEL_ADMIT,    cancel_admit_handler)
    router.register(EventType.CANCEL_TRANSFER, cancel_transfer_handler)
    router.register(EventType.CANCEL_DISCHARGE, cancel_discharge_handler)

    logger.info(
        "cancellation_handlers.registered",
        extra={"event_types": ["A11", "A12", "A13"]},
    )
```

### 3. Invoke `register_cancellation_handlers()` at application startup

In `hl7-listener/app/main.py` (FastAPI lifespan or startup event), call:

```python
from app.handlers.cancellation_handlers import register_cancellation_handlers

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup (PublishRetryQueue.start(), etc.)
    register_cancellation_handlers()
    yield
    # ... existing shutdown
```

### 4. Add `POST /api/v1/encounters/{id}/cancel-event` endpoint to `api-gateway`

In `api-gateway/app/api/v1/encounters.py` (extend):

```python
from app.services.cancellation_service import CancellationService
from app.services.cancellation_dispatcher import CancellationDispatcher
from app.models.encounter import EncounterStatus
from app.exceptions import EncounterNotFoundError, EncounterStateTransitionError

class CancelEventRequest(BaseModel):
    event_type: Literal["A11", "A12", "A13"]

@router.post(
    "/{encounter_id}/cancel-event",
    status_code=200,
    summary="Process ADT cancellation event (A11/A12/A13) for an encounter",
)
async def cancel_encounter_event(
    encounter_id: UUID,
    body: CancelEventRequest,
    db: AsyncSession = Depends(get_db_session),
    svc: CancellationService = Depends(get_cancellation_service),
    dispatcher: CancellationDispatcher = Depends(get_cancellation_dispatcher),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> dict:
    try:
        async with db.begin():
            match body.event_type:
                case "A11":
                    result = await svc.handle_cancel_admit(encounter_id, db)
                case "A12":
                    result = await svc.handle_cancel_transfer(encounter_id, db)
                case "A13":
                    result = await svc.handle_cancel_discharge(encounter_id, db)
    except EncounterNotFoundError:
        raise HTTPException(status_code=404, detail="Encounter not found")
    except EncounterStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Post-commit: Pub/Sub + SignalR (background, does not block response)
    background_tasks.add_task(dispatcher.dispatch_post_commit, result)

    return {
        "encounter_id": str(result.encounter_id),
        "event_type": result.event_type,
        "tasks_cancelled": result.tasks_cancelled,
        "docs_cancelled": result.docs_cancelled,
    }
```

### 5. Verify handler registration

```bash
cd hl7-listener
python -c "
from app.handlers.cancellation_handlers import register_cancellation_handlers
from app.parser.router import default_router
from app.models.adt_event import EventType

register_cancellation_handlers()
for et in [EventType.CANCEL_ADMIT, EventType.CANCEL_TRANSFER, EventType.CANCEL_DISCHARGE]:
    assert et in default_router._handlers, f'Handler not registered for {et}'
print('Handler registration: PASSED')
"
```

---

## Definition of Done Checklist

- [ ] `cancellation_handlers.py` created with `cancel_admit_handler`, `cancel_transfer_handler`, `cancel_discharge_handler`
- [ ] `register_cancellation_handlers()` called during hl7-listener application startup
- [ ] HTTP 404 response → warning log `unknown_encounter_id`, no raise (Scenario 4)
- [ ] HTTP timeout (>5s) → error log, exception re-raised so MLLP pipeline can nack
- [ ] `POST /api/v1/encounters/{id}/cancel-event` endpoint added to api-gateway
- [ ] Endpoint returns 404 for unknown encounter, 409 for invalid state transition
- [ ] Pub/Sub + SignalR dispatched as background task (post-commit, does not block HTTP response)
- [ ] No PHI in any handler log entries
