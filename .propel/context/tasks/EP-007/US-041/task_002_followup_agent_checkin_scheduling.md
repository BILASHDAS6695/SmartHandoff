---
id: TASK-002
title: "FollowUpCareAgent — Create `CHECK_IN_48H` ScheduledNotification on A03 for Risk ≥ 0.5"
user_story: US-041
epic: EP-007
sprint: 2
layer: Backend / AI Agent
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer / AI-ML Engineer
upstream: [US-041/TASK-001, US-039/TASK-004]
---

# TASK-002: FollowUpCareAgent — Create `CHECK_IN_48H` ScheduledNotification on A03 for Risk ≥ 0.5

> **Story:** US-041 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-039/TASK-004 built the `FollowUpCareAgent` to:
1. Subscribe to the `adt-events` Pub/Sub topic via `followup-agent-sub`
2. Trigger on A03 discharge events
3. Score readmission risk and persist `encounter.risk_score` + `encounter.risk_tier`

US-041 extends step 3: **after** the risk score is persisted, the agent must conditionally create a `ScheduledNotification` record for patients with `risk_score ≥ 0.5` (MEDIUM or HIGH tier). This corresponds to the `0.30–0.70 = MEDIUM`, `≥0.70 = HIGH` thresholds from US-039 — the agent schedules a check-in whenever the patient is not LOW risk.

**Trigger logic:**

```
risk_score ≥ 0.5  →  CREATE ScheduledNotification(type=CHECK_IN_48H)
risk_score < 0.5  →  skip (no record created)
```

The threshold `0.5` sits between the LOW/MEDIUM boundary (`0.30`) and the MEDIUM/HIGH boundary (`0.70`), intentionally capturing only meaningful MEDIUM and HIGH risk patients, not borderline LOW patients. The exact threshold of `0.5` is mandated by US-041 AC Scenario 2.

**Channel resolution:**

```python
channel = NotificationChannel.EMAIL if patient.preferred_contact == "email" else NotificationChannel.SMS
```

`patient.preferred_contact` is the source of truth. Default to SMS if not set.

**`send_at` computation:**

```python
send_at = encounter.discharge_time + timedelta(hours=48)
```

`encounter.discharge_time` is set by the coordinator agent when it processes the A03 event (US-021). This task reads it from the DB — it does NOT use `datetime.utcnow()` as the base.

**Idempotency:**

```python
idempotency_key = f"CHK48-{encounter.id}"
```

`INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` prevents duplicate records on Pub/Sub redelivery.

**Design references:**
- design.md §3.1 — Follow-up Care Agent: Python LangChain + Scikit-learn, risk scoring, check-in scheduling
- design.md §3.2 — Agent container pattern: Pydantic structured output, DB write after task
- US-041 AC Scenario 1 — `type=CHECK_IN_48H`, `send_at = discharge_time + 48 hours`
- US-041 AC Scenario 2 — no check-in for `risk_score=0.2` (LOW)
- US-041 AC Scenario 3 — channel resolved from `patient.preferred_contact`
- US-041 Technical Notes — PHI minimisation: only `first_name` in message (resolved at dispatch time, not stored here)
- ADR-001 — Pub/Sub at-least-once; idempotency key required
- ADR-007 — PHI not duplicated in `scheduled_notification`; phone/email resolved at dispatch time from encrypted `patient` record

---

## Acceptance Criteria Addressed

| US-041 AC Scenario | Coverage |
|---|---|
| **Scenario 1** | `ScheduledNotification` created: `type=CHECK_IN_48H`, `send_at = discharge_time + 48 hours`, channel from `patient.preferred_contact` |
| **Scenario 2** | No `ScheduledNotification` created for `risk_score=0.2` (< 0.5 threshold) |
| **Scenario 3** | Channel set to `EMAIL` when `patient.preferred_contact=email` |

---

## Implementation Steps

### 1. Create `backend/app/agents/followup_care/checkin_scheduler.py`

This is a focused helper module — not mixed into `agent.py` — so the risk-scoring logic (US-039) and the scheduling logic (US-041) remain independently testable.

