---
id: TASK-002
title: "Create `coordinator-agent/app/coordinator/agent.py` and `task_mapping.py` — TransitionCoordinatorAgent with Event→Task Mapping and Atomic DB Write"
user_story: US-020
epic: EP-003
sprint: 2
layer: Backend
estimate: 3.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-020/TASK-001, US-006/TASK-001]
---

# TASK-002: Create `coordinator-agent/app/coordinator/agent.py` and `task_mapping.py` — TransitionCoordinatorAgent with Event→Task Mapping and Atomic DB Write

> **Story:** US-020 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-020 mandates (FR-004, FR-010, ADR-004):

> *"5 `AgentTask` records are created in the DB within 2 seconds; each with `status=PENDING` and correct `encounter_id`"*

`TransitionCoordinatorAgent` is the orchestration heart of SmartHandoff. It:

1. Receives a deserialized `ADTEvent` from `ADTSubscriber` (TASK-001)
2. Looks up the event-type → task-type mapping from `task_mapping.py`
3. Creates all relevant `AgentTask` ORM records in a **single atomic DB transaction**
4. Uses `ON CONFLICT (encounter_id, agent_type) DO NOTHING` to handle Pub/Sub message redeliveries idempotently (AR-008)

Design decisions encoded in this module:

| Decision | Rationale |
|----------|-----------|
| Event-type → task-type mapping in config dict | Business rule changes (e.g. new ADT event types) require only config changes, not code changes |
| Single `INSERT … RETURNING` transaction for all tasks | Atomicity: either all 5 tasks are created or none — no partial states (US-020 DoD) |
| `ON CONFLICT DO NOTHING` idempotency | Pub/Sub guarantees at-least-once; coordinator must be idempotent (AR-008, US-020 tech notes) |
| LangChain `BaseTool` not used for pure DB writes | The coordinator dispatches tasks; it does not generate AI content — LLM not needed here |
| `AgentTaskStatus.PENDING` as initial status | Downstream agents poll for PENDING tasks; coordinator sets status only — agents own transitions |

Design refs: FR-004, FR-010, ADR-001, ADR-004, TR-001, AR-008, US-020 DoD.

---

## Acceptance Criteria Addressed

| US-020 AC | Requirement |
|---|---|
| **Scenario 1** | 5 `AgentTask` records created with `status=PENDING` and correct `encounter_id` within 2 seconds of ADT^A01 receipt |
| **Scenario 2** | ADT^A02 (transfer) creates only `TRANSFER_NOTE`, `BED_MANAGEMENT`; `DISCHARGE_SUMMARY` is NOT created |
| **Scenario 3** | In-flight task creation completes; DB transaction committed; message ACK-ed before exit |
| **Scenario 4** | Idempotent: re-delivered messages hit `ON CONFLICT DO NOTHING`; no duplicate `AgentTask` rows |

---

## Implementation Steps

### 1. Create `coordinator-agent/app/coordinator/task_mapping.py`

```python
"""Event-type to agent-task-type mapping configuration.

Defines which ``AgentTaskType`` values are created for each ADT event type.
This is the sole source-of-truth for coordinator routing logic; adding a new
ADT event type or new agent only requires updating ``TASK_TYPE_MAP``.

Design refs:
    FR-010  — coordinator orchestrates task assignment to all 5 specialist agents
    US-020  — SC-2: only relevant tasks created per event type
"""
from __future__ import annotations

from enum import StrEnum


class ADTEventType(StrEnum):
    """ADT event type codes from HL7 MSH-9 message type."""

    ADMIT = "ADT^A01"
    TRANSFER = "ADT^A02"
    DISCHARGE = "ADT^A03"
    CANCEL_ADMIT = "ADT^A11"
    CANCEL_DISCHARGE = "ADT^A13"


class AgentTaskType(StrEnum):
    """Agent task type identifiers — align with downstream agent subscriptions."""

    DOCUMENTATION = "DOCUMENTATION"
    MEDICATION_RECONCILIATION = "MEDICATION_RECONCILIATION"
    BED_MANAGEMENT = "BED_MANAGEMENT"
    FOLLOW_UP_CARE = "FOLLOW_UP_CARE"
    PATIENT_COMMUNICATION = "PATIENT_COMMUNICATION"
    TRANSFER_NOTE = "TRANSFER_NOTE"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"


# ---------------------------------------------------------------------------
# Task routing map — event type → list of task types to create
# ---------------------------------------------------------------------------

TASK_TYPE_MAP: dict[ADTEventType, list[AgentTaskType]] = {
    ADTEventType.ADMIT: [
        AgentTaskType.DOCUMENTATION,
        AgentTaskType.MEDICATION_RECONCILIATION,
        AgentTaskType.BED_MANAGEMENT,
        AgentTaskType.FOLLOW_UP_CARE,
        AgentTaskType.PATIENT_COMMUNICATION,
    ],
    ADTEventType.TRANSFER: [
        AgentTaskType.TRANSFER_NOTE,
        AgentTaskType.BED_MANAGEMENT,
    ],
    ADTEventType.DISCHARGE: [
        AgentTaskType.DISCHARGE_SUMMARY,
        AgentTaskType.MEDICATION_RECONCILIATION,
        AgentTaskType.FOLLOW_UP_CARE,
        AgentTaskType.PATIENT_COMMUNICATION,
    ],
    ADTEventType.CANCEL_ADMIT: [
        AgentTaskType.BED_MANAGEMENT,
    ],
    ADTEventType.CANCEL_DISCHARGE: [
        AgentTaskType.BED_MANAGEMENT,
        AgentTaskType.FOLLOW_UP_CARE,
    ],
}


def get_task_types_for_event(event_type: str) -> list[AgentTaskType]:
    """Return the list of ``AgentTaskType`` values for a given ADT event type.

    Args:
        event_type: ADT event type string, e.g. ``"ADT^A01"``.

    Returns:
        List of ``AgentTaskType`` enum members. Returns empty list for
        unrecognised event types (no tasks created — logged as warning).
    """
    try:
        adt_type = ADTEventType(event_type)
    except ValueError:
        return []
    return TASK_TYPE_MAP.get(adt_type, [])
```

