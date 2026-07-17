---
id: TASK-002
title: "BoardingMonitor — APScheduler Job, ED Stay Query, and Duration Calculation"
user_story: US-038
epic: EP-006
sprint: 2
layer: Backend / AI Agent
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-038/TASK-001, US-021, US-035/TASK-001]
---

# TASK-002: BoardingMonitor — APScheduler Job, ED Stay Query, and Duration Calculation

> **Story:** US-038 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-038 requires a `BoardingMonitor` that runs on an APScheduler interval job every 5 minutes and identifies encounters where a patient has been in the ED for ≥120 minutes without a confirmed bed assignment. This task implements the monitor class, the async DB query that identifies qualifying encounters, and the ED stay duration calculation logic.

The `BoardingMonitor` does **not** publish alerts directly — that responsibility belongs to TASK-003 (`BoardingAlertPublisher`). The monitor's sole output is a list of `BoardingCandidate` dataclass instances that are passed to the publisher. This keeps the scheduling, detection, and dispatch concerns cleanly separated.

The monitor is registered on the **shared APScheduler instance** provided by US-021. It does not create its own scheduler.

**Design references:**
- US-038 AC Scenario 1 — monitor runs every 5 minutes; fires at 120-minute threshold
- US-038 AC Scenario 2 — no alert if `bed_assigned_at IS NOT NULL` (patient placed before threshold)
- US-038 AC Scenario 4 — no duplicate detection run needed; idempotency is enforced at publish time (TASK-003)
- US-038 Technical Notes — boarding duration: `now - encounter.admit_time` (A01) or `now - encounter.transfer_time` (ED-originating transfer); ED codes from `config/ed_locations.yaml`
- US-038 DoD — "Boarding monitor runs every 5 minutes (APScheduler)"
- design.md §3.1 — Bed Management Agent Cloud Run service (`bed-mgmt-agent`)
- design.md §5.1 (TR-008) — Cloud Run min-instances=1 for this service

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | Monitor runs every 5 min; returns encounters ≥120 min in ED with no bed assignment |
| Scenario 2 | Encounters with `bed_assigned_at IS NOT NULL` before threshold excluded by query |
| Scenario 4 | Monitor detects duplicate-eligible encounters; idempotency enforced in publisher (TASK-003) |

---

## Implementation Steps

### 1. Create module structure

```bash
touch backend/app/agents/bed_management/boarding_monitor.py
touch backend/app/agents/bed_management/boarding_schemas.py
```

### 2. Implement `backend/app/agents/bed_management/boarding_schemas.py`

```python
"""Pydantic schemas and dataclasses for ED boarding alert workflow.

Shared between BoardingMonitor (detection) and BoardingAlertPublisher (dispatch).

Design refs:
    US-038 AC Scenario 1 — BoardingCandidate fields
    US-038 AC Scenario 4 — idempotency_key construction
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field
from typing import Literal


@dataclass(frozen=True, slots=True)
class BoardingCandidate:
    """Encounter identified by BoardingMonitor as eligible for a boarding alert.

    Immutable — produced by the monitor; consumed by the publisher.
    """

    encounter_id: str
    patient_id: str
    ed_arrival_time: datetime
    minutes_elapsed: int
    target_unit: str | None
    boarding_alert_sent_at: datetime | None  # None → alert not yet sent
    current_location: str

    @property
    def idempotency_key(self) -> str:
        """Deterministic key scoped to encounter + boarding start time.

        Format: boarding:{encounter_id}:{boarding_start_iso}

        Design ref: US-038 AC Scenario 4.
        """
        start_iso = self.ed_arrival_time.isoformat()
        return f"boarding:{self.encounter_id}:{start_iso}"

    @property
    def already_alerted(self) -> bool:
        """True if a boarding alert was already sent for this ED stay."""
        return self.boarding_alert_sent_at is not None


class BoardingAlertPayload(BaseModel):
    """Pub/Sub payload published to ``notification-requests`` on boarding threshold breach.

    Contains no PHI beyond the opaque ``patient_id`` UUID and ``encounter_id`` UUID.
    All fields are non-identifiable clinical metadata.

    Design refs:
        US-038 AC Scenario 1 — required payload fields
        US-038 Technical Notes — priority=IMMEDIATE
        design.md §7.5 AIR-040 — idempotency_key prevents duplicate sends
        BR-020 — no PHI in Pub/Sub payloads
    """

    notification_type: Literal["ED_BOARDING_ALERT"] = "ED_BOARDING_ALERT"
    priority: Literal["IMMEDIATE"] = "IMMEDIATE"
    patient_id: str = Field(..., description="Opaque UUID — not a human-readable MRN")
    encounter_id: str = Field(..., description="Opaque UUID")
    ed_arrival_time: str = Field(..., description="ISO-8601 UTC timestamp of ED arrival")
    minutes_elapsed: int = Field(..., ge=120, description="Minutes patient has waited in ED")
    target_unit: str | None = Field(None, description="Requested admission unit, if known")
    idempotency_key: str = Field(
        ...,
        description="boarding:{encounter_id}:{ed_arrival_time_iso} — prevents duplicate notifications",
    )
```

