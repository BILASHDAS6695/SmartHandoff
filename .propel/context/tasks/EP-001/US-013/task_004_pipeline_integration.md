---
id: TASK-004
title: "Integrate Archive & Idempotency into `hl7-listener/app/mllp/pipeline.py` — Pre-ACK Archive + Duplicate Guard"
user_story: US-013
epic: EP-001
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-011/TASK-003, US-013/TASK-001, US-013/TASK-002, US-013/TASK-003]
---

# TASK-004: Integrate Archive & Idempotency into `hl7-listener/app/mllp/pipeline.py` — Pre-ACK Archive + Duplicate Guard

> **Story:** US-013 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-013 requires two behaviours that must be wired into the MLLP processing pipeline:

1. **Archive before ACK (SC-1):** The raw HL7 message must be written to GCS (via `GCSArchiver`) before the MLLP ACK TCP response is dispatched. This guarantees replay capability even if the subsequent DB write or Pub/Sub publish fails.

2. **Idempotency before publish (SC-2):** Before the parsed `ADTEvent` is published to Pub/Sub, `IdempotencyChecker.is_duplicate()` must be called. If the MSH-10 ID is already in `adt_event`, the pipeline returns an ACK immediately — no new record is created and no Pub/Sub message is sent.

The MLLP pipeline (`pipeline.py`) already exists from US-011 (the asyncio TCP server). This task extends the `process_message()` function in that pipeline to inject the new steps in the correct order.

**Execution order within `process_message()`:**

```
1.  Extract MSH-10 (msg_control_id) from raw HL7 bytes
        ↓
2.  Archive raw HL7 to GCS   [GCSArchiver.archive()]   ← NEW (SC-1)
        ↓
3.  Idempotency check         [IdempotencyChecker.is_duplicate()]   ← NEW (SC-2)
        │
        ├── True  → return ACK immediately (no further processing)
        │
        └── False → continue pipeline
                        ↓
4.  Parse HL7 to ADTEvent     [HL7Parser.parse()]
        ↓
5.  Route to handler          [ADTRouter.route()]
        ↓
6.  Return ACK
```

**Fail-open DB failure policy (idempotency):** If the DB is unreachable, `is_duplicate()` raises a `SQLAlchemyError`. The pipeline catches this, logs a warning, and continues processing (treats as non-duplicate). This prevents DB connectivity issues from blocking all HL7 ingestion — a P1 alert from Cloud Monitoring will fire on the DB connectivity metric independently.

Design refs: AIR-001 (MLLP ACK), AIR-003 (archive before ACK), DR-022 (idempotency), TR-017 (graceful shutdown), US-011 TASK-003.

---

## Acceptance Criteria Addressed

| US-013 AC | Requirement |
|---|---|
| **Scenario 1** | `GCSArchiver.archive()` called and GCS write confirmed before ACK returned |
| **Scenario 2** | `IdempotencyChecker.is_duplicate()` called; returns early with ACK if duplicate |
| **Scenario 3** | Archive path date-partitioned (validated in TASK-001; pipeline passes `arrived_at=datetime.utcnow()`) |
| **Scenario 4** | GCS write failure handled by `GCSArchiver` (TASK-001); ACK sent after fallback write |
| **DoD** | Archive occurs atomically before ACK dispatch; idempotency check before any DB write |

---

## Implementation Steps

### 1. Locate and extend `hl7-listener/app/mllp/pipeline.py`

The `process_message()` function from US-011/TASK-003 currently has the signature:

```python
async def process_message(raw_hl7: str) -> bytes:
    """Process a raw HL7 message and return the ACK bytes."""
    ...
```

Extend it by injecting `GCSArchiver`, `FallbackQueue`, and `IdempotencyChecker` dependencies and inserting the two new pipeline steps.

### 2. Updated `hl7-listener/app/mllp/pipeline.py`

