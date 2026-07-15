---
id: TASK-003
title: "Create `api-gateway/app/services/cancellation_dispatcher.py` — Publish `WORKFLOW_CANCELLED` Pub/Sub Event & Broadcast SignalR Notification (Post-Commit Background Tasks)"
user_story: US-015
epic: EP-001
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-015/TASK-001, US-015/TASK-002]
---

# TASK-003: Create `api-gateway/app/services/cancellation_dispatcher.py` — Publish `WORKFLOW_CANCELLED` Pub/Sub Event & Broadcast SignalR Notification (Post-Commit Background Tasks)

> **Story:** US-015 | **Epic:** EP-001 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-015 Technical Notes specify two side effects that must run **after** the database transaction commits — not inside it:

> *"SignalR notification dispatched via async background task after transaction commits (do not block MLLP ACK)"*
> *"A11 should also publish a `WORKFLOW_CANCELLED` event to Pub/Sub so the agent framework (EP-003) can drain its own in-flight tasks"*

And Scenario 1 requires:

> *"a SignalR notification is broadcast to care team dashboard users"*

Running these side effects outside the transaction boundary is correct for two reasons:

1. **Transaction isolation:** If the Pub/Sub publish or SignalR call fails, the DB transaction (encounter status revert + task cancellations) must not be rolled back — the cancellation is already durably recorded.
2. **MLLP ACK timeliness:** The HL7 listener's MLLP ACK must not be held open waiting for SignalR or Pub/Sub latency. Both are dispatched as FastAPI `BackgroundTask` entries after the HTTP response (ACK) is sent (AIR-001: "MLLP ACK within 200ms").

`CancellationDispatcher` encapsulates both side effects:

1. **Pub/Sub `WORKFLOW_CANCELLED` event** — published to `adt-events` topic with a special `message_type=WORKFLOW_CANCELLED` attribute. The Coordinator Agent (EP-003) subscribes to this attribute filter to drain any in-flight LLM or tool calls for the affected encounter.

2. **SignalR broadcast** — pushed to the `encounter-{encounter_id}` group with payload `{event: ENCOUNTER_CANCELLED, encounter_id, event_type, reason}` (Scenario 1 DoD requirement).

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Separate `CancellationDispatcher` from `CancellationService` | `CancellationService` (TASK-001) owns DB state; dispatcher owns external side effects. Separation simplifies unit testing: service tests mock dispatcher, dispatcher tests mock Pub/Sub SDK and SignalR hub |
| `dispatch_post_commit()` async method | Called after `await session.commit()` in the API handler; never called inside the `async with session.begin()` block |
| Pub/Sub `message_type=WORKFLOW_CANCELLED` attribute | Allows coordinator agent subscription to filter-match this event type specifically, without deserialising the full message body |
| `encounter_id` ordering key on `WORKFLOW_CANCELLED` | Same ordering key as standard ADT events (ADR-001); preserves FIFO per encounter in Pub/Sub |
| `ENCOUNTER_CANCELLED` SignalR event name | Care team dashboard subscribes to this event name to display cancellation banner; payload schema version-pinned |
| `asyncio.gather` for Pub/Sub + SignalR | Both are independent I/O operations; run concurrently to minimise total post-commit latency |

Design refs: ADR-001, AIR-001, FR-006, NFR-006 (<1s SignalR latency), TR-015, US-015 Technical Notes.

---

## Acceptance Criteria Addressed

| US-015 AC | Requirement |
|---|---|
| **Scenario 1** | SignalR notification broadcast to care team dashboard with `{event: ENCOUNTER_CANCELLED, encounter_id, reason}` |
| **DoD (Pub/Sub)** | `WORKFLOW_CANCELLED` event published to Pub/Sub (Technical Notes) |
| **DoD (no block)** | Notification dispatched as async background task — does not block MLLP ACK path |

---

## Implementation Steps

### 1. Scaffold the dispatcher

```
api-gateway/
└── app/
    └── services/
        └── cancellation_dispatcher.py   ← THIS TASK
```

### 2. Create `api-gateway/app/services/cancellation_dispatcher.py`