### 2. Create `coordinator-agent/app/coordinator/agent.py`

```python
"""Transition Coordinator Agent — orchestrates AgentTask creation on ADT events.

Receives a validated ``ADTEvent``, maps the event type to the set of
``AgentTaskType`` values, then creates all ``AgentTask`` ORM records in a
single atomic database transaction.

Idempotency:
  The upsert strategy uses ``INSERT … ON CONFLICT (encounter_id, agent_type)
  DO NOTHING`` so that redelivered Pub/Sub messages do not create duplicate
  tasks (AR-008, US-020 technical notes).

Latency target:
  Task creation p95 <2 seconds from Pub/Sub message receipt (FR-004,
  US-020 SC-1). The coordinator performs only DB writes — no LLM calls —
  keeping the hot path synchronous with the asyncio event loop.

Design refs:
    FR-004   — trigger agent workflow within 2 seconds of ADT event
    FR-010   — coordinator orchestrates task assignment across 5 specialist agents
    ADR-001  — coordinator is a Pub/Sub consumer; downstream agents are too
    TR-001   — API/DB response p95 <500ms; avoid N+1 (selectinload)
    AR-008   — idempotency guard for duplicate Pub/Sub deliveries
    US-020   — SC-1 to SC-4, DoD
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.coordinator.task_mapping import AgentTaskType, get_task_types_for_event

if TYPE_CHECKING:
    from app.models.adt_event import ADTEvent
    from app.models.agent_task import AgentTask  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

COORDINATOR_TASKS_CREATED = Counter(
    "coordinator_agent_tasks_created_total",
    "Total AgentTask records created by event type",
    ["event_type"],
)

COORDINATOR_LATENCY = Histogram(
    "coordinator_task_creation_latency_seconds",
    "Latency from Pub/Sub message receipt to all AgentTask rows committed",
    buckets=[0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0],
)


# ---------------------------------------------------------------------------
# TransitionCoordinatorAgent
# ---------------------------------------------------------------------------


class TransitionCoordinatorAgent:
    """Orchestrates ``AgentTask`` creation for every incoming ADT event.

    Args:
        db_session: ``AsyncSession`` factory (callable returning
            ``AsyncSession`` context manager). Injected at construction so
            the coordinator is testable without a live database.

    Example::

        agent = TransitionCoordinatorAgent(db_session=async_session_factory)
        await agent.process_event(adt_event)
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self._db_session = db_session

    async def process_event(self, event: "ADTEvent") -> int:
        """Create ``AgentTask`` records for all task types mapped to ``event``.

        Performs a single ``INSERT … ON CONFLICT DO NOTHING`` statement that
        inserts all task rows atomically. Returns the number of tasks actually
        inserted (may be 0 for redelivered messages that already have rows).

        Args:
            event: Validated ``ADTEvent`` from the Pub/Sub subscriber.

        Returns:
            Number of ``AgentTask`` rows inserted (0 on idempotent replay).

        Raises:
            sqlalchemy.exc.SQLAlchemyError: On DB connection/constraint errors
                (propagated so the Pub/Sub subscriber can NACK the message).
        """
        start = time.monotonic()

        task_types: list[AgentTaskType] = get_task_types_for_event(
            event.event_type.value
        )

        if not task_types:
            logger.warning(
                "coordinator_no_tasks_mapped",
                extra={
                    "encounter_id": str(event.encounter_id),
                    "event_type": event.event_type.value,
                },
            )
            return 0

        rows_inserted = await self._create_tasks_atomically(event, task_types)

        elapsed = time.monotonic() - start
        COORDINATOR_LATENCY.observe(elapsed)
        COORDINATOR_TASKS_CREATED.labels(
            event_type=event.event_type.value
        ).inc(rows_inserted)

        logger.info(
            "coordinator_tasks_created",
            extra={
                "encounter_id": str(event.encounter_id),
                "event_type": event.event_type.value,
                "tasks_inserted": rows_inserted,
                "latency_seconds": round(elapsed, 4),
            },
        )

        return rows_inserted

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _create_tasks_atomically(
        self,
        event: "ADTEvent",
        task_types: list[AgentTaskType],
    ) -> int:
        """Execute a single INSERT … ON CONFLICT DO NOTHING for all task rows.

        All rows share the same ``encounter_id`` and ``status=PENDING``.
        The conflict target is ``(encounter_id, agent_type)`` — the unique
        constraint defined on the ``agent_task`` table (US-006).

        Returns the count of rows actually inserted (not skipped by conflict).
        """
        from app.models.agent_task import AgentTask  # noqa: PLC0415

        task_values = [
            {
                "encounter_id": event.encounter_id,
                "agent_type": task_type.value,
                "status": "PENDING",
                "event_type": event.event_type.value,
            }
            for task_type in task_types
        ]

        async with self._db_session() as session:
            async with session.begin():
                stmt = (
                    pg_insert(AgentTask)
                    .values(task_values)
                    .on_conflict_do_nothing(
                        index_elements=["encounter_id", "agent_type"]
                    )
                    .returning(AgentTask.id)
                )
                result = await session.execute(stmt)
                return len(result.fetchall())
```