```python
"""MLLP message processing pipeline — extended with archive and idempotency.

Processing order (US-013):
  1. Extract MSH-10 from raw bytes (no full parse needed yet)
  2. Archive raw HL7 to GCS via GCSArchiver [SC-1 — before ACK]
  3. Idempotency check via IdempotencyChecker [SC-2 — before Pub/Sub]
     └── Duplicate → return ACK (AA) immediately
  4. Parse HL7 to ADTEvent via HL7Parser
  5. Route ADTEvent to registered handler via ADTRouter
  6. Return ACK (AA)

Fail-open policy for idempotency DB failure:
  If the DB is unreachable, SQLAlchemyError is caught and logged.
  The pipeline continues (treat as non-duplicate) to avoid blocking
  all HL7 ingestion on a DB connectivity blip.  Cloud Monitoring P1
  alert for DB replication lag fires independently (TR-014).

Design refs:
    AIR-001 — MLLP ACK within 200 ms of receipt
    AIR-003 — archive before ACK (SC-1)
    DR-022  — MSH-10 idempotency (SC-2)
    TR-017  — graceful shutdown; GCSArchiver uses FallbackQueue on SIGTERM
    US-011  — MLLP server and ACK/NACK builders (upstream)
"""
from __future__ import annotations

import datetime
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.archive.gcs_archiver import GCSArchiver
from app.archive.fallback_queue import FallbackQueue
from app.idempotency.idempotency_checker import IdempotencyChecker
from app.mllp.ack_builder import build_ack_response, build_nack_response
from app.parser.models import HL7ValidationError
from app.parser.hl7_parser import HL7Parser
from app.parser.router import default_router
from app.db.session import get_async_session  # async session factory (US-006)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons — initialised at service startup (see main.py)
# ---------------------------------------------------------------------------

_fallback_queue: FallbackQueue | None = None
_gcs_archiver: GCSArchiver | None = None
_idempotency_checker = IdempotencyChecker()
_hl7_parser = HL7Parser()


def init_pipeline(
    fallback_queue: FallbackQueue,
    gcs_archiver: GCSArchiver,
) -> None:
    """Initialise pipeline dependencies at service startup.

    Called from ``main.py`` after the asyncio event loop is running and
    ``FallbackQueue.start()`` has been awaited.

    Args:
        fallback_queue: Started ``FallbackQueue`` instance.
        gcs_archiver:   ``GCSArchiver`` configured with ``fallback_queue``.
    """
    global _fallback_queue, _gcs_archiver
    _fallback_queue = fallback_queue
    _gcs_archiver = gcs_archiver


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

async def process_message(raw_hl7: str) -> bytes:
    """Process a raw HL7 ADT message through the full pipeline.

    Returns the MLLP-framed ACK (AA) or NACK (AE) bytes.

    The MLLP server (US-011/TASK-003) calls this coroutine for every
    successfully framed HL7 message.

    Step 1 — Extract MSH-10:
        Use a lightweight string split to get the message control ID
        without a full hl7apy parse.  The full parse happens in Step 4.

    Step 2 — Archive to GCS (SC-1):
        ``GCSArchiver.archive()`` is awaited before any other processing.
        The method handles retries and fallback internally.

    Step 3 — Idempotency check (SC-2):
        Query ``adt_event.source_message_id``.  On duplicate: return ACK.
        On DB error: log warning and continue (fail-open policy).

    Step 4 — Parse HL7 message:
        ``HL7Parser.parse()`` raises ``HL7ValidationError`` on bad messages.
        On parse failure: return NACK (AE).

    Step 5 — Route to handler:
        ``default_router.route()`` dispatches to the registered handler
        (Pub/Sub publisher stub until that story is implemented).

    Step 6 — Return ACK.
    """
    arrived_at = datetime.datetime.now(datetime.timezone.utc)

    # ------------------------------------------------------------------ #
    # Step 1: Extract MSH-10 (msg_control_id) from raw HL7
    # ------------------------------------------------------------------ #
    msg_control_id = _extract_msh10(raw_hl7)

    # ------------------------------------------------------------------ #
    # Step 2: Archive raw HL7 to GCS before ACK (SC-1 / AIR-003)
    # ------------------------------------------------------------------ #
    if _gcs_archiver is not None:
        await _gcs_archiver.archive(
            raw_hl7=raw_hl7,
            msg_control_id=msg_control_id,
            arrived_at=arrived_at,
        )
    else:
        logger.warning(
            "GCSArchiver not initialised — skipping archive for message_id=%s. "
            "Call init_pipeline() at startup.",
            msg_control_id,
        )

    # ------------------------------------------------------------------ #
    # Step 3: Idempotency check — skip if already processed (SC-2)
    # ------------------------------------------------------------------ #
    try:
        async with get_async_session() as session:
            if await _idempotency_checker.is_duplicate(session, msg_control_id):
                # Return ACK immediately — no further processing (DR-022)
                return build_ack_response(msg_control_id)
    except SQLAlchemyError as exc:
        # Fail-open: DB error does not block HL7 ingestion
        logger.warning(
            "Idempotency check DB error for message_id=%s (%s) — treating as non-duplicate",
            msg_control_id,
            type(exc).__name__,
        )

    # ------------------------------------------------------------------ #
    # Step 4: Parse HL7 message
    # ------------------------------------------------------------------ #
    try:
        adt_event = _hl7_parser.parse(raw_hl7)
    except HL7ValidationError as exc:
        logger.warning(
            "HL7 validation failed for message_id=%s: %s",
            msg_control_id,
            str(exc),
        )
        return build_nack_response(msg_control_id, error_message=str(exc))

    # ------------------------------------------------------------------ #
    # Step 5: Route to registered handler (Pub/Sub publish stub)
    # ------------------------------------------------------------------ #
    try:
        default_router.route(adt_event)
    except Exception as exc:
        logger.error(
            "Handler routing failed for message_id=%s event_type=%s: %s",
            msg_control_id,
            adt_event.event_type,
            type(exc).__name__,
        )
        # Do not NACK — the message is archived and will be replayed; return ACK
        # to prevent EHR from indefinitely retransmitting a successfully-received msg.

    # ------------------------------------------------------------------ #
    # Step 6: Return ACK
    # ------------------------------------------------------------------ #
    return build_ack_response(msg_control_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_msh10(raw_hl7: str) -> str:
    """Extract the MSH-10 message control ID from a raw HL7 string.

    Uses lightweight string splitting (no hl7apy overhead) since this runs
    before the full parse.  MSH is always the first segment; MSH-10 is the
    10th pipe-delimited field (0-indexed: index 9).

    Falls back to a placeholder value if extraction fails — the archive and
    idempotency steps still proceed with the placeholder.

    Args:
        raw_hl7: Raw HL7 message text (MLLP framing already stripped).

    Returns:
        MSH-10 value string, or ``"UNKNOWN-{timestamp}`` on extraction failure.
    """
    try:
        msh_segment = raw_hl7.split("\r")[0]
        fields = msh_segment.split("|")
        msg_control_id = fields[9].strip()
        if msg_control_id:
            return msg_control_id
    except (IndexError, AttributeError):
        pass
    # Fallback — generate a timestamp-based placeholder for archive path
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S%f")
    fallback_id = f"UNKNOWN-{ts}"
    logger.warning(
        "Could not extract MSH-10 from raw HL7 — using fallback ID: %s",
        fallback_id,
    )
    return fallback_id
```

