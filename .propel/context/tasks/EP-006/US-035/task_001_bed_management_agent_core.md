---
id: TASK-001
title: "BedManagementAgent — ADT Event Consumer and Bed Status State Machine"
user_story: US-035
epic: EP-006
sprint: 2
layer: Backend / AI Agent
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-024, US-006]
---

# TASK-001: BedManagementAgent — ADT Event Consumer and Bed Status State Machine

> **Story:** US-035 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-035 requires a `BedManagementAgent` that subscribes to the `adt-events` Pub/Sub topic and updates bed status in response to ADT admission, transfer, and discharge events. This task implements the agent shell, the bed status state machine (VACANT → OCCUPIED → DIRTY), and the DB write logic.

`BaseAgent` is provided by US-024. The `bed` ORM model and `mv_bed_board` materialised view are provisioned by US-006 and US-009 respectively.

**Design references:**
- design.md §3.1 — Bed Management Agent responsibility
- design.md §3.2 — Agent container pattern (LangChain, Pub/Sub subscription)
- design.md §9.2 — Cloud Run config: `bed-mgmt-agent`, min=1, max=5, 1 vCPU, 1 GB
- US-035 Technical Notes — status enum; CONCURRENTLY refresh wired post-update
- ADR-001 — Each agent subscribes on a dedicated Pub/Sub subscription with its own DLQ
- ADR-004 — LangChain as agent framework

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | A01 event → bed transitions to OCCUPIED within 60 s; mv_bed_board refreshed |
| Scenario 2 | A03 event → bed transitions to DIRTY within 60 s |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p backend/app/agents/bed_management
touch backend/app/agents/bed_management/__init__.py
touch backend/app/agents/bed_management/agent.py
touch backend/app/agents/bed_management/status_machine.py
touch backend/app/agents/bed_management/schemas.py
```

### 2. Implement `backend/app/agents/bed_management/schemas.py`

```python
"""Pydantic schemas for BedManagementAgent structured output.

Design refs:
    US-035 AC Scenarios 1, 2
    ADR-004  — structured Pydantic output enforced for all agents
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BedStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    DIRTY = "DIRTY"
    MAINTENANCE = "MAINTENANCE"
    RESERVED = "RESERVED"


class BedStatusUpdateResult(BaseModel):
    """Structured output produced after each bed status transition."""

    bed_id: str = Field(..., description="UUID of the bed record updated")
    previous_status: BedStatus
    new_status: BedStatus
    encounter_id: str = Field(..., description="Encounter UUID that triggered the update")
    event_type: str = Field(..., description="HL7 ADT event type: A01, A02, or A03")
    housekeeping_notification_published: bool = False
    mv_refresh_triggered: bool = False
```

### 3. Implement `backend/app/agents/bed_management/status_machine.py`

```python
"""Bed status state machine for ADT event-driven transitions.

Enforces allowed status transitions per event type:
    A01 (admit)     : any → OCCUPIED
    A02 (transfer)  : old bed OCCUPIED → DIRTY; new bed any → OCCUPIED
    A03 (discharge) : OCCUPIED → DIRTY

Design refs:
    US-035 Technical Notes — status enum and transition rules
    US-035 AC Scenario 1   — A01 → OCCUPIED
    US-035 AC Scenario 2   — A03 → DIRTY
"""
from __future__ import annotations

import logging

from app.agents.bed_management.schemas import BedStatus
from app.exceptions import BedStatusTransitionError

logger = logging.getLogger(__name__)

# Mapping: event_type → (required current statuses, target status)
# None in current_statuses means any status is valid (e.g. force-admit)
_TRANSITION_MAP: dict[str, tuple[set[BedStatus] | None, BedStatus]] = {
    "A01": (None, BedStatus.OCCUPIED),           # admit — any → OCCUPIED
    "A03": ({BedStatus.OCCUPIED}, BedStatus.DIRTY),  # discharge — OCCUPIED → DIRTY
}


def resolve_target_status(event_type: str, current_status: BedStatus) -> BedStatus:
    """Return the target BedStatus for a given ADT event type.

    Args:
        event_type: HL7 ADT message type (e.g. ``"A01"``).
        current_status: The bed's current status before the event.

    Returns:
        Target ``BedStatus`` after the transition.

    Raises:
        BedStatusTransitionError: If the transition is not permitted.
        ValueError: If the ``event_type`` is not handled by this agent.
    """
    if event_type not in _TRANSITION_MAP and event_type != "A02":
        raise ValueError(f"BedManagementAgent does not handle event type: {event_type}")

    if event_type == "A02":
        # A02 (transfer): handled separately — two bed updates required
        return BedStatus.OCCUPIED

    allowed_current, target = _TRANSITION_MAP[event_type]
    if allowed_current is not None and current_status not in allowed_current:
        raise BedStatusTransitionError(
            f"Cannot transition bed from {current_status} via {event_type}. "
            f"Allowed current statuses: {allowed_current}"
        )
    logger.debug(
        "Bed status transition approved: %s → %s (event=%s)",
        current_status,
        target,
        event_type,
    )
    return target
```

### 4. Implement `backend/app/agents/bed_management/agent.py`

```python
"""BedManagementAgent — processes ADT events and updates bed status.