---

## Validation

Run from `coordinator-agent/`:

```bash
# 1. Syntax check — both files
for f in app/coordinator/task_mapping.py app/coordinator/agent.py; do
  python -c "
import ast, pathlib
ast.parse(pathlib.Path('$f').read_text())
print('Syntax check $f: PASSED')
"
done

# 2. Task mapping — admit creates 5 tasks
python -c "
from app.coordinator.task_mapping import get_task_types_for_event, AgentTaskType
tasks = get_task_types_for_event('ADT^A01')
assert len(tasks) == 5, f'Expected 5 admit tasks, got {len(tasks)}'
print(f'ADT^A01 tasks ({len(tasks)}): PASSED')
"

# 3. Task mapping — transfer does NOT include DISCHARGE_SUMMARY
python -c "
from app.coordinator.task_mapping import get_task_types_for_event, AgentTaskType
tasks = get_task_types_for_event('ADT^A02')
assert AgentTaskType.DISCHARGE_SUMMARY not in tasks, 'DISCHARGE_SUMMARY must not be in transfer tasks'
assert AgentTaskType.BED_MANAGEMENT in tasks, 'BED_MANAGEMENT must be in transfer tasks'
print('ADT^A02 transfer task filter: PASSED')
"

# 4. Unknown event type returns empty list
python -c "
from app.coordinator.task_mapping import get_task_types_for_event
result = get_task_types_for_event('ADT^A99')
assert result == [], f'Expected [], got {result}'
print('Unknown event type returns []: PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `coordinator-agent/app/coordinator/__init__.py` |
| CREATE | `coordinator-agent/app/coordinator/task_mapping.py` |
| CREATE | `coordinator-agent/app/coordinator/agent.py` |

---

## Definition of Done Checklist

- [ ] `get_task_types_for_event("ADT^A01")` returns exactly 5 task types
- [ ] `get_task_types_for_event("ADT^A02")` does NOT include `DISCHARGE_SUMMARY`
- [ ] `get_task_types_for_event("ADT^A99")` returns `[]` without raising
- [ ] `TransitionCoordinatorAgent.process_event()` creates all tasks in a single DB transaction
- [ ] `INSERT … ON CONFLICT (encounter_id, agent_type) DO NOTHING` — no duplicate rows on replay
- [ ] `COORDINATOR_LATENCY` Prometheus histogram records latency per call
- [ ] `COORDINATOR_TASKS_CREATED` counter incremented by number of rows inserted
- [ ] No PHI in structured log fields (only `encounter_id` UUID, `event_type`, counts)
- [ ] `AgentTask` rows created with `status="PENDING"` as initial value
