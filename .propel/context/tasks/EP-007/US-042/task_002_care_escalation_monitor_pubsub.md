---
id: TASK-002
title: "`CareEscalationMonitor` — Pub/Sub Subscriber + Initial CARE_TEAM_ESCALATION Notification"
user_story: US-042
epic: EP-007
sprint: 2
layer: Backend / AI Agent
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-042/TASK-001, US-039/TASK-004]
---

# TASK-002: `CareEscalationMonitor` — Pub/Sub Subscriber + Initial CARE_TEAM_ESCALATION Notification

> **Story:** US-042 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / AI Agent | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-042 AC Scenario 1 requires that when the chatbot agent (EP-008) sets `urgency_flag=True`, a `CARE_TEAM_ESCALATION` notification is published to `notification-requests` within **60 seconds** of the flag being set.

The chatbot agent publishes a `URGENCY_FLAG_SET` Pub/Sub event to the `patient-events` topic. The follow-up care agent subscribes via the `urgency-escalation-sub` subscription and handles:

1. Receive `URGENCY_FLAG_SET` event
2. Look up the encounter and on-call nurse (`app_user WHERE role=ON_CALL_NURSE AND unit=encounter.current_unit`)
3. Create a `care_escalation` record (`status=PENDING`) — idempotency-guarded
4. Publish `CARE_TEAM_ESCALATION` message to `notification-requests` (SMS to on-call nurse)
5. ACK the Pub/Sub message

The 60-second SLA starts from when the Pub/Sub event is published by EP-008. Network propagation + pull latency is typically <2 seconds for Pub/Sub. The DB write and `notification-requests` publish must complete within the remaining window. This task must NOT perform any synchronous FHIR API calls on the critical path — encounter data is read from the SmartHandoff DB.

**`URGENCY_FLAG_SET` event envelope (published by EP-008):**

```json
{
  "event_type": "URGENCY_FLAG_SET",
  "encounter_id": "uuid",
  "patient_id": "uuid",
  "chatbot_transcript_id": "uuid",
  "urgency_flag_set_at": "2026-07-17T10:00:00Z"
}
```

**`CARE_TEAM_ESCALATION` message published to `notification-requests`:**

```json
{
  "event_type": "CARE_TEAM_ESCALATION",
  "escalation_id": "uuid",
  "encounter_id": "uuid",
  "patient_id": "uuid",
  "nurse_user_id": "uuid",
  "channel": "SMS",
  "idempotency_key": "NOTIF-ESC-{escalation_id}"
}
```

The Notification Service (US-064) resolves the nurse's phone from `app_user.phone` at dispatch time.

**Design references:**
- design.md §3.1 — Follow-up Care Agent responsibility: risk scoring, appointment scheduling, reminder dispatch
- design.md §3.2 — Agent container pattern: Pub/Sub consumer → DB write → Pub/Sub publish
- design.md §5.1 TR-015 — Dead-letter queue on all agent subscriptions; max_delivery_attempts=5
- design.md §7.4 AIR-040 — Notification Service idempotency key prevents duplicate sends
- US-042 AC Scenario 1 — `CARE_TEAM_ESCALATION` published within 60 seconds of urgency flag set
- US-042 Technical Notes — on-call nurse: `app_user WHERE role=ON_CALL_NURSE AND unit=encounter.current_unit`
- ADR-001 — Pub/Sub at-least-once; idempotency required
- ADR-007 — PHI (nurse phone) resolved at dispatch, not stored in escalation record

---

## Acceptance Criteria Addressed

