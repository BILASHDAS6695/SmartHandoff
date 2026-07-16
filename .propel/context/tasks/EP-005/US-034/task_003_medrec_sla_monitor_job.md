---
id: TASK-003
title: "Implement `MedRecSLAMonitor` — 24-Hour Admission SLA Check Added to Existing APScheduler Instance"
user_story: US-034
epic: EP-005
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-034/TASK-001, US-034/TASK-002, US-021/TASK-003]
---

# TASK-003: Implement `MedRecSLAMonitor` — 24-Hour Admission SLA Check Added to Existing APScheduler Instance

> **Story:** US-034 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-034 mandates:

> *"SLA monitor is the same APScheduler instance as US-021 (coordinator SLA) — add a medication-specific check to the same scheduler"*

This task adds a **second job** to the existing `AsyncIOScheduler` started by `SLAMonitor` (US-021/TASK-003). The new job `_check_medrec_admission_sla` runs every 5 minutes and:

1. Queries `AgentTask` records where `agent_type = 'MEDICATION_RECONCILIATION'` AND `status IN ('IN_PROGRESS', 'PENDING')` AND `sla_escalation_sent_at IS NULL`.
2. Joins to `Encounter` to retrieve `admit_time` (the SLA start time per US-034 Technical Notes).
3. For each task where `NOW() - encounter.admit_time >= 24 hours`, delegates to `ChargePharmacistEscalationPublisher.publish()` (TASK-004).
4. Sets `AgentTask.sla_escalation_sent_at = NOW()` on the write session — preventing duplicate escalations (US-034 Scenario 3).
5. Skips tasks where `AgentTask.status = COMPLETED` — even if `admit_time` is >24h ago (US-034 Scenario 2).

**Design decisions:**

| Decision | Rationale |
|---|---|
| Same APScheduler instance | US-034 Technical Notes explicit requirement — avoids second scheduler startup |
| `admit_time` from `Encounter` join | US-034 Technical Notes: *"`admit_time` sourced from `encounter.admit_time`"* |
| Idempotency via `sla_escalation_sent_at` | US-034 Scenario 3: repeated ticks must not send duplicate notifications |
| Read replica for poll query | Same pattern as US-021/TASK-003 — TR-010 |

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | Task `IN_PROGRESS` / `PENDING` for ≥ 24 hours after `admit_time` → `CHARGE_PHARMACIST_ESCALATION` published |
| Scenario 2 | Task with `status=COMPLETED` is excluded — no escalation fired |
| Scenario 3 | `sla_escalation_sent_at` set after first escalation — subsequent ticks skip the task |
| DoD | SLA monitor checks `MEDICATION_RECONCILIATION` tasks: escalate if `IN_PROGRESS` or `PENDING` > 24 hours from `encounter.admit_time` |

---

## Implementation Steps

### 1. Create `sla-monitor/app/monitor/medrec_sla_monitor.py`

```python
"""MedRecSLAMonitor — Medication reconciliation 24-hour admission SLA check.

Added as a second job to the same APScheduler AsyncIOScheduler instance
started by SLAMonitor (app/monitor/sla_monitor.py, US-021).

SLA window: 24 hours from encounter.admit_time (BR-002, CMS CoP).
Idempotency: sla_escalation_sent_at field on AgentTask (US-034 Scenario 3).

Design refs:
    US-034 AC Scenario 1  — escalate at 24 h after admit_time
    US-034 AC Scenario 2  — COMPLETED tasks must never be escalated
    US-034 AC Scenario 3  — sla_escalation_sent_at prevents duplicate escalation
    US-034 Technical Notes — same APScheduler instance as US-021; admit_time from encounter
    TR-010                 — use read replica for poll queries
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.sla_loader import SLAConfig
from app.db.session import get_read_session, get_write_session
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.encounter import Encounter
from app.publisher.charge_pharmacist_escalation_publisher import (
    ChargePharmacistEscalationPublisher,
)

logger = logging.getLogger(__name__)

_MEDREC_AGENT_TYPE = "MEDICATION_RECONCILIATION"
_ACTIVE_STATUSES: frozenset[str] = frozenset({"IN_PROGRESS", "PENDING"})


class MedRecSLAMonitor:
    """Medication reconciliation 24-hour admission SLA checker.

    Intended to be registered as a second job on the APScheduler instance
    owned by ``SLAMonitor`` — not as a standalone scheduler.

    Usage (in ``SLAMonitor.start()``)::

        medrec_monitor = MedRecSLAMonitor(
            publisher=ChargePharmacistEscalationPublisher(...),
            config=self._config,
        )
        self._scheduler.add_job(
            medrec_monitor.run_check,
            trigger="interval",
            seconds=self._config.monitor_interval_seconds,
            id="medrec_sla_check",
            max_instances=1,
            coalesce=True,
        )
    """

    def __init__(
        self,
        publisher: ChargePharmacistEscalationPublisher,
        config: SLAConfig,
    ) -> None:
        self._publisher = publisher
        self._sla_entry = config.med_reconciliation_admission_entry()
        self._threshold = timedelta(minutes=self._sla_entry.threshold_minutes)

    async def run_check(self) -> None:
        """Entry point called by APScheduler every ``monitor_interval_seconds``."""
        logger.info("MedRecSLAMonitor: starting 24-hour admission SLA check")
        try:
            breached = await self._find_breached_tasks()
            for task, encounter in breached:
                await self._handle_breach(task, encounter)
        except Exception:
            logger.exception("MedRecSLAMonitor: unhandled error during SLA check")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _find_breached_tasks(
        self,
    ) -> list[tuple[AgentTask, Encounter]]:
        """Query the read replica for MEDICATION_RECONCILIATION tasks past 24h.

        Returns:
            List of (AgentTask, Encounter) pairs where the admission SLA is breached
            and no escalation has been sent yet.
        """
        cutoff: datetime = datetime.now(tz=timezone.utc) - self._threshold

        stmt = (
            sa.select(AgentTask, Encounter)
            .join(Encounter, AgentTask.encounter_id == Encounter.id)
            .where(
                AgentTask.agent_type == _MEDREC_AGENT_TYPE,
                AgentTask.status.in_(_ACTIVE_STATUSES),
                AgentTask.sla_escalation_sent_at.is_(None),
                Encounter.admit_time <= cutoff,
            )
        )

        async with get_read_session() as session:  # TR-010: read replica
            result = await session.execute(stmt)
            return list(result.all())

    async def _handle_breach(
        self,
        task: AgentTask,
        encounter: Encounter,
    ) -> None:
        """Publish escalation and stamp ``sla_escalation_sent_at`` atomically.

        Sets ``AgentTask.sla_escalation_sent_at = NOW()`` before publishing so that
        a publisher failure leaves the stamp set — a deliberate choice to avoid
        duplicate escalation storms if the publisher is intermittently unavailable.
        The publisher has its own retry (TASK-004).
        """
        now = datetime.now(tz=timezone.utc)
        hours_elapsed = int(
            (now - encounter.admit_time).total_seconds() / 3600
        )

        async with get_write_session() as session:
            # Stamp first — prevents race if scheduler fires two concurrent ticks
            await session.execute(
                sa.update(AgentTask)
                .where(
                    AgentTask.id == task.id,
                    AgentTask.sla_escalation_sent_at.is_(None),  # guard
                )
                .values(sla_escalation_sent_at=now)
            )
            await session.commit()

        await self._publisher.publish(
            encounter_id=encounter.id,
            task_id=task.id,
            patient_unit=encounter.patient_unit,
            hours_elapsed=hours_elapsed,
        )

        logger.warning(
            "MedRecSLAMonitor: escalation sent",
            extra={
                "encounter_id": str(encounter.id),
                "task_id": str(task.id),
                "hours_elapsed": hours_elapsed,
                "patient_unit": encounter.patient_unit,
            },
        )
```