```python
"""Post-commit dispatcher for ADT cancellation side effects.

Publishes a ``WORKFLOW_CANCELLED`` Pub/Sub event and broadcasts a SignalR
``ENCOUNTER_CANCELLED`` notification after the database transaction for an
ADT cancellation event (A11, A12, or A13) has committed successfully.

IMPORTANT: This module must NEVER be called inside a database transaction.
The dispatcher performs best-effort I/O; failures are logged but do not
roll back the committed DB state.

Pub/Sub message spec (``WORKFLOW_CANCELLED``):
  topic     : adt-events  (same topic as all ADT events — ADR-001)
  ordering_key: str(encounter_id)
  attributes:
    message_type   = "WORKFLOW_CANCELLED"
    event_type     = "A11" | "A12" | "A13"
    encounter_id   = str(UUID)
    iso_timestamp  = ISO-8601 UTC string
  body      : UTF-8 JSON — {"encounter_id": str, "event_type": str,
                             "tasks_cancelled": int, "docs_cancelled": int}

SignalR payload spec (``ENCOUNTER_CANCELLED``):
  group     : "encounter-{encounter_id}"
  event     : "ENCOUNTER_CANCELLED"
  payload   :
    { "event": "ENCOUNTER_CANCELLED",
      "encounter_id": str(UUID),
      "event_type": "A11" | "A12" | "A13",
      "reason": "Cancellation event {event_type} received" }

PHI safety (BR-020):
  Neither the Pub/Sub message attributes nor the SignalR payload contain
  PHI fields (patient name, MRN, DOB). Only encounter_id (UUID) and
  event_type are included.

Design refs:
    ADR-001  — all ADT events (including WORKFLOW_CANCELLED) published to
               adt-events Pub/Sub topic
    AIR-001  — MLLP ACK within 200ms; dispatcher is post-commit background task
    FR-006   — A11/A12/A13 triggers halt of agent workflows
    NFR-006  — SignalR latency ≤1 second
    TR-015   — best-effort post-commit; failures logged, not fatal
    US-015   — SC-1 (SignalR), Technical Notes (Pub/Sub WORKFLOW_CANCELLED)
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from uuid import UUID

from app.pubsub.adt_event_publisher import ADTEventPublisher
from app.signalr.hub import SignalRHub
from app.services.cancellation_service import CancellationResult

logger = logging.getLogger(__name__)


class CancellationDispatcher:
    """Dispatches post-commit side effects for ADT cancellation events.

    Args:
        publisher: ``ADTEventPublisher`` instance (injected for testability).
        hub: ``SignalRHub`` instance (injected for testability).

    Example::

        dispatcher = CancellationDispatcher(publisher=publisher, hub=hub)
        # Call after session.commit():
        await dispatcher.dispatch_post_commit(result)
    """

    def __init__(
        self,
        publisher: ADTEventPublisher,
        hub: SignalRHub,
    ) -> None:
        self._publisher = publisher
        self._hub = hub

    async def dispatch_post_commit(
        self,
        result: CancellationResult,
    ) -> None:
        """Concurrently publish Pub/Sub event and broadcast SignalR notification.

        This method is designed to be called after the database transaction
        commits.  Failures in either side effect are logged at ERROR level but
        do not raise — the DB state is already durable.

        Args:
            result: ``CancellationResult`` from ``CancellationService``.
        """
        await asyncio.gather(
            self._publish_workflow_cancelled(result),
            self._broadcast_signalr(result),
            return_exceptions=True,  # log errors; do not raise
        )

    # ------------------------------------------------------------------
    # Pub/Sub
    # ------------------------------------------------------------------

    async def _publish_workflow_cancelled(
        self,
        result: CancellationResult,
    ) -> None:
        """Publish ``WORKFLOW_CANCELLED`` message to ``adt-events`` topic."""
        iso_now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        attributes = {
            "message_type":  "WORKFLOW_CANCELLED",
            "event_type":    result.event_type,
            "encounter_id":  str(result.encounter_id),
            "iso_timestamp": iso_now,
        }
        body = json.dumps(
            {
                "encounter_id":    str(result.encounter_id),
                "event_type":      result.event_type,
                "tasks_cancelled": result.tasks_cancelled,
                "docs_cancelled":  result.docs_cancelled,
            }
        ).encode("utf-8")

        try:
            await self._publisher.publish_raw(
                ordering_key=str(result.encounter_id),
                attributes=attributes,
                data=body,
            )
            logger.info(
                "cancellation_dispatcher.pubsub_published",
                extra={
                    "encounter_id": str(result.encounter_id),
                    "event_type":   result.event_type,
                    "message_type": "WORKFLOW_CANCELLED",
                },
            )
        except Exception:
            logger.exception(
                "cancellation_dispatcher.pubsub_publish_failed",
                extra={"encounter_id": str(result.encounter_id)},
            )

    # ------------------------------------------------------------------
    # SignalR
    # ------------------------------------------------------------------

    async def _broadcast_signalr(
        self,
        result: CancellationResult,
    ) -> None:
        """Broadcast ``ENCOUNTER_CANCELLED`` event to care team dashboard."""
        group = f"encounter-{result.encounter_id}"
        payload = {
            "event":        "ENCOUNTER_CANCELLED",
            "encounter_id": str(result.encounter_id),
            "event_type":   result.event_type,
            "reason":       f"Cancellation event {result.event_type} received",
        }
        try:
            await self._hub.send_to_group(
                group=group,
                event="ENCOUNTER_CANCELLED",
                payload=payload,
            )
            logger.info(
                "cancellation_dispatcher.signalr_broadcast",
                extra={
                    "encounter_id": str(result.encounter_id),
                    "group":        group,
                    "event_type":   result.event_type,
                },
            )
        except Exception:
            logger.exception(
                "cancellation_dispatcher.signalr_broadcast_failed",
                extra={"encounter_id": str(result.encounter_id)},
            )
```

