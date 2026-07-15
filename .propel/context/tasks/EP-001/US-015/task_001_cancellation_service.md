---
id: TASK-001
title: "Create `api-gateway/app/services/cancellation_service.py` — CancellationService with Atomic Task Cancellation & Encounter Status Revert"
user_story: US-015
epic: EP-001
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-006/TASK-001, US-015/TASK-002]
---

# TASK-001: Create `api-gateway/app/services/cancellation_service.py` — CancellationService with Atomic Task Cancellation & Encounter Status Revert

> **Story:** US-015 | **Epic:** EP-001 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-015 mandates (FR-006, UC-017):

> *"Handle HL7 cancellation events (A11, A12, A13) by halting in-progress agent workflows and reverting the encounter status."*

US-015 Technical Notes specify:

> *"Use database transaction to ensure encounter status update + task cancellations are atomic."*

`CancellationService` is the single backend component responsible for:

1. **Atomically** updating all non-terminal `AgentTask` records to `CANCELLED` within the same transaction that reverts the encounter status.
2. Routing to the correct revert handler based on cancellation event type (A11, A12, A13).
3. Soft-cancelling related `Document` records — setting `status=CANCELLED` without deleting content (DoD: "Cancelled documents retain their content with `status=CANCELLED` — no hard delete").
4. Persisting the source `ADTEvent` record with `status=CANCELLED` for audit.

The transaction boundary is critical: if the encounter status revert succeeds but task cancellations fail (or vice versa), the system would be in an inconsistent state where agents continue processing an encounter that was cancelled. A single SQLAlchemy async session wrapping both operations prevents this.

After the transaction commits, downstream side effects (Pub/Sub `WORKFLOW_CANCELLED` event + SignalR notification) are dispatched as async background tasks by the caller (TASK-003) — not within the transaction itself.

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `cancel_agent_tasks()` bulk-updates via `UPDATE ... WHERE encounter_id=:id AND status NOT IN ('CANCELLED', 'COMPLETED', 'FAILED')` | Avoids row-by-row updates; excludes terminal statuses so already-finished tasks are not re-written (idempotency) |
| Single DB session for encounter + tasks | Atomic — both succeed or both roll back (US-015 Technical Notes) |
| Separate handlers `handle_cancel_admit`, `handle_cancel_transfer`, `handle_cancel_discharge` | Each cancellation type reverts different fields; separate methods improve testability and state machine clarity |
| Soft-cancel documents (status=CANCELLED, content retained) | DoD requirement: "no hard delete"; documents may be needed for audit/compliance review |
| `cancel_agent_tasks()` returns the count of rows updated | Enables the caller to log a structured metric: `agent_tasks_cancelled_total{event_type=A11}` |

Design refs: FR-006, DR-005, DR-023, UC-017, US-015 DoD, US-015 Technical Notes.

---

## Acceptance Criteria Addressed

| US-015 AC | Requirement |
|---|---|
| **Scenario 1 (A11)** | `handle_cancel_admit()` updates all 5 `AgentTask` records to `CANCELLED`; encounter status reverts to `PRE_ADMISSION`; both within one transaction |
| **Scenario 2 (A12)** | `handle_cancel_transfer()` reverts `encounter.current_unit` to previous unit; transfer record marked `CANCELLED`; in-progress Transfer-Note tasks cancelled |
| **Scenario 3 (A13)** | `handle_cancel_discharge()` reverts encounter status to `ADMITTED`; discharge documents soft-cancelled (status=CANCELLED, content intact) |
| **Scenario 4 (unknown)** | Callers that cannot find the encounter raise `EncounterNotFoundError` before calling service; service itself does not need to handle this case — enforced at handler layer (TASK-004) |
| **DoD** | `cancel_agent_tasks()` updates all non-terminal tasks; documents retain content with status=CANCELLED; atomic DB transaction |

---

## Implementation Steps

### 1. Scaffold the service

```
api-gateway/
└── app/
    └── services/
        ├── __init__.py           (existing)
        └── cancellation_service.py   ← THIS TASK
```

### 2. Create `api-gateway/app/services/cancellation_service.py`