### 3. Implement `backend/app/agents/bed_management/boarding_monitor.py`

```python
"""BoardingMonitor — detects ED encounters that have breached the 2-hour boarding threshold.

Runs as an APScheduler interval job every 5 minutes on the shared scheduler
provided by US-021. Delegates alert publishing to BoardingAlertPublisher (TASK-003).

Detection query returns encounters where ALL of the following hold:
    1. current_location IN <ed_location_codes>
    2. status = 'ADMITTED'
    3. bed_assigned_at IS NULL  (no bed assignment confirmed)
    4. boarding_alert_resolved_at IS NULL  (alert not already resolved)
    5. (now - admit_time OR transfer_time) >= 120 minutes

Design refs:
    US-038 AC Scenario 1  — 120-minute threshold; every-5-min APScheduler job
    US-038 AC Scenario 2  — bed_assigned_at IS NULL filter
    US-038 AC Scenario 4  — idempotency enforced in publisher; monitor passes all candidates
    US-038 Technical Notes — admit_time for A01; transfer_time for ED-originating transfers
    design.md §3.1        — BedManagementAgent responsibility
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bed_management.boarding_schemas import BoardingCandidate
from app.agents.bed_management.ed_location_loader import load_ed_location_codes
from app.db.session import get_write_session
from app.models.encounter import Encounter

logger = logging.getLogger(__name__)

# US-038 AC Scenario 1: threshold = 120 minutes
BOARDING_THRESHOLD_MINUTES: int = 120
# US-038 DoD: monitor runs every 5 minutes
MONITOR_INTERVAL_MINUTES: int = 5


class BoardingMonitor:
    """Identifies ED encounters that have exceeded the boarding threshold.

    Instantiated once per `bed-mgmt-agent` Cloud Run container and registered
    on the shared APScheduler instance (US-021).

    Args:
        publisher: Callable that receives a list of ``BoardingCandidate`` instances
                   and dispatches alerts. Injected to keep monitor/publisher decoupled.
        scheduler: The shared AsyncIOScheduler from US-021.
    """

    def __init__(
        self,
        publisher: "BoardingAlertPublisher",  # noqa: F821 — imported at call site
        scheduler: AsyncIOScheduler,
    ) -> None:
        self._publisher = publisher
        self._scheduler = scheduler

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self) -> None:
        """Register the boarding monitor as an APScheduler interval job.

        Idempotent — safe to call multiple times (APScheduler deduplicates by job_id).
        """
        self._scheduler.add_job(
            self._run_cycle,
            trigger="interval",
            minutes=MONITOR_INTERVAL_MINUTES,
            id="boarding_monitor",
            replace_existing=True,
            misfire_grace_time=60,  # tolerate 60-second scheduler lag
        )
        logger.info(
            "BoardingMonitor registered: interval=%d minutes, threshold=%d minutes",
            MONITOR_INTERVAL_MINUTES,
            BOARDING_THRESHOLD_MINUTES,
        )

    # ------------------------------------------------------------------
    # Internal cycle
    # ------------------------------------------------------------------

    async def _run_cycle(self) -> None:
        """Execute a single monitoring cycle.

        Queries the DB for boarding candidates and delegates each to the publisher.
        Exceptions are caught and logged — a failed cycle must not crash the scheduler.
        """
        try:
            candidates = await self._detect_boarding_candidates()
            if not candidates:
                logger.debug("BoardingMonitor: no boarding candidates found this cycle.")
                return

            logger.info(
                "BoardingMonitor: %d boarding candidate(s) detected.", len(candidates)
            )
            await self._publisher.dispatch_alerts(candidates)
        except Exception:
            logger.exception("BoardingMonitor cycle failed — will retry next interval.")

    async def _detect_boarding_candidates(self) -> list[BoardingCandidate]:
        """Query for encounters that qualify for a boarding alert.

        Returns a list of ``BoardingCandidate`` instances (may include already-alerted
        encounters — idempotency is enforced in the publisher).
        """
        ed_codes = load_ed_location_codes()
        threshold_time = datetime.now(UTC) - timedelta(minutes=BOARDING_THRESHOLD_MINUTES)

        # Boarding start time: admit_time for A01 admissions;
        # transfer_time for ED-originating transfers (US-038 Technical Notes).
        # COALESCE ensures we handle both cases with a single query.
        stmt = (
            select(Encounter)
            .where(
                Encounter.current_location.in_(ed_codes),
                Encounter.status == "ADMITTED",
                Encounter.bed_assigned_at.is_(None),
                Encounter.boarding_alert_resolved_at.is_(None),
                # Boarding start = earliest of admit_time / transfer_time
                text(
                    "COALESCE(encounter.admit_time, encounter.transfer_time) "
                    "<= :threshold"
                ).bindparams(threshold=threshold_time),
            )
        )

        candidates: list[BoardingCandidate] = []
        async with get_write_session() as session:  # type: AsyncSession
            result = await session.execute(stmt)
            encounters = result.scalars().all()

        now = datetime.now(UTC)
        for enc in encounters:
            boarding_start = enc.admit_time or enc.transfer_time
            if boarding_start is None:
                logger.warning(
                    "Encounter %s has no admit_time or transfer_time — skipping.",
                    enc.id,
                )
                continue

            minutes_elapsed = int((now - boarding_start).total_seconds() / 60)
            candidates.append(
                BoardingCandidate(
                    encounter_id=str(enc.id),
                    patient_id=str(enc.patient_id),
                    ed_arrival_time=boarding_start,
                    minutes_elapsed=minutes_elapsed,
                    target_unit=enc.admission_unit,
                    boarding_alert_sent_at=enc.boarding_alert_sent_at,
                    current_location=enc.current_location,
                )
            )

        return candidates
```