Subscribes to the ``adt-events`` Pub/Sub topic via ``bed-mgmt-agent-sub``.
Handles A01 (admit), A02 (transfer), and A03 (discharge) events, writing
bed status changes to the primary DB and triggering a CONCURRENTLY
materialised-view refresh via the BedBoardRefreshService (TASK-002).

Design refs:
    US-035 AC Scenarios 1, 2
    design.md §3.1  — Bed Management Agent responsibility
    design.md §3.2  — Agent container pattern
    ADR-001         — dedicated Pub/Sub subscription per agent
    ADR-004         — LangChain agent framework; Pydantic structured output
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent, RetryableError
from app.agents.bed_management.schemas import BedStatus, BedStatusUpdateResult
from app.agents.bed_management.status_machine import resolve_target_status
from app.exceptions import BedStatusTransitionError
from app.models.bed import Bed
from app.models.agent_task import AgentTask, AgentTaskStatus

logger = logging.getLogger(__name__)


class BedManagementAgent(BaseAgent):
    """Processes A01/A02/A03 ADT events and updates bed status.

    Inherits Pub/Sub consumption, retry, DLQ handling, and cancellation
    flag checking from ``BaseAgent`` (US-024).

    Args:
        db_session_factory: Async SQLAlchemy session factory (write session).
        refresh_service: ``BedBoardRefreshService`` instance (TASK-002).
        housekeeping_notifier: ``HousekeepingNotifier`` instance (TASK-004).
    """

    HANDLED_EVENT_TYPES = frozenset({"A01", "A02", "A03"})

    def __init__(
        self,
        db_session_factory: Any,
        refresh_service: Any,
        housekeeping_notifier: Any,
    ) -> None:
        super().__init__(subscription_id="bed-mgmt-agent-sub")
        self._db_session_factory = db_session_factory
        self._refresh_service = refresh_service
        self._housekeeping_notifier = housekeeping_notifier

    async def process(self, message: dict[str, Any]) -> BedStatusUpdateResult:
        """Handle a single ADT event message from Pub/Sub.

        Args:
            message: Decoded Pub/Sub message payload containing at minimum
                ``event_type``, ``encounter_id``, ``bed_id``, and for A02
                also ``previous_bed_id``.

        Returns:
            ``BedStatusUpdateResult`` describing the completed transition.

        Raises:
            RetryableError: On transient DB failures.
            BedStatusTransitionError: On invalid state transitions (non-retryable).
        """
        event_type: str = message["event_type"]
        encounter_id: str = message["encounter_id"]

        if event_type not in self.HANDLED_EVENT_TYPES:
            logger.debug(
                "Skipping unhandled event type=%s encounter_id=%s",
                event_type,
                encounter_id,
            )
            return None  # type: ignore[return-value]

        logger.info(
            "Processing event_type=%s encounter_id=%s",
            event_type,
            encounter_id,
        )

        async with self._db_session_factory() as session:
            try:
                result = await self._handle_event(session, event_type, encounter_id, message)
                await session.commit()
            except BedStatusTransitionError:
                # Non-retryable: log and ack (do not DLQ for invalid transitions)
                logger.warning(
                    "Invalid bed status transition encounter_id=%s event_type=%s",
                    encounter_id,
                    event_type,
                )
                await session.rollback()
                raise
            except Exception as exc:
                await session.rollback()
                raise RetryableError(f"DB error processing {event_type}: {exc}") from exc

        # Post-commit side effects (non-transactional)
        await self._refresh_service.refresh_async()
        result = result.model_copy(update={"mv_refresh_triggered": True})

        if event_type == "A03":
            await self._housekeeping_notifier.notify(
                bed_id=result.bed_id,
                encounter_id=encounter_id,
            )
            result = result.model_copy(update={"housekeeping_notification_published": True})

        return result

    async def _handle_event(
        self,
        session: AsyncSession,
        event_type: str,
        encounter_id: str,
        message: dict[str, Any],
    ) -> BedStatusUpdateResult:
        """Dispatch to the appropriate event handler.

        A02 requires updating two beds: the previous bed (→ DIRTY) and the
        new assigned bed (→ OCCUPIED).
        """
        if event_type == "A02":
            return await self._handle_transfer(session, encounter_id, message)
        return await self._handle_single_bed_transition(
            session, event_type, encounter_id, message
        )

    async def _handle_single_bed_transition(
        self,
        session: AsyncSession,
        event_type: str,
        encounter_id: str,
        message: dict[str, Any],
    ) -> BedStatusUpdateResult:
        """Handle A01 or A03 — single bed status update."""
        bed_id: str = message["bed_id"]
        bed = await self._fetch_bed(session, bed_id)
        current_status = BedStatus(bed.status)
        target_status = resolve_target_status(event_type, current_status)

        await session.execute(
            update(Bed)
            .where(Bed.id == uuid.UUID(bed_id))
            .values(status=target_status.value)
        )

        return BedStatusUpdateResult(
            bed_id=bed_id,
            previous_status=current_status,
            new_status=target_status,
            encounter_id=encounter_id,
            event_type=event_type,
        )

    async def _handle_transfer(
        self,
        session: AsyncSession,
        encounter_id: str,
        message: dict[str, Any],
    ) -> BedStatusUpdateResult:
        """Handle A02 — mark previous bed DIRTY, new bed OCCUPIED."""
        previous_bed_id: str = message["previous_bed_id"]
        new_bed_id: str = message["bed_id"]

        # Previous bed → DIRTY
        await session.execute(
            update(Bed)
            .where(Bed.id == uuid.UUID(previous_bed_id))
            .values(status=BedStatus.DIRTY.value)
        )
        # New bed → OCCUPIED
        await session.execute(
            update(Bed)
            .where(Bed.id == uuid.UUID(new_bed_id))
            .values(status=BedStatus.OCCUPIED.value)
        )

        return BedStatusUpdateResult(
            bed_id=new_bed_id,
            previous_status=BedStatus.OCCUPIED,
            new_status=BedStatus.OCCUPIED,
            encounter_id=encounter_id,
            event_type="A02",
        )

    async def _fetch_bed(self, session: AsyncSession, bed_id: str) -> Bed:
        """Load bed record; raises RetryableError if not found."""
        result = await session.execute(select(Bed).where(Bed.id == uuid.UUID(bed_id)))
        bed = result.scalar_one_or_none()
        if bed is None:
            raise RetryableError(f"Bed not found: {bed_id}")
        return bed