### 2. Register `MedRecSLAMonitor` job in `SLAMonitor.start()`

Open `sla-monitor/app/monitor/sla_monitor.py` (US-021/TASK-003). Apply a **surgical addition** to `start()` only — add the second job registration immediately after the existing job:

```python
from app.monitor.medrec_sla_monitor import MedRecSLAMonitor
from app.publisher.charge_pharmacist_escalation_publisher import (
    ChargePharmacistEscalationPublisher,
)

# Inside SLAMonitor.__init__ — add publisher arg (inject from main.py):
#   self._medrec_publisher = medrec_publisher

# Inside SLAMonitor.start():
    def start(self) -> None:
        """Register monitor jobs and start the scheduler."""
        # Existing coordinator SLA job (US-021):
        self._scheduler.add_job(
            self._run_check,
            trigger="interval",
            seconds=self._config.monitor_interval_seconds,
            id="coordinator_sla_check",
            max_instances=1,
            coalesce=True,
        )

        # US-034: medication reconciliation admission SLA job (second job, same scheduler):
        medrec_monitor = MedRecSLAMonitor(
            publisher=self._medrec_publisher,
            config=self._config,
        )
        self._scheduler.add_job(
            medrec_monitor.run_check,
            trigger="interval",
            seconds=self._config.monitor_interval_seconds,
            id="medrec_sla_check",
            max_instances=1,
            coalesce=True,
        )

        self._scheduler.start()
        logger.info("SLAMonitor: scheduler started (2 jobs registered)")
```

### 3. Wire `ChargePharmacistEscalationPublisher` in `main.py`

Open `sla-monitor/app/main.py` and inject the new publisher into `SLAMonitor` at startup. Apply surgical additions to the lifespan context manager only:

```python
from app.publisher.charge_pharmacist_escalation_publisher import (
    ChargePharmacistEscalationPublisher,
)

# In the lifespan startup block:
medrec_publisher = ChargePharmacistEscalationPublisher(
    pubsub_client=pubsub_client,
    topic=settings.NOTIFICATION_REQUESTS_TOPIC,
)
monitor = SLAMonitor(
    publisher=escalation_publisher,
    medrec_publisher=medrec_publisher,  # US-034
)
monitor.start()
```

---

## Files Changed

| File | Change |
|---|---|
| `sla-monitor/app/monitor/medrec_sla_monitor.py` | **New** — `MedRecSLAMonitor` class |
| `sla-monitor/app/monitor/sla_monitor.py` | Surgical: register second job; accept `medrec_publisher` injection |
| `sla-monitor/app/main.py` | Surgical: instantiate `ChargePharmacistEscalationPublisher`; pass to `SLAMonitor` |

---

## Definition of Done Checklist

- [ ] `MedRecSLAMonitor.run_check()` queries only `MEDICATION_RECONCILIATION` tasks with `sla_escalation_sent_at IS NULL` and `status IN ('IN_PROGRESS', 'PENDING')`
- [ ] SLA window measured from `encounter.admit_time` — not `AgentTask.created_at`
- [ ] `sla_escalation_sent_at` stamped **before** publisher call — prevents duplicate escalation
- [ ] Second APScheduler job `medrec_sla_check` registered on existing scheduler — not a new scheduler
- [ ] `COMPLETED` tasks excluded by `status.in_(_ACTIVE_STATUSES)` filter
- [ ] `logger.warning` emitted with `encounter_id`, `task_id`, `hours_elapsed`, `patient_unit` (no PHI in logs)
