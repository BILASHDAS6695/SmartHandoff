---
id: TASK-004
title: "Implement `ChargePharmacistEscalationPublisher` — Pub/Sub Escalation to `notification-requests`"
user_story: US-034
epic: EP-005
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-021/TASK-004, US-034/TASK-002]
---

# TASK-004: Implement `ChargePharmacistEscalationPublisher` — Pub/Sub Escalation to `notification-requests`

> **Story:** US-034 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-034 Scenario 1 requires:

> *"A `CHARGE_PHARMACIST_ESCALATION` notification is published to `notification-requests` with `encounter_id`, `patient_unit`, and `hours_elapsed=24`."*

US-021/TASK-004 established `EscalationPublisher` for `SUPERVISOR_ESCALATION` messages. This task follows the same pattern to implement `ChargePharmacistEscalationPublisher`, which publishes `CHARGE_PHARMACIST_ESCALATION` payloads with `priority=HIGH`.

**Design decisions:**

| Decision | Rationale |
|---|---|
| Separate publisher class | Single Responsibility — keeps charge pharmacist escalation schema isolated from supervisor escalation |
| `priority=HIGH` attribute | US-034 DoD: *"Escalation published to `notification-requests` Pub/Sub with `priority=HIGH`"* |
| Pydantic payload schema | Enforces required fields; prevents accidental field omission |
| Retry on transient Pub/Sub failure | Mirrors `EscalationPublisher` retry pattern (US-021/TASK-004) |

**Design references:**
- US-021/TASK-004 — `EscalationPublisher` pattern to follow
- US-034 Scenario 1 — required payload fields: `encounter_id`, `patient_unit`, `hours_elapsed`
- design.md §3.1 — `notification-requests` Pub/Sub topic

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | `CHARGE_PHARMACIST_ESCALATION` published with `encounter_id`, `patient_unit`, `hours_elapsed=24` |
| DoD | Escalation published to `notification-requests` Pub/Sub with `priority=HIGH` |

---

## Implementation Steps

### 1. Create payload schema `sla-monitor/app/publisher/schemas.py`

Add the `ChargePharmacistEscalationPayload` Pydantic model. If `schemas.py` already exists from US-021/TASK-004, append the new class — do not recreate the file.

```python
class ChargePharmacistEscalationPayload(BaseModel):
    """Pub/Sub message payload for CHARGE_PHARMACIST_ESCALATION.

    Published to the ``notification-requests`` topic by ``MedRecSLAMonitor``
    when a MEDICATION_RECONCILIATION AgentTask remains non-COMPLETED ≥ 24 hours
    after encounter.admit_time.

    US-034 Scenario 1 required fields: encounter_id, patient_unit, hours_elapsed.
    """

    notification_type: Literal["CHARGE_PHARMACIST_ESCALATION"] = (
        "CHARGE_PHARMACIST_ESCALATION"
    )
    priority: Literal["HIGH"] = "HIGH"
    encounter_id: UUID
    task_id: UUID
    patient_unit: str
    hours_elapsed: int
    sent_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
```

### 2. Create `sla-monitor/app/publisher/charge_pharmacist_escalation_publisher.py`

```python
"""ChargePharmacistEscalationPublisher — publishes CHARGE_PHARMACIST_ESCALATION.

Sends a HIGH-priority notification to the ``notification-requests`` Pub/Sub topic
when a MEDICATION_RECONCILIATION AgentTask has exceeded the 24-hour admission SLA.

Design refs:
    US-034 Scenario 1  — required payload fields
    US-034 DoD         — priority=HIGH on notification-requests topic
    US-021/TASK-004    — EscalationPublisher pattern (same topic, same retry logic)
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from google.cloud import pubsub_v1

from app.publisher.schemas import ChargePharmacistEscalationPayload

logger = logging.getLogger(__name__)


class ChargePharmacistEscalationPublisher:
    """Publishes CHARGE_PHARMACIST_ESCALATION messages to notification-requests.

    Args:
        pubsub_client: Initialised ``google.cloud.pubsub_v1.PublisherClient``.
        topic: Fully qualified Pub/Sub topic path, e.g.
            ``projects/{project}/topics/notification-requests``.
    """

    def __init__(
        self,
        pubsub_client: pubsub_v1.PublisherClient,
        topic: str,
    ) -> None:
        self._client = pubsub_client
        self._topic = topic

    async def publish(
        self,
        *,
        encounter_id: UUID,
        task_id: UUID,
        patient_unit: str,
        hours_elapsed: int,
    ) -> None:
        """Publish a CHARGE_PHARMACIST_ESCALATION message.

        Args:
            encounter_id: UUID of the encounter breaching the SLA.
            task_id: UUID of the MEDICATION_RECONCILIATION AgentTask.
            patient_unit: Ward / unit identifier (e.g. ``"3N"``).
            hours_elapsed: Hours since admission at the time of escalation.

        Raises:
            google.api_core.exceptions.GoogleAPICallError: On non-retryable
                Pub/Sub publish failure after internal retries.
        """
        payload = ChargePharmacistEscalationPayload(
            encounter_id=encounter_id,
            task_id=task_id,
            patient_unit=patient_unit,
            hours_elapsed=hours_elapsed,
        )
        data = payload.model_dump_json().encode("utf-8")

        future = self._client.publish(
            self._topic,
            data=data,
            notification_type="CHARGE_PHARMACIST_ESCALATION",
            priority="HIGH",
        )
        message_id = future.result(timeout=10)  # blocks; raises on failure

        logger.info(
            "ChargePharmacistEscalationPublisher: published",
            extra={
                "message_id": message_id,
                "encounter_id": str(encounter_id),
                "task_id": str(task_id),
                "hours_elapsed": hours_elapsed,
            },
        )
```

### 3. Export from `publisher/__init__.py`

```python
from app.publisher.charge_pharmacist_escalation_publisher import (
    ChargePharmacistEscalationPublisher,
)
```

---

## Files Changed

| File | Change |
|---|---|
| `sla-monitor/app/publisher/schemas.py` | Add `ChargePharmacistEscalationPayload` (append — do not rewrite) |
| `sla-monitor/app/publisher/charge_pharmacist_escalation_publisher.py` | **New** — `ChargePharmacistEscalationPublisher` class |
| `sla-monitor/app/publisher/__init__.py` | Export `ChargePharmacistEscalationPublisher` |

---

## Definition of Done Checklist

- [ ] `ChargePharmacistEscalationPayload` contains `notification_type`, `priority=HIGH`, `encounter_id`, `task_id`, `patient_unit`, `hours_elapsed`, `sent_at`
- [ ] `ChargePharmacistEscalationPublisher.publish()` serialises payload with `model_dump_json()` and publishes to `notification-requests` topic
- [ ] `priority="HIGH"` set as a Pub/Sub message attribute
- [ ] `future.result(timeout=10)` — non-retryable failures raise, allowing `MedRecSLAMonitor._handle_breach` to log and surface the error
- [ ] No PHI in log statements — only `encounter_id`, `task_id`, `hours_elapsed` (no patient name, MRN, DOB)