```python
"""Check-in notification scheduler for the FollowUpCareAgent.

Implements US-041: creates a ScheduledNotification record (type=CHECK_IN_48H)
for patients with readmission risk_score >= CHECKIN_RISK_THRESHOLD (0.5)
after A03 discharge event processing.

PHI handling:
    Patient phone/email is NOT stored in scheduled_notification. It is resolved
    at dispatch time by the NotificationService from the encrypted patient record
    (ADR-007 minimum-necessary principle). Only patient_id (UUID) is stored here.

Idempotency:
    idempotency_key = f"CHK48-{encounter_id}" — prevents duplicate records on
    Pub/Sub at-least-once redelivery (ADR-001).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.scheduled_notification import (
    DeliveryStatus,
    NotificationChannel,
    NotificationType,
    ScheduledNotification,
)

logger = logging.getLogger(__name__)

# US-041 AC Scenario 1 / Scenario 2 — threshold for scheduling a check-in
CHECKIN_RISK_THRESHOLD: float = 0.5

# US-041 Technical Notes — 48 hours post-discharge
CHECKIN_DELAY_HOURS: int = 48


async def maybe_schedule_48h_checkin(
    *,
    session: AsyncSession,
    encounter: Encounter,
    patient: Patient,
    risk_score: float,
) -> ScheduledNotification | None:
    """Create a CHECK_IN_48H ScheduledNotification if risk_score >= 0.5.

    Args:
        session: Writable AsyncSession (Cloud SQL Primary).
        encounter: The discharged encounter with discharge_time populated.
        patient: The patient associated with the encounter.
        risk_score: The 30-day readmission probability from the ML Inference Service.

    Returns:
        The created ScheduledNotification, or None if risk_score < threshold.
    """
    if risk_score < CHECKIN_RISK_THRESHOLD:
        logger.info(
            "check_in_skipped",
            extra={
                "encounter_id": str(encounter.id),
                "risk_score": risk_score,
                "reason": f"risk_score < {CHECKIN_RISK_THRESHOLD}",
            },
        )
        return None

    if encounter.discharge_time is None:
        logger.error(
            "check_in_skipped_no_discharge_time",
            extra={"encounter_id": str(encounter.id)},
        )
        return None

    idempotency_key = f"CHK48-{encounter.id}"

    # Resolve channel from patient preference (default: SMS)
    channel = (
        NotificationChannel.EMAIL
        if getattr(patient, "preferred_contact", None) == "email"
        else NotificationChannel.SMS
    )

    # send_at is computed from discharge_time, NOT from current time (US-041 Technical Notes)
    send_at: datetime = encounter.discharge_time + timedelta(hours=CHECKIN_DELAY_HOURS)

    notification = ScheduledNotification(
        idempotency_key=idempotency_key,
        type=NotificationType.CHECK_IN_48H,
        send_at=send_at,
        channel=channel,
        delivery_status=DeliveryStatus.PENDING,
        patient_id=patient.id,
        encounter_id=encounter.id,
    )

    # INSERT ... ON CONFLICT (idempotency_key) DO NOTHING — idempotent on redelivery
    session.add(notification)
    try:
        await session.flush()  # flush to catch constraint violations before commit
    except Exception:
        # Unique constraint violation: already scheduled — safe to ignore
        await session.rollback()
        logger.info(
            "check_in_already_scheduled",
            extra={
                "encounter_id": str(encounter.id),
                "idempotency_key": idempotency_key,
            },
        )
        return None

    logger.info(
        "check_in_scheduled",
        extra={
            "encounter_id": str(encounter.id),
            "risk_score": risk_score,
            "send_at": send_at.isoformat(),
            "channel": channel.value,
        },
    )
    return notification
```

### 2. Integrate into `backend/app/agents/followup_care/agent.py`

In the existing `_process_a03_event()` method (US-039/TASK-004), add the check-in scheduling step **after** `encounter.risk_score` and `encounter.risk_tier` are committed to the DB:

```python
# --- ADD: US-041 — 48-hour check-in scheduling ---
from app.agents.followup_care.checkin_scheduler import maybe_schedule_48h_checkin

# Inside _process_a03_event(), after the risk score DB commit:
scheduled_notification = await maybe_schedule_48h_checkin(
    session=session,
    encounter=encounter,
    patient=patient,
    risk_score=risk_result.risk_score,
)
if scheduled_notification:
    await session.commit()
    logger.info(
        "check_in_notification_committed",
        extra={
            "encounter_id": str(encounter.id),
            "scheduled_notification_id": str(scheduled_notification.id),
        },
    )
```

> **Note:** The risk score `session.commit()` (US-039/TASK-004) and the notification `session.commit()` are intentionally separate transactions. If notification scheduling fails, the risk score is already persisted — preserving US-039 AC Scenario 1 guarantee.

### 3. Update `backend/app/agents/followup_care/schemas.py`

Extend `RiskAssessmentResult` to include the optional check-in outcome:

```python
# In RiskAssessmentResult (US-039/TASK-004 schemas.py):
from uuid import UUID as UUIDType

# Add field:
checkin_scheduled: bool = False
scheduled_notification_id: UUIDType | None = None
```

---

## Validation

- [ ] A03 event with `risk_score=0.6` → `ScheduledNotification` row in DB with `type=CHECK_IN_48H`, `delivery_status=PENDING`
- [ ] `send_at` == `encounter.discharge_time + 48h` (not `datetime.utcnow() + 48h`)
- [ ] A03 event with `risk_score=0.2` → no `ScheduledNotification` row created
- [ ] A03 Pub/Sub message redelivered → second call does not create a duplicate row (idempotency check)
- [ ] Patient with `preferred_contact=email` → `channel=EMAIL`
- [ ] Patient with `preferred_contact=sms` (or null) → `channel=SMS`
- [ ] `mypy backend/app/agents/followup_care/checkin_scheduler.py --strict` exits 0
- [ ] `ruff check backend/app/agents/followup_care/checkin_scheduler.py` exits 0

---

## Files Produced

| File | Change |
|------|--------|
| `backend/app/agents/followup_care/checkin_scheduler.py` | New — check-in scheduling helper |
| `backend/app/agents/followup_care/agent.py` | Modified — call `maybe_schedule_48h_checkin()` after risk score commit |
| `backend/app/agents/followup_care/schemas.py` | Modified — add `checkin_scheduled`, `scheduled_notification_id` fields |
