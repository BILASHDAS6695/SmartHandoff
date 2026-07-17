---
id: TASK-003
title: "APScheduler Re-escalation Monitor — 15-Minute Unacknowledged Supervisor Escalation"
user_story: US-042
epic: EP-007
sprint: 2
layer: Backend / AI Agent
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-042/TASK-001, US-042/TASK-002, US-021]
---

# TASK-003: APScheduler Re-escalation Monitor — 15-Minute Unacknowledged Supervisor Escalation

> **Story:** US-042 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-042 AC Scenario 3 requires that if a `CARE_TEAM_ESCALATION` alert goes unacknowledged for 15 minutes, a `SUPERVISOR_ESCALATION` notification is published and the original `care_escalation` record is tagged with `escalated_to_supervisor=True`.

The re-escalation monitor runs as an APScheduler job every 60 seconds on the **shared APScheduler instance** established in US-021 (coordinator agent). It queries `care_escalation` for records where:

```sql
status = 'PENDING'
AND escalated_to_supervisor = FALSE
AND sent_at < NOW() - INTERVAL '15 minutes'
AND deleted_at IS NULL
```

For each matching record, the monitor:
1. Publishes a `SUPERVISOR_ESCALATION` message to `notification-requests`
2. Updates `care_escalation.status = 'ESCALATED_TO_SUPERVISOR'`, `escalated_to_supervisor = True`, `escalated_at = NOW()`

**`SUPERVISOR_ESCALATION` message published to `notification-requests`:**

```json
{
  "event_type": "SUPERVISOR_ESCALATION",
  "escalation_id": "uuid",
  "encounter_id": "uuid",
  "patient_id": "uuid",
  "original_sent_at": "2026-07-17T10:00:00Z",
  "channel": "SMS",
  "idempotency_key": "NOTIF-SUP-ESC-{escalation_id}"
}
```

The Notification Service resolves the on-call supervisor's contact from `app_user WHERE role=CHARGE_NURSE AND unit=encounter.current_unit` at dispatch time.

**Re-escalation idempotency:** The `escalated_to_supervisor=TRUE` column acts as the deduplication flag. The job updates this atomically before publishing, so a second scheduler tick cannot re-escalate an already-escalated record.

**US-021 dependency:** US-021/TASK-001 establishes the shared APScheduler (`AsyncIOScheduler`) instance in `backend/app/agents/coordinator/scheduler.py`. This task adds a new job to that scheduler — no new APScheduler instance is created.

**Design references:**
- design.md §3.1 — Follow-up Care Agent: risk scoring, appointment scheduling, reminder dispatch
- design.md §5.1 TR-015 — Pub/Sub DLQ on all agent subscriptions; zero message loss
- design.md §7.4 AIR-040 — Notification Service idempotency key; `channel` field routing
- US-042 AC Scenario 3 — `SUPERVISOR_ESCALATION` published; `escalated_to_supervisor=True` set
- US-021 — shared APScheduler instance in coordinator agent
- ADR-001 — idempotency key prevents duplicate supervisor alerts

---

## Acceptance Criteria Addressed

| US-042 AC Scenario | Coverage |
|---|---|
| **Scenario 3** | `SUPERVISOR_ESCALATION` published to `notification-requests`; `care_escalation.escalated_to_supervisor=True`; `escalated_at` timestamp recorded; no further reminders sent after tagging |

---

## Implementation Steps

### 1. Create `backend/app/agents/followup_care/escalation/reescalation_job.py`