### 3. Add `publish_raw()` method to `ADTEventPublisher` (minimal extension)

In `hl7-listener/app/pubsub/adt_event_publisher.py` (or the api-gateway equivalent), add a lower-level `publish_raw()` method that accepts pre-built `attributes` and `data` bytes, rather than a full `ADTEvent` object. This decouples `CancellationDispatcher` from the `ADTEvent` domain model.

```python
async def publish_raw(
    self,
    ordering_key: str,
    attributes: dict[str, str],
    data: bytes,
) -> str:
    """Publish a raw Pub/Sub message with pre-built attributes and body.

    Returns:
        The Pub/Sub message ID.
    """
    # same retry + run_in_executor pattern as publish()
    ...
```

### 4. Register `CancellationDispatcher` as a FastAPI dependency

```python
# api-gateway/app/dependencies.py (extend)
from app.services.cancellation_dispatcher import CancellationDispatcher
from app.pubsub.adt_event_publisher import ADTEventPublisher
from app.signalr.hub import SignalRHub

def get_cancellation_dispatcher(
    publisher: ADTEventPublisher = Depends(get_publisher),
    hub: SignalRHub = Depends(get_signalr_hub),
) -> CancellationDispatcher:
    return CancellationDispatcher(publisher=publisher, hub=hub)
```

---

## Definition of Done Checklist

- [ ] `CancellationDispatcher.dispatch_post_commit()` publishes `WORKFLOW_CANCELLED` to `adt-events` with correct attributes (`message_type`, `event_type`, `encounter_id`, `iso_timestamp`)
- [ ] `CancellationDispatcher.dispatch_post_commit()` broadcasts `ENCOUNTER_CANCELLED` SignalR event to `encounter-{encounter_id}` group
- [ ] Both operations run concurrently via `asyncio.gather`
- [ ] Failures in Pub/Sub or SignalR are logged at ERROR level but do not raise
- [ ] No PHI fields in Pub/Sub attributes or SignalR payload — only UUIDs and event type strings
- [ ] `ADTEventPublisher.publish_raw()` method implemented
- [ ] `CancellationDispatcher` registered as a FastAPI dependency

---

## Structured Log Fields (Cloud Monitoring alert alignment)

| Field | Example |
|---|---|
| `encounter_id` | `"3fa85f64-..."` |
| `event_type` | `"A11"` |
| `message_type` | `"WORKFLOW_CANCELLED"` |
| `group` | `"encounter-3fa85f64-..."` |

No PHI in any log entry.
