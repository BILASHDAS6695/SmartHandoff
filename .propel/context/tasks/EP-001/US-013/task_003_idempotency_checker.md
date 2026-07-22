---
id: TASK-003
title: "Create `hl7-listener/app/idempotency/idempotency_checker.py` — MSH-10 Idempotency Guard Against `adt_event` Table"
user_story: US-013
epic: EP-001
sprint: 1
layer: Backend
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-012/TASK-001, US-006]
---

# TASK-003: Create `hl7-listener/app/idempotency/idempotency_checker.py` — MSH-10 Idempotency Guard Against `adt_event` Table

> **Story:** US-013 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-013 Acceptance Criteria Scenario 2 states:

> *"Given an HL7 message with MSH-10 `MSG-20260714-001` has already been processed… When the same MSH-10 value arrives again, Then an ACK (AA) is returned immediately, no new `adt_event` record is created, and a `duplicate_message_skipped` log entry is written."*

US-013 DoD requires:

> *"Idempotency check: query `adt_event` table by `source_message_id` (MSH-10) before processing; return early if found"*
> *"`source_message_id` is indexed on `adt_event` table for fast lookup (O(log n))"*

`IdempotencyChecker` provides a single async method `is_duplicate(msg_control_id)` that queries the `adt_event` table. The index on `source_message_id` ensures the query executes in O(log n) time (DR-022, TASK-006 of US-006).

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Query only — no write | Writes happen in the coordinator agent after Pub/Sub delivery. Idempotency check is a pure read. |
| Async SQLAlchemy session | Matches the asyncio MLLP server; never blocks the event loop on a DB round-trip |
| Return `bool` | Simple contract: `True` = duplicate (skip), `False` = new (process) |
| Log `duplicate_message_skipped` as structured event | Allows Cloud Monitoring to count duplicate suppression for operational insight |
| Session injected, not created internally | Enables unit testing with a mock session; follows dependency injection pattern |

Design refs: DR-022, US-013 DoD (SC-2), ADR-003, TR-001 (async DB access).

---

## Acceptance Criteria Addressed

| US-013 AC | Requirement |
|---|---|
| **Scenario 2** | `is_duplicate()` returns `True` for a known `source_message_id`; `duplicate_message_skipped` log emitted |
| **DoD** | Query `adt_event.source_message_id` by MSH-10 before processing; indexed for O(log n) lookup |

---

## Implementation Steps

### 1. Scaffold the `idempotency` sub-package

```
hl7-listener/
└── app/
    └── idempotency/
        ├── __init__.py
        └── idempotency_checker.py  ← THIS TASK
```

```bash
mkdir -p hl7-listener/app/idempotency
touch hl7-listener/app/idempotency/__init__.py
```

### 2. Create `hl7-listener/app/idempotency/__init__.py`

```python
"""Idempotency sub-package — MSH-10 duplicate detection.

Exports:
  IdempotencyChecker  — async guard that queries adt_event.source_message_id

Design refs:
    DR-022  — HL7 message idempotency: MSH-10 unique constraint on adt_event
    US-013  — SC-2: duplicate detection before Pub/Sub publish
"""
from app.idempotency.idempotency_checker import IdempotencyChecker

__all__ = ["IdempotencyChecker"]
```

### 3. Create `hl7-listener/app/idempotency/idempotency_checker.py`

```python
"""MSH-10 idempotency guard for the HL7 Listener service.

Queries the ``adt_event`` table to determine whether an HL7 message with
the given MSH-10 message control ID has already been processed.

Why MSH-10 (message control ID)?
  DR-022 designates MSH-10 as the natural idempotency key.  EHR systems
  retransmit unacknowledged messages with the same MSH-10, so a unique
  constraint on ``adt_event.source_message_id`` (plus a B-tree index)
  allows the listener to short-circuit duplicate processing in O(log n)
  time before doing any Pub/Sub publish or agent work.

Database contract:
  - Table: ``adt_event``
  - Column: ``source_message_id``  (VARCHAR, unique, indexed)
  - The column and index are created by US-006 (schema migration).
  - This module performs a read-only ``SELECT EXISTS`` — it never writes.

Async pattern:
  - Uses ``AsyncSession`` from SQLAlchemy 2.x async engine.
  - Session is injected by the caller (MLLP pipeline, TASK-004) so this
    module remains independently testable.

Design refs:
    DR-022  — MSH-10 idempotency unique constraint
    US-013  — SC-2: duplicate returns AA ACK, no adt_event record created
    TR-001  — API async handlers; read replica for GET endpoints
    ADR-003 — Cloud SQL PostgreSQL as system of record
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class IdempotencyChecker:
    """Async guard that checks whether an HL7 message has already been processed.

    Usage::

        checker = IdempotencyChecker()

        async with async_session() as session:
            if await checker.is_duplicate(session, "MSG-20260714-001"):
                # Return AA ACK immediately — skip all processing
                return build_ack_response(msg_control_id)

    This class is stateless; instantiate once and reuse across requests.
    """

    async def is_duplicate(
        self,
        session: AsyncSession,
        msg_control_id: str,
    ) -> bool:
        """Check whether ``msg_control_id`` already exists in ``adt_event``.

        Uses ``SELECT EXISTS`` which short-circuits on the first matching
        index entry — O(log n) via the B-tree index on ``source_message_id``.

        Args:
            session:         SQLAlchemy async session (read-only access used).
            msg_control_id:  MSH-10 value from the incoming HL7 message.

        Returns:
            ``True``  — duplicate: ACK and skip further processing.
            ``False`` — new message: proceed with archive and publish.

        Raises:
            sqlalchemy.exc.SQLAlchemyError — propagated on DB connectivity failure.
                The MLLP pipeline (TASK-004) catches this and treats it as a
                non-duplicate (fail-open) to avoid blocking ACK indefinitely.
        """
        stmt = text(
            "SELECT EXISTS("
            "  SELECT 1 FROM adt_event"
            "  WHERE source_message_id = :msg_id"
            ")"
        )
        result = await session.execute(stmt, {"msg_id": msg_control_id})
        exists: bool = result.scalar_one()

        if exists:
            logger.info(
                "duplicate_message_skipped",
                extra={
                    "event": "duplicate_message_skipped",
                    "message_id": msg_control_id,
                },
            )
        return exists
```

---

## File Structure After This Task

```
hl7-listener/
└── app/
    └── idempotency/
        ├── __init__.py               ← exports IdempotencyChecker
        └── idempotency_checker.py    ← IdempotencyChecker ← THIS TASK
```

---

## Definition of Done Checklist (this task)

- [ ] `IdempotencyChecker.is_duplicate()` uses `SELECT EXISTS` with parameterised `:msg_id` (no string interpolation — prevents SQL injection)
- [ ] Returns `True` for a known `source_message_id`, `False` otherwise
- [ ] Emits structured `duplicate_message_skipped` log when returning `True`
- [ ] Session injected by caller (no internal session creation)
- [ ] `IdempotencyChecker` exported from `app/idempotency/__init__.py`
- [ ] No PHI values referenced or logged in this module