```

### 5. Add `BedStatusTransitionError` to `backend/app/exceptions.py`

```python
class BedStatusTransitionError(ValueError):
    """Raised when a bed status transition is not permitted."""
```

### 6. Register subscription in Cloud Run entrypoint

In `backend/app/agents/bed_management/main.py` (Cloud Run service entrypoint):

```python
"""Cloud Run entrypoint for the Bed Management Agent service."""
import asyncio
import logging

from app.agents.bed_management.agent import BedManagementAgent
from app.agents.bed_management.refresh_service import BedBoardRefreshService
from app.agents.bed_management.notifier import HousekeepingNotifier
from app.core.dependencies import get_write_db, get_pubsub_client

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    refresh_service = BedBoardRefreshService()
    housekeeping_notifier = HousekeepingNotifier(pubsub_client=get_pubsub_client())
    agent = BedManagementAgent(
        db_session_factory=get_write_db,
        refresh_service=refresh_service,
        housekeeping_notifier=housekeeping_notifier,
    )
    await agent.run()  # BaseAgent pull loop


if __name__ == "__main__":
    asyncio.run(main())
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/bed_management/__init__.py` | Create (empty) |
| `backend/app/agents/bed_management/schemas.py` | Create |
| `backend/app/agents/bed_management/status_machine.py` | Create |
| `backend/app/agents/bed_management/agent.py` | Create |
| `backend/app/agents/bed_management/main.py` | Create |
| `backend/app/exceptions.py` | Update — add `BedStatusTransitionError` |

---

## Validation

- [ ] `resolve_target_status("A01", BedStatus.VACANT)` returns `BedStatus.OCCUPIED`
- [ ] `resolve_target_status("A03", BedStatus.OCCUPIED)` returns `BedStatus.DIRTY`
- [ ] `resolve_target_status("A03", BedStatus.VACANT)` raises `BedStatusTransitionError`
- [ ] Agent skips silently (returns `None`) for unhandled event types (e.g. A08)
- [ ] A02 handler updates two bed records within a single DB transaction
- [ ] No PHI in any log line — only `encounter_id` (UUID) and `event_type` logged
- [ ] `BedStatusUpdateResult` is fully serialisable to JSON (Pydantic)

---

## Definition of Done

- [ ] `BedManagementAgent` implemented, extending `BaseAgent`
- [ ] A01/A02/A03 status transitions wired and tested
- [ ] `BedStatusTransitionError` added to exception registry
- [ ] `mv_refresh_triggered` and `housekeeping_notification_published` set correctly in result
- [ ] Code peer-reviewed before merge
