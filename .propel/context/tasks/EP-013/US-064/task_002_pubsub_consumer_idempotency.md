---
id: TASK-002
title: "Create `notification-service/app/consumer.py` — Pub/Sub Pull Consumer with Idempotency Guard"
user_story: US-064
epic: EP-013
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001]
---

# TASK-002: Create `notification-service/app/consumer.py` — Pub/Sub Pull Consumer with Idempotency Guard

> **Story:** US-064 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-064 DoD specifies:

> *"`NotificationService` Cloud Run service: Pub/Sub pull subscription on `notification-requests`"*
> *"Idempotency check: `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`"*

This task implements the Pub/Sub pull consumer that is the entry point for the `notification-service`. It:

1. Pulls messages from the `notification-requests` subscription
2. Parses and validates the message payload against a Pydantic schema
3. Attempts a `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` to create the `Notification` row
4. Routes to the correct dispatcher (`TwilioSMSDispatcher` or `SendGridEmailDispatcher`) based on `type`
5. ACKs the Pub/Sub message after processing (idempotent check or dispatch)
6. NACKs on validation errors so the message routes to DLQ

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Pull subscription (not push) | Cloud Run services pull Pub/Sub to avoid inbound HTTP surface area and to control concurrency with flow control |
| `INSERT ... ON CONFLICT DO NOTHING` before dispatch | DB uniqueness is checked atomically; avoids SELECT-then-INSERT race on concurrent Pub/Sub deliveries |
| ACK on duplicate idempotency key | Pub/Sub at-least-once guarantees mean a duplicate is normal; ACKing prevents infinite redelivery |
| NACK on Pydantic validation error | Malformed messages are routed to DLQ after `max_delivery_attempts=5` (TR-015) |
| `asyncio`-based pull loop | The Cloud Run service is async-native; blocking pull would stall the event loop |
| `max_messages=10` per pull | Limits memory footprint per container; concurrency controlled by Cloud Run instance count |

Design refs: TR-015, ADR-001, US-064 Technical Notes, design.md §3.1.

---

## Acceptance Criteria Addressed

| US-064 AC | Requirement |
|---|---|
| **Scenario 1** | Consumer receives `type=SMS` message and routes to Twilio dispatcher within 30 seconds |
| **Scenario 2** | Duplicate `idempotency_key` detected by `ON CONFLICT DO NOTHING`; ACK without send |

---

## Implementation Steps

### 1. Create `notification-service/app/schemas.py` — Pub/Sub message schema

```python
"""Pydantic schemas for notification-requests Pub/Sub messages.

Pub/Sub message schema (US-064 Technical Notes):
    {
        "idempotency_key": "NOTIF-001",
        "type": "SMS",                          # or "EMAIL"
        "priority": "HIGH",                     # optional
        "recipient_id": "uuid-string",
        "template": "medication_reminder",
        "substitutions": {"patient_name": "John"}
    }

Validation:
    - `idempotency_key` required, max 255 chars
    - `type` must be "SMS" or "EMAIL"
    - `phone` required when type=SMS; `email` required when type=EMAIL
    - `template` required
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, EmailStr, Field, model_validator


class NotificationTypeEnum(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"


class NotificationPriority(str, Enum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class NotificationRequest(BaseModel):
    """Validated Pub/Sub `notification-requests` message payload."""

    idempotency_key: str = Field(..., max_length=255)
    type: NotificationTypeEnum
    priority: NotificationPriority = NotificationPriority.NORMAL
    recipient_id: str | None = None
    phone: str | None = Field(
        default=None,
        description="E.164 phone number, required when type=SMS",
    )
    email: EmailStr | None = Field(
        default=None,
        description="Recipient email, required when type=EMAIL",
    )
    template: str = Field(..., max_length=128)
    substitutions: dict[str, Any] = Field(default_factory=dict)
    urgency_override: bool = False

    @model_validator(mode="after")
    def _validate_recipient_address(self) -> "NotificationRequest":
        if self.type == NotificationTypeEnum.SMS and not self.phone:
            raise ValueError("phone is required when type=SMS")
        if self.type == NotificationTypeEnum.EMAIL and not self.email:
            raise ValueError("email is required when type=EMAIL")
        return self
```

### 2. Create `notification-service/app/consumer.py`

