---
id: TASK-003
title: "Integrate `ADTEventPublisher` into `hl7-listener/app/mllp/pipeline.py` — Publish After DB Persist, Deferred ACK on Retry"
user_story: US-014
epic: EP-001
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-013/TASK-004, US-014/TASK-001, US-014/TASK-002]
---

# TASK-003: Integrate `ADTEventPublisher` into `hl7-listener/app/mllp/pipeline.py` — Publish After DB Persist, Deferred ACK on Retry

> **Story:** US-014 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-014 Acceptance Criteria Scenario 1 states:

> *"Given a valid ADTEvent has been parsed and persisted to `adt_event` table, When the Pub/Sub publisher dispatches the event, Then the message appears in the `adt-events` Pub/Sub topic within 1 second."*

Scenario 3 states:

> *"The original Pub/Sub ACK to the processing pipeline is withheld until publish succeeds."*

The MLLP pipeline (`pipeline.py`) already orchestrates archive, idempotency, parse, and route steps (US-011 through US-013). This task extends the pipeline to:

1. Call `ADTEventPublisher.publish(adt_event)` **after** the handler routes and persists the `ADTEvent` to the DB (step 5)
2. Withhold the MLLP ACK response until `publish()` returns — if `publish()` delegates to `PublishRetryQueue` (all 3 retries exhausted) the ACK is still returned after enqueue succeeds, since the event is now safely queued for retry
3. Wire `PublishRetryQueue` startup and shutdown into the FastAPI `lifespan` context manager

**Updated execution order within `process_message()`:**

```
1.  Extract MSH-10 (msg_control_id)
        ↓
2.  Archive raw HL7 to GCS   [GCSArchiver.archive()]            (US-013)
        ↓
3.  Idempotency check         [IdempotencyChecker.is_duplicate()]  (US-013)
        │
        ├── True  → return ACK immediately
        └── False → continue
                ↓
4.  Parse HL7 to ADTEvent     [HL7Parser.parse()]               (US-012)
        ↓
5.  Route to handler          [ADTRouter.route()]               (US-012)
        (handler persists ADTEvent to adt_event table)
        ↓
6.  Publish to Pub/Sub        [ADTEventPublisher.publish()]     ← NEW (US-014)
        ↓
7.  Return ACK (AA)           ← ACK deferred until step 6 completes
```

Design decisions encoded in this task:

| Decision | Rationale |
|----------|-----------|
| Publish after persist (step 6 > step 5) | ADR-003: DB write is source of truth; Pub/Sub is downstream notification. Publish-before-persist could result in agents processing events for non-existent DB records. |
| ACK after `publish()` returns | SC-3: "original Pub/Sub ACK withheld until publish succeeds". `publish()` either succeeds (direct or retry) or enqueues — either way it returns only after ensuring the event is durably handled. |
| `ADTEventPublisher` injected via dependency | Enables unit testing with a mock publisher; follows the pattern established for `GCSArchiver` and `IdempotencyChecker` |
| `PublishRetryQueue.start()` in lifespan | Background flush task must be running before the first MLLP message arrives |

Design refs: ADR-001, AIR-001, TR-005, TR-017, US-011/TASK-003, US-013/TASK-004, US-014 SC-1, SC-3.

---

## Acceptance Criteria Addressed

| US-014 AC | Requirement |
|---|---|
| **Scenario 1** | `ADTEventPublisher.publish()` called after `adt_event` persisted; ACK returned after publish completes |
| **Scenario 2** | Ordering key applied by publisher (TASK-001); pipeline passes the full `ADTEvent` — ordering key derived from `encounter_id` inside publisher |
| **Scenario 3** | `publish()` retries then enqueues; ACK returned after `publish()` returns (not before) |
| **Scenario 4** | Attributes set inside publisher (TASK-001); pipeline has no attribute logic |
| **DoD** | `ADTEventPublisher` wired into pipeline; `PublishRetryQueue` started in lifespan startup |

---

## Implementation Steps

### 1. Locate `hl7-listener/app/mllp/pipeline.py`