| US-042 AC Scenario | Coverage |
|---|---|
| **Scenario 1** | `CARE_TEAM_ESCALATION` published to `notification-requests` within 60 s of `URGENCY_FLAG_SET` receipt; on-call nurse SMS dispatched |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p backend/app/agents/followup_care/escalation
touch backend/app/agents/followup_care/escalation/__init__.py
touch backend/app/agents/followup_care/escalation/monitor.py
touch backend/app/agents/followup_care/escalation/schemas.py
```

### 2. Define event schemas in `backend/app/agents/followup_care/escalation/schemas.py`

```python
"""Pydantic schemas for URGENCY_FLAG_SET and CARE_TEAM_ESCALATION events.

Design refs:
    US-042 Technical Notes — event envelope formats
    design.md §3.2 — Pydantic structured output per agent pattern
    ADR-001 — Pub/Sub event contracts
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UrgencyFlagSetEvent(BaseModel):
    """Inbound Pub/Sub event published by the chatbot agent (EP-008)."""

    event_type: Literal["URGENCY_FLAG_SET"]
    encounter_id: UUID
    patient_id: UUID
    chatbot_transcript_id: UUID
    urgency_flag_set_at: datetime = Field(
        description="UTC timestamp when the chatbot set urgency_flag=True."
    )


class CareTeamEscalationMessage(BaseModel):
    """Outbound message published to the notification-requests Pub/Sub topic.

    PHI policy:
        nurse_user_id is a UUID reference only. The Notification Service resolves
        the nurse's phone number from app_user at dispatch time (ADR-007).
    """

    event_type: Literal["CARE_TEAM_ESCALATION"] = "CARE_TEAM_ESCALATION"
    escalation_id: UUID
    encounter_id: UUID
    patient_id: UUID
    nurse_user_id: UUID
    channel: Literal["SMS"] = "SMS"
    idempotency_key: str = Field(
        description="Format: NOTIF-ESC-{escalation_id}. Prevents duplicate SMS on notification redelivery."
    )
```

### 3. Implement `backend/app/agents/followup_care/escalation/monitor.py`

```python
"""CareEscalationMonitor — processes URGENCY_FLAG_SET events from the patient-events topic.

Responsibility:
    1. Receive URGENCY_FLAG_SET message from Pub/Sub subscription urgency-escalation-sub
    2. Look up encounter + on-call nurse from SmartHandoff DB
    3. Create care_escalation record (idempotency-guarded INSERT ... ON CONFLICT DO NOTHING)
    4. Publish CARE_TEAM_ESCALATION to notification-requests topic
    5. ACK the Pub/Sub message

SLA:
    The 60-second window (US-042 AC Scenario 1) starts from the Pub/Sub message publish_time.
    This handler MUST NOT make synchronous FHIR API calls. All data is read from the local DB.

PHI handling:
    Logs contain only encounter_id (UUID), escalation_id (UUID), and nurse_user_id (UUID).
    No patient name, MRN, DOB, phone, or email in any log line.

Design refs:
    design.md §3.2 — agent container pattern
    US-042 AC Scenario 1
    ADR-001 (idempotency), ADR-007 (PHI logs)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from google.cloud import pubsub_v1
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.followup_care.escalation.schemas import (
    CareTeamEscalationMessage,
    UrgencyFlagSetEvent,
)
from app.models.app_user import AppUser
from app.models.care_escalation import CareEscalation
from app.models.enums import CareEscalationStatus
from app.models.encounter import Encounter

logger = logging.getLogger(__name__)

ON_CALL_NURSE_ROLE = "ON_CALL_NURSE"