### 4. Register `BoardingMonitor` on service startup

In `backend/app/agents/bed_management/main.py`, after the shared scheduler is retrieved from US-021:

```python
from app.agents.bed_management.boarding_monitor import BoardingMonitor
from app.agents.bed_management.boarding_publisher import BoardingAlertPublisher

# ... existing startup logic ...

publisher = BoardingAlertPublisher(pubsub_client=pubsub_client, db_session_factory=get_write_session)
boarding_monitor = BoardingMonitor(publisher=publisher, scheduler=scheduler)
boarding_monitor.register()
```

---

## Validation Checklist

- [ ] `BoardingMonitor.register()` adds job with id `"boarding_monitor"` and `interval=5 min`
- [ ] `_detect_boarding_candidates()` excludes encounters where `bed_assigned_at IS NOT NULL`
- [ ] `_detect_boarding_candidates()` excludes encounters where `boarding_alert_resolved_at IS NOT NULL`
- [ ] COALESCE logic handles both `admit_time` (A01) and `transfer_time` (ED transfer) correctly
- [ ] ED location codes loaded fresh on each cycle (no stale cache)
- [ ] Exceptions in `_run_cycle()` are caught/logged; scheduler continues running
- [ ] `BoardingCandidate.already_alerted` correctly returns `True` when `boarding_alert_sent_at` is set

---

## Files Changed

| File | Action |
|---|---|
| `backend/app/agents/bed_management/boarding_schemas.py` | Create |
| `backend/app/agents/bed_management/boarding_monitor.py` | Create |
| `backend/app/agents/bed_management/main.py` | Modify — register `BoardingMonitor` |