```python
"""Cancellation service — handles A11, A12, A13 ADT cancellation events.

Atomically reverts encounter status and cancels all non-terminal agent tasks
within a single SQLAlchemy async session (one transaction).

Public API:
  CancellationService.handle_cancel_admit(encounter_id, db)
      A11: ADMITTED → PRE_ADMISSION; cancel pending/in-progress AgentTasks;
      soft-cancel documents with task_type matching the cancelled encounter.

  CancellationService.handle_cancel_transfer(encounter_id, db)
      A12: TRANSFERRED → ADMITTED; revert current_unit to previous_unit;
      cancel in-progress Transfer-Note agent tasks.

  CancellationService.handle_cancel_discharge(encounter_id, db)
      A13: DISCHARGED → ADMITTED; soft-cancel discharge documents
      (status=CANCELLED, content retained); permit re-admission.

  CancellationService.cancel_agent_tasks(encounter_id, db) -> int
      Bulk-update all non-terminal AgentTask records to CANCELLED.
      Returns the number of rows updated.

Transaction contract:
  Each public method executes within a SINGLE database transaction.
  The caller MUST commit (or the session auto-commits with async context
  manager). If any step raises, the whole transaction rolls back.

PHI safety (ADR-007):
  No PHI fields (patient name, MRN, DOB) are read or logged by this service.
  Only encounter_id (UUID), task_id (UUID), and status strings are used.

Design refs:
    FR-006   — handle A11, A12, A13; halt in-progress agent workflows
    DR-005   — soft deletes; no hard delete on encounter or document records
    DR-023   — encounter state machine: invalid transitions rejected (409)
    US-015   — SC-1, SC-2, SC-3, DoD
    US-006   — encounter, agent_task, document ORM models
"""
from __future__ import annotations

import logging
from typing import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.document import Document, DocumentStatus
from app.models.encounter import Encounter, EncounterStatus
from app.exceptions import EncounterNotFoundError, EncounterStateTransitionError

logger = logging.getLogger(__name__)

# Statuses that are already terminal — do not overwrite with CANCELLED
_TERMINAL_TASK_STATUSES: frozenset[AgentTaskStatus] = frozenset(
    {AgentTaskStatus.COMPLETED, AgentTaskStatus.CANCELLED, AgentTaskStatus.FAILED}
)


class CancellationService:
    """Service for processing ADT cancellation events (A11, A12, A13).

    All public methods accept an ``AsyncSession`` and must be called within
    an active transaction context (use ``async with session.begin()`` in the
    caller, or rely on a FastAPI dependency that manages the session lifecycle).
    """

    # ------------------------------------------------------------------
    # A11: Cancel Admit
    # ------------------------------------------------------------------

    async def handle_cancel_admit(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> CancellationResult:
        """Handle A11 — cancel admit.

        Transitions: ADMITTED → PRE_ADMISSION.
        Cancels all non-terminal AgentTask records for the encounter.
        Soft-cancels any documents linked to the encounter.

        Args:
            encounter_id: UUID of the encounter being cancelled.
            db: Active SQLAlchemy async session (caller owns transaction).

        Returns:
            CancellationResult with encounter_id, tasks_cancelled count,
            docs_cancelled count.

        Raises:
            EncounterNotFoundError: If encounter_id does not exist.
            EncounterStateTransitionError: If encounter status is not ADMITTED.
        """
        encounter = await self._get_encounter(encounter_id, db)
        encounter.transition_to(EncounterStatus.PRE_ADMISSION)  # state machine validation

        tasks_cancelled = await self.cancel_agent_tasks(encounter_id, db)
        docs_cancelled = await self._soft_cancel_documents(encounter_id, db)

        logger.info(
            "cancellation_service.a11_handled",
            extra={
                "encounter_id": str(encounter_id),
                "tasks_cancelled": tasks_cancelled,
                "docs_cancelled": docs_cancelled,
                "new_status": EncounterStatus.PRE_ADMISSION.value,
            },
        )
        return CancellationResult(
            encounter_id=encounter_id,
            event_type="A11",
            tasks_cancelled=tasks_cancelled,
            docs_cancelled=docs_cancelled,
        )

    # ------------------------------------------------------------------
    # A12: Cancel Transfer
    # ------------------------------------------------------------------

    async def handle_cancel_transfer(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> CancellationResult:
        """Handle A12 — cancel transfer.

        Transitions: TRANSFERRED → ADMITTED.
        Reverts current_unit to previous_unit on the encounter.
        Cancels in-progress Transfer-Note agent tasks.

        Raises:
            EncounterNotFoundError: If encounter_id does not exist.
            EncounterStateTransitionError: If encounter status is not TRANSFERRED.
        """
        encounter = await self._get_encounter(encounter_id, db)
        previous_unit = encounter.previous_unit

        encounter.transition_to(EncounterStatus.ADMITTED)
        encounter.current_unit = previous_unit  # revert unit assignment

        tasks_cancelled = await self.cancel_agent_tasks(encounter_id, db)

        logger.info(
            "cancellation_service.a12_handled",
            extra={
                "encounter_id": str(encounter_id),
                "reverted_to_unit": str(previous_unit) if previous_unit else None,
                "tasks_cancelled": tasks_cancelled,
            },
        )
        return CancellationResult(
            encounter_id=encounter_id,
            event_type="A12",
            tasks_cancelled=tasks_cancelled,
            docs_cancelled=0,
        )

    # ------------------------------------------------------------------
    # A13: Cancel Discharge
    # ------------------------------------------------------------------

    async def handle_cancel_discharge(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> CancellationResult:
        """Handle A13 — cancel discharge.

        Transitions: DISCHARGED → ADMITTED.
        Soft-cancels discharge document records (status=CANCELLED, content
        retained — DoD requirement: no hard delete).

        Raises:
            EncounterNotFoundError: If encounter_id does not exist.
            EncounterStateTransitionError: If encounter status is not DISCHARGED.
        """
        encounter = await self._get_encounter(encounter_id, db)
        encounter.transition_to(EncounterStatus.ADMITTED)

        docs_cancelled = await self._soft_cancel_documents(encounter_id, db)

        logger.info(
            "cancellation_service.a13_handled",
            extra={
                "encounter_id": str(encounter_id),
                "new_status": EncounterStatus.ADMITTED.value,
                "docs_cancelled": docs_cancelled,
            },
        )
        return CancellationResult(
            encounter_id=encounter_id,
            event_type="A13",
            tasks_cancelled=0,
            docs_cancelled=docs_cancelled,
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def cancel_agent_tasks(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> int:
        """Bulk-update all non-terminal AgentTask records to CANCELLED.

        Uses a single UPDATE statement for efficiency; avoids row-by-row
        fetching.  Excludes tasks that are already in a terminal status
        (COMPLETED, CANCELLED, FAILED) to maintain idempotency.

        Args:
            encounter_id: UUID of the encounter whose tasks are to be cancelled.
            db: Active SQLAlchemy async session.

        Returns:
            Number of rows updated (0 if no non-terminal tasks exist).
        """
        non_terminal_values = [s.value for s in AgentTaskStatus if s not in _TERMINAL_TASK_STATUSES]
        result = await db.execute(
            update(AgentTask)
            .where(
                AgentTask.encounter_id == encounter_id,
                AgentTask.status.in_(non_terminal_values),
            )
            .values(status=AgentTaskStatus.CANCELLED.value)
            .execution_options(synchronize_session="fetch")
        )
        rows_updated: int = result.rowcount
        return rows_updated

    async def _soft_cancel_documents(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> int:
        """Soft-cancel all non-cancelled Document records for an encounter.

        Sets Document.status = CANCELLED.  Document.content is NEVER deleted
        (DoD: "Cancelled documents retain their content — no hard delete").

        Returns:
            Number of document records updated.
        """
        result = await db.execute(
            update(Document)
            .where(
                Document.encounter_id == encounter_id,
                Document.status != DocumentStatus.CANCELLED,
            )
            .values(status=DocumentStatus.CANCELLED)
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount

    async def _get_encounter(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> Encounter:
        """Fetch encounter by ID; raise EncounterNotFoundError if missing."""
        result = await db.execute(
            select(Encounter).where(Encounter.id == encounter_id)
        )
        encounter = result.scalar_one_or_none()
        if encounter is None:
            raise EncounterNotFoundError(encounter_id=encounter_id)
        return encounter


# ------------------------------------------------------------------
# Result dataclass
# ------------------------------------------------------------------

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CancellationResult:
    """Immutable result returned by CancellationService public methods."""

    encounter_id: UUID
    event_type: str          # "A11" | "A12" | "A13"
    tasks_cancelled: int
    docs_cancelled: int
```