class CareEscalationMonitor:
    """Processes URGENCY_FLAG_SET events and creates initial care team escalations.

    Args:
        session_factory: Async SQLAlchemy session factory for DB operations.
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

    async def handle_urgency_flag_set(
        self,
        message: pubsub_v1.subscriber.message.Message,
    ) -> None:
        """Main entry point called by the Pub/Sub pull subscriber.

        Validates the event, creates the escalation record, and publishes the
        CARE_TEAM_ESCALATION notification — all within the 60-second SLA window.

        Args:
            message: Raw Pub/Sub message from urgency-escalation-sub.
        """
        try:
            event = self._parse_event(message)
        except Exception as exc:
            logger.error(
                "care_escalation_monitor.parse_failure",
                extra={"error": str(exc), "message_id": message.message_id},
            )
            # NACK — let DLQ handle after max_delivery_attempts=5
            message.nack()
            return

        idempotency_key = f"ESC-{event.encounter_id}"
        logger.info(
            "care_escalation_monitor.urgency_flag_received",
            extra={
                "encounter_id": str(event.encounter_id),
                "idempotency_key": idempotency_key,
            },
        )

        async with self._session_factory() as session:
            try:
                escalation = await self._get_or_create_escalation(
                    session=session,
                    event=event,
                    idempotency_key=idempotency_key,
                )
                if escalation is None:
                    # Duplicate event — already processed (idempotency hit)
                    logger.info(
                        "care_escalation_monitor.duplicate_event_skipped",
                        extra={"idempotency_key": idempotency_key},
                    )
                    message.ack()
                    return

                await self._publish_care_team_escalation(escalation)
                await session.commit()

                logger.info(
                    "care_escalation_monitor.escalation_created",
                    extra={
                        "escalation_id": str(escalation.id),
                        "encounter_id": str(escalation.encounter_id),
                        "nurse_user_id": str(escalation.notified_nurse_user_id),
                    },
                )
                message.ack()

            except Exception as exc:
                await session.rollback()
                logger.error(
                    "care_escalation_monitor.processing_error",
                    extra={
                        "encounter_id": str(event.encounter_id),
                        "error": str(exc),
                    },
                )
                message.nack()

    def _parse_event(self, message: pubsub_v1.subscriber.message.Message) -> UrgencyFlagSetEvent:
        """Deserialise and validate the Pub/Sub message payload."""
        payload = json.loads(message.data.decode("utf-8"))
        return UrgencyFlagSetEvent(**payload)

    async def _get_or_create_escalation(
        self,
        session: AsyncSession,
        event: UrgencyFlagSetEvent,
        idempotency_key: str,
    ) -> CareEscalation | None:
        """Create a CareEscalation record using INSERT ... ON CONFLICT DO NOTHING.

        Returns the new CareEscalation record, or None if the idempotency key
        already exists (duplicate Pub/Sub delivery).
        """
        # Fetch encounter to determine current unit for on-call nurse lookup
        encounter: Encounter | None = await session.get(Encounter, event.encounter_id)
        if encounter is None:
            raise ValueError(f"Encounter {event.encounter_id} not found in DB")

        # Resolve on-call nurse for the encounter's current unit
        nurse = await self._resolve_on_call_nurse(session, encounter.current_unit)
        if nurse is None:
            # No on-call nurse configured — log warning and proceed without nurse FK
            logger.warning(
                "care_escalation_monitor.no_on_call_nurse",
                extra={
                    "encounter_id": str(event.encounter_id),
                    "unit": encounter.current_unit,
                },
            )

        escalation = CareEscalation(
            id=uuid.uuid4(),
            encounter_id=event.encounter_id,
            patient_id=event.patient_id,
            notified_nurse_user_id=nurse.id if nurse else None,
            status=CareEscalationStatus.PENDING,
            sent_at=datetime.now(tz=timezone.utc),
            escalated_to_supervisor=False,
            idempotency_key=idempotency_key,
        )

        # INSERT ... ON CONFLICT (idempotency_key) DO NOTHING
        session.add(escalation)
        try:
            await session.flush()  # Flushes to detect conflict before commit
        except Exception:
            # Unique constraint violation → duplicate delivery
            await session.rollback()
            return None

        return escalation

    async def _resolve_on_call_nurse(
        self,
        session: AsyncSession,
        unit: str | None,
    ) -> AppUser | None:
        """Look up the on-call nurse assigned to the given unit.

        Query: app_user WHERE role=ON_CALL_NURSE AND unit=encounter.current_unit
        Returns the first matching AppUser, or None if no on-call nurse configured.
        """
        if unit is None:
            return None

        result = await session.execute(
            select(AppUser).where(
                AppUser.role == ON_CALL_NURSE_ROLE,
                AppUser.unit == unit,
                AppUser.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def _publish_care_team_escalation(self, escalation: CareEscalation) -> None:
        """Publish CARE_TEAM_ESCALATION to the notification-requests Pub/Sub topic.

        PHI policy:
            Only UUIDs are included. The Notification Service resolves nurse phone
            from app_user at dispatch time (ADR-007).
        """
        if escalation.notified_nurse_user_id is None:
            logger.warning(
                "care_escalation_monitor.escalation_no_nurse_notified",
                extra={"escalation_id": str(escalation.id)},
            )
            return

        message = CareTeamEscalationMessage(
            escalation_id=escalation.id,
            encounter_id=escalation.encounter_id,
            patient_id=escalation.patient_id,
            nurse_user_id=escalation.notified_nurse_user_id,
            idempotency_key=f"NOTIF-ESC-{escalation.id}",
        )
        payload = message.model_dump_json().encode("utf-8")
        future = self._publisher.publish(self._notification_topic, payload)
        future.result(timeout=10)  # Block until confirmed — within 60-second SLA budget
```

### 4. Register the Pub/Sub subscription in the followup-care agent startup

In `backend/app/agents/followup_care/main.py`, add the `urgency-escalation-sub` subscriber alongside the existing `followup-agent-sub`:

```python
# In agent startup (backend/app/agents/followup_care/main.py)
# Add after existing adt-events subscriber setup:

from app.agents.followup_care.escalation.monitor import CareEscalationMonitor

escalation_monitor = CareEscalationMonitor(
    session_factory=async_session_factory,
    publisher=publisher_client,
    notification_topic=settings.NOTIFICATION_REQUESTS_TOPIC,
)

urgency_subscriber = subscriber_client.subscribe(
    subscription=settings.URGENCY_ESCALATION_SUBSCRIPTION,  # urgency-escalation-sub
    callback=lambda msg: asyncio.run_coroutine_threadsafe(
        escalation_monitor.handle_urgency_flag_set(msg),
        event_loop,
    ).result(),
)
```

### 5. Add required settings to `backend/app/core/config.py`

```python
# Append to Settings class in backend/app/core/config.py

PATIENT_EVENTS_TOPIC: str = Field(
    default="projects/{project_id}/topics/patient-events",
    description="Pub/Sub topic published to by the chatbot agent (EP-008).",
)
URGENCY_ESCALATION_SUBSCRIPTION: str = Field(
    default="projects/{project_id}/subscriptions/urgency-escalation-sub",
    description="Pub/Sub subscription for URGENCY_FLAG_SET events consumed by the follow-up care agent.",
)
NOTIFICATION_REQUESTS_TOPIC: str = Field(
    default="projects/{project_id}/topics/notification-requests",
    description="Pub/Sub topic for outbound notification dispatch requests.",
)
```

---

## Definition of Done Checklist

- [ ] `backend/app/agents/followup_care/escalation/schemas.py` created with `UrgencyFlagSetEvent` and `CareTeamEscalationMessage`
- [ ] `backend/app/agents/followup_care/escalation/monitor.py` created with `CareEscalationMonitor`
- [ ] `_get_or_create_escalation()` uses `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` for idempotency
- [ ] `_resolve_on_call_nurse()` queries `app_user WHERE role=ON_CALL_NURSE AND unit=encounter.current_unit`
- [ ] `_publish_care_team_escalation()` publishes only UUIDs — no PHI
- [ ] `urgency-escalation-sub` subscription registered in followup-care agent startup
- [ ] `URGENCY_ESCALATION_SUBSCRIPTION` and `NOTIFICATION_REQUESTS_TOPIC` settings added
- [ ] No PHI (name, MRN, DOB, phone, email) in any log line

---

## Notes

- **SLA**: The 60-second window is from Pub/Sub message `publish_time` to when `CARE_TEAM_ESCALATION` is published to `notification-requests`. The actual SMS delivery time (Twilio) is beyond this boundary and tracked by the Notification Service.
- **No-nurse fallback**: If no `ON_CALL_NURSE` is configured for the unit, the escalation record is still created (for the 15-minute re-escalation monitor to track), but `notified_nurse_user_id=NULL`. A warning log is emitted — ops should configure on-call coverage.
- **DLQ**: The `urgency-escalation-sub` must be provisioned with `max_delivery_attempts=5` and a dead-letter topic per design.md TR-015. Provisioning is covered by the Terraform IaC (`infra/terraform/modules/pubsub/`).