The current `process_message()` function (from US-011/TASK-003 + US-013/TASK-004) ends after `ADTRouter.route()`. Extend it by adding the publish step between route and ACK return.

### 2. Updated `hl7-listener/app/mllp/pipeline.py`

```python
"""MLLP message processing pipeline — extended with Pub/Sub publish step.

Processing order (US-011 → US-013 → US-014):
  1. Extract MSH-10 from raw bytes
  2. Archive raw HL7 to GCS via GCSArchiver           [US-013 SC-1]
  3. Idempotency check via IdempotencyChecker          [US-013 SC-2]
     └── Duplicate → return ACK immediately
  4. Parse HL7 to ADTEvent via HL7Parser               [US-012]
  5. Route ADTEvent to handler via ADTRouter            [US-012]
     (handler persists ADTEvent to adt_event table)
  6. Publish ADTEvent to Pub/Sub via ADTEventPublisher  [US-014]
  7. Return ACK (AA)

ACK deferred until step 6 completes (US-014 SC-3).

Fail-open policy for idempotency DB failure:
  If DB is unreachable, treat as non-duplicate (log + continue).

Design refs:
    AIR-001  — MLLP ACK within 200 ms of receipt; NACK on parse failure
    AIR-003  — archive before ACK
    ADR-001  — all ADT events to Pub/Sub before any agent processing
    DR-022   — MSH-10 idempotency
    TR-017   — graceful shutdown: stop publishers on SIGTERM
    US-014   — SC-1 to SC-4
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from app.hl7.parser import HL7Parser, HL7ParseError
from app.hl7.router import ADTRouter
from app.archive.gcs_archiver import GCSArchiver
from app.idempotency.idempotency_checker import IdempotencyChecker
from app.pubsub.adt_event_publisher import ADTEventPublisher  # NEW
from app.mllp.ack_builder import build_ack_response, build_nack_response
from app.mllp.msh_extractor import extract_msh10

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class MLLPPipeline:
    """Orchestrates the 7-step MLLP message processing pipeline.

    Dependencies are constructor-injected to enable deterministic unit
    testing without real I/O calls.

    Args:
        parser: ``HL7Parser`` instance for segment extraction.
        router: ``ADTRouter`` instance that persists the ``ADTEvent``.
        archiver: ``GCSArchiver`` instance for pre-ACK GCS write.
        idempotency_checker: ``IdempotencyChecker`` for MSH-10 dedup.
        publisher: ``ADTEventPublisher`` for Pub/Sub dispatch.  # NEW
        db_session: ``AsyncSession`` for idempotency DB queries.
    """

    def __init__(
        self,
        parser: HL7Parser,
        router: ADTRouter,
        archiver: GCSArchiver,
        idempotency_checker: IdempotencyChecker,
        publisher: ADTEventPublisher,  # NEW
        db_session: "AsyncSession",
    ) -> None:
        self._parser = parser
        self._router = router
        self._archiver = archiver
        self._idempotency = idempotency_checker
        self._publisher = publisher  # NEW
        self._db_session = db_session

    async def process_message(self, raw_hl7: str) -> bytes:
        """Process a raw HL7 message through all 7 pipeline steps.

        Returns:
            MLLP-framed ACK (AA) or NACK (AE) bytes.
        """
        # ------------------------------------------------------------------
        # Step 1: Extract MSH-10 (message control ID) without full parse
        # ------------------------------------------------------------------
        msg_control_id = extract_msh10(raw_hl7)

        # ------------------------------------------------------------------
        # Step 2: Archive raw HL7 to GCS before anything else (SC-1 US-013)
        # ------------------------------------------------------------------
        await self._archiver.archive(raw_hl7, msg_control_id)

        # ------------------------------------------------------------------
        # Step 3: Idempotency check — return early for duplicates (SC-2 US-013)
        # ------------------------------------------------------------------
        try:
            is_dup = await self._idempotency.is_duplicate(
                msg_control_id, self._db_session
            )
        except SQLAlchemyError as exc:
            logger.warning(
                "idempotency_db_error_fail_open",
                extra={"msg_control_id": msg_control_id, "error": str(exc)},
            )
            is_dup = False  # fail-open: treat as new message

        if is_dup:
            return build_ack_response(msg_control_id)

        # ------------------------------------------------------------------
        # Step 4: Parse raw HL7 bytes to ADTEvent domain object (US-012)
        # ------------------------------------------------------------------
        try:
            adt_event = await self._parser.parse(raw_hl7)
        except HL7ParseError as exc:
            logger.error(
                "hl7_parse_failure",
                extra={"msg_control_id": msg_control_id, "error": str(exc)},
            )
            return build_nack_response(msg_control_id)

        # ------------------------------------------------------------------
        # Step 5: Route to handler — persists ADTEvent to adt_event table (US-012)
        # ------------------------------------------------------------------
        await self._router.route(adt_event, self._db_session)

        # ------------------------------------------------------------------
        # Step 6: Publish ADTEvent to Pub/Sub adt-events topic  ← NEW US-014
        #
        # ACK is withheld until publish() returns.
        # publish() either:
        #   (a) succeeds directly or after retries → returns normally
        #   (b) exhausts retries → enqueues to PublishRetryQueue → returns
        # In both cases, the event is durably handled before ACK is sent.
        # ------------------------------------------------------------------
        await self._publisher.publish(adt_event)

        logger.info(
            "hl7_pipeline_complete",
            extra={
                "msg_control_id": msg_control_id,
                "encounter_id": str(adt_event.encounter_id),
                "event_type": adt_event.event_type.value,
            },
        )

        # ------------------------------------------------------------------
        # Step 7: Return MLLP ACK (AA)
        # ------------------------------------------------------------------
        return build_ack_response(msg_control_id)
```