```python
"""Pub/Sub pull consumer for notification-requests topic.

Pulls messages from the `notification-requests` subscription, validates
the payload, enforces idempotency via `INSERT ... ON CONFLICT DO NOTHING`,
and delegates dispatch to the appropriate channel dispatcher.

Idempotency flow (US-064 AC Scenario 2):
    1. Parse and validate Pub/Sub message payload (Pydantic).
    2. Attempt INSERT with ON CONFLICT (idempotency_key) DO NOTHING.
    3. If 0 rows inserted → duplicate; ACK message and return.
    4. If 1 row inserted → new notification; dispatch and ACK.
    5. On validation error → NACK; DLQ handles after max_delivery_attempts.

Design refs:
    ADR-001 — Pub/Sub event-driven architecture
    TR-015  — DLQ max_delivery_attempts=5
    US-064  — DoD and AC Scenarios 1 and 2
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timezone

from google.cloud import pubsub_v1
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionFactory
from app.dispatchers.sms import TwilioSMSDispatcher
from app.dispatchers.email import SendGridEmailDispatcher
from app.models.notification import Notification, NotificationStatus, NotificationType
from app.schemas import NotificationRequest, NotificationTypeEnum

logger = logging.getLogger(__name__)

_SMS_DISPATCHER = TwilioSMSDispatcher()
_EMAIL_DISPATCHER = SendGridEmailDispatcher()


async def _process_message(
    message_data: bytes,
    ack_id: str,
    subscriber: pubsub_v1.SubscriberClient,
    subscription_path: str,
) -> None:
    """Process a single Pub/Sub notification-requests message.

    Args:
        message_data: Raw base64-decoded Pub/Sub message body.
        ack_id: Pub/Sub ACK ID for this message.
        subscriber: Pub/Sub subscriber client.
        subscription_path: Fully-qualified subscription path.
    """
    # --- 1. Parse and validate payload ---
    try:
        payload = json.loads(message_data)
        request = NotificationRequest.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error(
            "notification_consumer.invalid_payload",
            extra={"error": str(exc), "raw": message_data[:200]},
        )
        # NACK — routes to DLQ after max_delivery_attempts
        subscriber.modify_ack_deadline(
            request=pubsub_v1.types.ModifyAckDeadlineRequest(
                subscription=subscription_path,
                ack_ids=[ack_id],
                ack_deadline_seconds=0,
            )
        )
        return

    async with AsyncSessionFactory() as session:
        notification_id = uuid.uuid4()

        # --- 2. Idempotency INSERT (ON CONFLICT DO NOTHING) ---
        rows_inserted = await _upsert_notification(session, notification_id, request)

        if rows_inserted == 0:
            # Duplicate — idempotency_key already exists; safe to ACK and skip
            logger.info(
                "notification_consumer.duplicate_skipped",
                extra={"idempotency_key": request.idempotency_key},
            )
            subscriber.acknowledge(
                request=pubsub_v1.types.AcknowledgeRequest(
                    subscription=subscription_path, ack_ids=[ack_id]
                )
            )
            return

        # --- 3. Route to dispatcher ---
        try:
            if request.type == NotificationTypeEnum.SMS:
                await _SMS_DISPATCHER.dispatch(session, notification_id, request)
            else:
                await _EMAIL_DISPATCHER.dispatch(session, notification_id, request)
        except Exception as exc:
            # Dispatcher handles retry scheduling; consumer ACKs to avoid
            # redundant Pub/Sub redelivery (dispatcher owns retry via APScheduler)
            logger.exception(
                "notification_consumer.dispatch_error",
                extra={"idempotency_key": request.idempotency_key, "error": str(exc)},
            )

    # ACK regardless — retry is owned by APScheduler (TASK-003), not Pub/Sub
    subscriber.acknowledge(
        request=pubsub_v1.types.AcknowledgeRequest(
            subscription=subscription_path, ack_ids=[ack_id]
        )
    )


async def _upsert_notification(
    session: AsyncSession,
    notification_id: uuid.UUID,
    request: NotificationRequest,
) -> int:
    """INSERT notification row with idempotency guard.

    Uses ``INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`` so
    concurrent deliveries of the same Pub/Sub message are safe.

    Returns:
        1 if a new row was inserted; 0 if the idempotency key already existed.
    """
    recipient_address = request.phone if request.type == NotificationTypeEnum.SMS else request.email
    result = await session.execute(
        text(
            """
            INSERT INTO notification (
                id, idempotency_key, type, recipient_id, phone_or_email,
                template, substitutions, status, retry_count, created_at, updated_at
            ) VALUES (
                :id, :idempotency_key, :type, :recipient_id, :phone_or_email,
                :template, CAST(:substitutions AS jsonb), 'PENDING', 0, now(), now()
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            """
        ),
        {
            "id": str(notification_id),
            "idempotency_key": request.idempotency_key,
            "type": request.type.value,
            "recipient_id": request.recipient_id,
            "phone_or_email": recipient_address,
            "template": request.template,
            "substitutions": json.dumps(request.substitutions),
        },
    )
    await session.commit()
    return result.rowcount


async def run_consumer(project_id: str, subscription_id: str) -> None:
    """Start the Pub/Sub pull loop for notification-requests.

    Pulls up to 10 messages per batch, processes each, and ACKs/NACKs
    based on processing outcome. Runs indefinitely until cancelled.

    Args:
        project_id: GCP project ID.
        subscription_id: Pub/Sub subscription ID (e.g. ``notification-service-sub``).
    """
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(project_id, subscription_id)
    logger.info("notification_consumer.started", extra={"subscription": subscription_path})

    while True:
        response = subscriber.pull(
            request=pubsub_v1.types.PullRequest(
                subscription=subscription_path,
                max_messages=10,
            ),
            timeout=30,
        )

        for received_message in response.received_messages:
            data = base64.b64decode(received_message.message.data)
            await _process_message(
                message_data=data,
                ack_id=received_message.ack_id,
                subscriber=subscriber,
                subscription_path=subscription_path,
            )
```