```python
"""APScheduler job for re-escalating unacknowledged care team escalations.

Runs every 60 seconds on the shared AsyncIOScheduler (US-021).

Logic:
    Query care_escalation WHERE status=PENDING AND escalated_to_supervisor=FALSE
    AND sent_at < NOW() - INTERVAL '15 minutes'.
    For each result:
        1. Update status=ESCALATED_TO_SUPERVISOR, escalated_to_supervisor=True, escalated_at=NOW()
        2. Publish SUPERVISOR_ESCALATION to notification-requests

Idempotency:
    The DB UPDATE is performed before the Pub/Sub publish. If the job crashes
    between the UPDATE and publish, the record status is ESCALATED_TO_SUPERVISOR,
    so the next tick will not re-query it — but the notification was not sent.
    Recovery: a separate Cloud Monitoring alert on DLQ depth detects delivery failures.

PHI handling:
    Logs contain only escalation_id (UUID), encounter_id (UUID). No patient name,
    MRN, DOB, phone, or email in any log line (ADR-007).

Design refs:
    US-042 AC Scenario 3
    US-021 — shared APScheduler
    design.md §5.1 TR-015 — DLQ and zero message loss
    ADR-001 — idempotency
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from google.cloud import pubsub_v1
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.care_escalation import CareEscalation
from app.models.enums import CareEscalationStatus

logger = logging.getLogger(__name__)

ESCALATION_SLA_MINUTES = 15
JOB_INTERVAL_SECONDS = 60


class ReEscalationJob:
    """Detects unacknowledged escalations past the 15-minute SLA and re-escalates to supervisor.

    Args:
        session_factory: Async SQLAlchemy session factory.
        publisher: GCP Pub/Sub PublisherClient.
        notification_topic: Full Pub/Sub topic path for notification-requests.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: pubsub_v1.PublisherClient,
        notification_topic: str,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._notification_topic = notification_topic

    async def run(self) -> None:
        """APScheduler callback — runs every 60 seconds.

        Queries for PENDING escalations past the 15-minute SLA and re-escalates each.
        Errors in individual records are caught and logged; they do not abort the batch.
        """
        sla_cutoff = datetime.now(tz=timezone.utc) - timedelta(minutes=ESCALATION_SLA_MINUTES)

        async with self._session_factory() as session:
            result = await session.execute(
                select(CareEscalation).where(
                    CareEscalation.status == CareEscalationStatus.PENDING,
                    CareEscalation.escalated_to_supervisor.is_(False),
                    CareEscalation.sent_at < sla_cutoff,
                    CareEscalation.deleted_at.is_(None),
                )
            )
            overdue_escalations = result.scalars().all()

        if not overdue_escalations:
            return

        logger.info(
            "reescalation_job.overdue_escalations_found",
            extra={"count": len(overdue_escalations)},
        )

        for escalation in overdue_escalations:
            try:
                await self._reescalate(escalation)
            except Exception as exc:
                logger.error(
                    "reescalation_job.reescalation_failed",
                    extra={
                        "escalation_id": str(escalation.id),
                        "encounter_id": str(escalation.encounter_id),
                        "error": str(exc),
                    },
                )

    async def _reescalate(self, escalation: CareEscalation) -> None:
        """Update the escalation record to ESCALATED_TO_SUPERVISOR and publish notification.

        The DB update is committed before the Pub/Sub publish so that a crash
        after the UPDATE but before publish is recoverable via Cloud Monitoring
        alert (P3: DLQ count > 0), not via duplicate re-escalation.
        """
        now = datetime.now(tz=timezone.utc)

        async with self._session_factory() as session:
            # Atomic update — only updates PENDING records that are not yet escalated
            result = await session.execute(
                update(CareEscalation)
                .where(
                    CareEscalation.id == escalation.id,
                    CareEscalation.status == CareEscalationStatus.PENDING,
                    CareEscalation.escalated_to_supervisor.is_(False),
                )
                .values(
                    status=CareEscalationStatus.ESCALATED_TO_SUPERVISOR,
                    escalated_to_supervisor=True,
                    escalated_at=now,
                )
                .returning(CareEscalation.id)
            )
            updated_id = result.scalar_one_or_none()

            if updated_id is None:
                # Concurrent tick already updated this record — skip
                logger.info(
                    "reescalation_job.concurrent_update_skipped",
                    extra={"escalation_id": str(escalation.id)},
                )
                return

            await session.commit()

        # Publish SUPERVISOR_ESCALATION after DB commit
        self._publish_supervisor_escalation(escalation, sent_at=now)

        logger.info(
            "reescalation_job.supervisor_escalation_published",
            extra={
                "escalation_id": str(escalation.id),
                "encounter_id": str(escalation.encounter_id),
            },
        )

    def _publish_supervisor_escalation(
        self,
        escalation: CareEscalation,
        sent_at: datetime,
    ) -> None:
        """Publish SUPERVISOR_ESCALATION to the notification-requests topic.

        PHI policy: Only UUIDs are published. The Notification Service resolves
        the supervisor's contact from app_user at dispatch time (ADR-007).
        """
        payload = json.dumps(
            {
                "event_type": "SUPERVISOR_ESCALATION",
                "escalation_id": str(escalation.id),
                "encounter_id": str(escalation.encounter_id),
                "patient_id": str(escalation.patient_id),
                "original_sent_at": escalation.sent_at.isoformat(),
                "channel": "SMS",
                "idempotency_key": f"NOTIF-SUP-ESC-{escalation.id}",
            }
        ).encode("utf-8")

        future = self._publisher.publish(self._notification_topic, payload)
        future.result(timeout=10)
```

### 2. Register the job with the shared APScheduler in `backend/app/agents/coordinator/scheduler.py`

```python
# In backend/app/agents/coordinator/scheduler.py
# Add after existing scheduler job registrations (US-021):

from app.agents.followup_care.escalation.reescalation_job import ReEscalationJob

reescalation_job = ReEscalationJob(
    session_factory=async_session_factory,
    publisher=publisher_client,
    notification_topic=settings.NOTIFICATION_REQUESTS_TOPIC,
)

scheduler.add_job(
    reescalation_job.run,
    trigger="interval",
    seconds=60,
    id="care_escalation_reescalation_monitor",
    replace_existing=True,
    misfire_grace_time=30,  # Allow up to 30 s of scheduler drift before declaring misfire
)
```

---

## Definition of Done Checklist

- [ ] `backend/app/agents/followup_care/escalation/reescalation_job.py` created
- [ ] `ReEscalationJob.run()` queries `care_escalation WHERE status=PENDING AND escalated_to_supervisor=FALSE AND sent_at < NOW() - INTERVAL '15 minutes'`
- [ ] DB `UPDATE` uses `WHERE status=PENDING AND escalated_to_supervisor=FALSE` to prevent concurrent duplicates
- [ ] `SUPERVISOR_ESCALATION` published to `notification-requests` after DB commit (not before)
- [ ] `idempotency_key = "NOTIF-SUP-ESC-{escalation_id}"` included in published message
- [ ] Job registered on shared APScheduler with `interval=60s`, `misfire_grace_time=30s`
- [ ] Errors in individual records caught, logged, and do not abort the batch
- [ ] No PHI in any log line

---

## Notes

- **Ordering**: The DB UPDATE is committed before Pub/Sub publish. This means a crash between the two steps leaves the record tagged as `ESCALATED_TO_SUPERVISOR` without a notification having been sent. This is the safer failure mode (no duplicate supervisor alerts) and is recoverable via a runbook step.
- **Scheduler drift**: `misfire_grace_time=30` allows APScheduler to execute a missed tick if the process was briefly unresponsive (e.g., during Cloud Run cold restart). Jobs missed beyond 30 seconds are skipped and logged at WARNING level.
- **15-minute SLA precision**: The SLA is measured from `care_escalation.sent_at`, not from the chatbot urgency flag timestamp. The `sent_at` is set by TASK-002 when the `CARE_TEAM_ESCALATION` is first dispatched.