### 3. Create `api-gateway/app/exceptions.py` entries (extend if file already exists)

Add the two exceptions if not already present:

```python
class EncounterNotFoundError(Exception):
    """Raised when an encounter_id does not exist in the database."""

    def __init__(self, encounter_id: "UUID") -> None:
        self.encounter_id = encounter_id
        super().__init__(f"Encounter not found: {encounter_id}")


class EncounterStateTransitionError(Exception):
    """Raised when an encounter status transition is not permitted.

    Maps to HTTP 409 Conflict at the API layer.
    """

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Invalid encounter state transition: {current} → {target}"
        )
```

### 4. Verify module imports cleanly

```bash
cd api-gateway
python -c "
from app.services.cancellation_service import CancellationService, CancellationResult
print('CancellationService import: OK')
"
```

---

## Definition of Done Checklist

- [ ] `CancellationService` class implemented with `handle_cancel_admit`, `handle_cancel_transfer`, `handle_cancel_discharge`, `cancel_agent_tasks`
- [ ] `cancel_agent_tasks()` uses bulk `UPDATE` (not row-by-row)
- [ ] `cancel_agent_tasks()` excludes terminal statuses (COMPLETED, CANCELLED, FAILED)
- [ ] `_soft_cancel_documents()` sets status=CANCELLED; content column not modified
- [ ] `CancellationResult` dataclass returned by all three handlers
- [ ] `EncounterNotFoundError` and `EncounterStateTransitionError` defined in `app/exceptions.py`
- [ ] No PHI fields (patient name, MRN, DOB) read or logged — only UUIDs and status strings
- [ ] Module imports without error

---

## Structured Log Fields

All log entries emitted by `CancellationService` must use these field names (Cloud Monitoring alert patterns):

| Field | Type | Example |
|---|---|---|
| `encounter_id` | string (UUID) | `"3fa85f64-5717-4562-b3fc-2c963f66afa6"` |
| `tasks_cancelled` | int | `5` |
| `docs_cancelled` | int | `2` |
| `new_status` | string | `"PRE_ADMISSION"` |
| `event_type` | string | `"A11"` |

No patient name, MRN, DOB, or other PHI fields are included in any log entry.