### 3. Create `notification-service/app/main.py` — Cloud Run entrypoint

```python
"""notification-service Cloud Run entrypoint.

Starts the Pub/Sub consumer on service startup.
Exposes /health and /ready HTTP probes for Cloud Run liveness checks (TR-016).
"""
from __future__ import annotations

import asyncio
import os

import uvicorn
from fastapi import FastAPI

from app.consumer import run_consumer
from app.db.session import init_db

app = FastAPI(title="SmartHandoff Notification Service")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> dict:
    return {"status": "ready"}


@app.on_event("startup")
async def _startup() -> None:
    await init_db()
    project_id = os.environ["GCP_PROJECT_ID"]
    subscription_id = os.environ.get("PUBSUB_SUBSCRIPTION_ID", "notification-service-sub")
    asyncio.create_task(run_consumer(project_id, subscription_id))


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
```

---

## Validation

```bash
# Start local service with emulator
export PUBSUB_EMULATOR_HOST=localhost:8085
export GCP_PROJECT_ID=smarthandoff-dev
export PUBSUB_SUBSCRIPTION_ID=notification-service-sub

cd notification-service
uvicorn app.main:app --reload

# Publish a test SMS message
gcloud pubsub topics publish notification-requests \
  --message='{"idempotency_key":"NOTIF-TEST-001","type":"SMS","phone":"+15005550006","template":"medication_reminder","substitutions":{"name":"Test Patient"}}'

# Verify DB row created with status=PENDING
psql -c "SELECT idempotency_key, type, status FROM notification WHERE idempotency_key='NOTIF-TEST-001';"

# Re-publish same message — verify 0 new rows (idempotency)
gcloud pubsub topics publish notification-requests \
  --message='{"idempotency_key":"NOTIF-TEST-001","type":"SMS","phone":"+15005550006","template":"medication_reminder","substitutions":{"name":"Test Patient"}}'
psql -c "SELECT COUNT(*) FROM notification WHERE idempotency_key='NOTIF-TEST-001';"
# Expected: 1
```

---

## Files Touched

| File | Action |
|------|--------|
| `notification-service/app/schemas.py` | Create |
| `notification-service/app/consumer.py` | Create |
| `notification-service/app/main.py` | Create |

---

## Definition of Done Checklist

- [ ] `NotificationRequest` Pydantic schema validates all fields from US-064 Technical Notes
- [ ] `phone` required when `type=SMS`; `email` required when `type=EMAIL` — validated by `@model_validator`
- [ ] `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING` returns `rowcount=0` on duplicate
- [ ] Duplicate messages are ACKed without dispatching
- [ ] Validation errors NACK the Pub/Sub message
- [ ] `/health` and `/ready` endpoints return 200 OK
- [ ] Consumer starts as a background `asyncio.Task` on FastAPI startup

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `notification` ORM model and DB schema must exist |
| TASK-003 | Task | `TwilioSMSDispatcher` imported by consumer |
| TASK-004 | Task | `SendGridEmailDispatcher` imported by consumer |