### 3. Update `hl7-listener/app/main.py` — startup wiring

Add the following to the FastAPI `lifespan` context manager (or `@app.on_event("startup")` if lifespan is not yet implemented):

```python
# main.py — startup additions for US-013
from app.archive.gcs_archiver import GCSArchiver
from app.archive.fallback_queue import FallbackQueue
from app.mllp.pipeline import init_pipeline

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise archive pipeline
    fallback_queue = FallbackQueue(archiver=None)  # archiver set below
    gcs_archiver = GCSArchiver(fallback_queue=fallback_queue)
    fallback_queue._archiver = gcs_archiver          # complete circular ref
    await fallback_queue.start()
    init_pipeline(fallback_queue=fallback_queue, gcs_archiver=gcs_archiver)

    yield  # application runs

    # Graceful shutdown
    await fallback_queue.stop()
```

---

## File Structure After This Task

```
hl7-listener/
└── app/
    ├── archive/
    │   ├── __init__.py
    │   ├── gcs_archiver.py
    │   └── fallback_queue.py
    ├── idempotency/
    │   ├── __init__.py
    │   └── idempotency_checker.py
    ├── mllp/
    │   ├── pipeline.py         ← EXTENDED (archive + idempotency steps)
    │   ├── server.py
    │   └── ack_builder.py
    └── main.py                 ← EXTENDED (lifespan startup wiring)
```

---

## Definition of Done Checklist (this task)

- [ ] `process_message()` calls `GCSArchiver.archive()` **before** `build_ack_response()` or any return path
- [ ] `IdempotencyChecker.is_duplicate()` called after archive, before parser
- [ ] Duplicate detection returns ACK immediately without parsing or routing
- [ ] `SQLAlchemyError` from idempotency check is caught; pipeline continues (fail-open)
- [ ] `_extract_msh10()` uses pipe-split fallback, never raises
- [ ] `init_pipeline()` called during `lifespan` startup with both dependencies
- [ ] `FallbackQueue.stop()` called in lifespan shutdown