### 3. Wire `PublishRetryQueue` into FastAPI lifespan (`hl7-listener/app/main.py`)

```python
# In the existing lifespan context manager (from US-011):

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    retry_queue = PublishRetryQueue(publish_fn=publisher.publish)
    await retry_queue.start()          # NEW: start background flush task
    app.state.retry_queue = retry_queue

    yield

    # --- Shutdown (SIGTERM) ---
    await retry_queue.stop()           # NEW: drain queue on shutdown (TR-017)
    await publisher.close()            # NEW: stop Pub/Sub client + executor
    await archiver.fallback_queue.stop()
```

> **Note:** The exact shape of `main.py` depends on what was produced by US-011/TASK-001. The integration point is `lifespan` startup and shutdown. If `main.py` does not yet have a `lifespan` context manager, create one following the [FastAPI lifespan docs](https://fastapi.tiangolo.com/advanced/events/).

---

## Validation

Run from `hl7-listener/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/mllp/pipeline.py').read_text())
print('Syntax check: PASSED')
"

# 2. Verify publish step is after route step in process_message source
python -c "
import inspect, textwrap
from app.mllp.pipeline import MLLPPipeline
src = inspect.getsource(MLLPPipeline.process_message)
route_pos = src.index('router.route')
publish_pos = src.index('publisher.publish')
assert publish_pos > route_pos, 'publish() must come after route()'
print('Pipeline order (route before publish): PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| MODIFY | `hl7-listener/app/mllp/pipeline.py` — add `publisher` param and Step 6 |
| MODIFY | `hl7-listener/app/main.py` — wire `PublishRetryQueue.start()` / `stop()` into lifespan |

---

## Definition of Done Checklist

- [ ] `ADTEventPublisher` injected as constructor parameter into `MLLPPipeline`
- [ ] `publisher.publish(adt_event)` called in step 6, after `router.route()` in step 5
- [ ] ACK is returned only after `publish()` completes (line ordering in `process_message`)
- [ ] `PublishRetryQueue.start()` called in FastAPI lifespan startup
- [ ] `PublishRetryQueue.stop()` called in FastAPI lifespan shutdown (TR-017)
- [ ] `publisher.close()` called in FastAPI lifespan shutdown (TR-017)
- [ ] Pipeline integration test (TASK-005) passes with mock publisher
