---
id: TASK-003
title: "Notification Service — Scheduled Notification Polling Loop, Dispatch & Opt-Out Enforcement"
user_story: US-041
epic: EP-007
sprint: 2
layer: Backend / Notification Service
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-041/TASK-001, US-064/TASK-001, US-064]
---

# TASK-003: Notification Service — Scheduled Notification Polling Loop, Dispatch & Opt-Out Enforcement

> **Story:** US-041 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / Notification Service | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-041 DoD specifies:

> *"Notification service reads scheduled notifications from DB and dispatches at `send_at` time"*
> *"Opt-out flag respected: `patient.notification_opt_out=True` → skip + log"*

US-064 built the `NotificationService` to dispatch SMS (Twilio) and email (SendGrid) from Pub/Sub `notification-requests` messages. This task **extends** the Notification Service with a second dispatch pathway: a **scheduled polling loop** that fires every 5 minutes and delivers `scheduled_notification` records whose `send_at <= now()` and `delivery_status=PENDING`.

The two pathways are independent:
- **Pub/Sub pathway** (US-064): real-time alerts (medication reminders, pharmacist alerts)
- **Scheduled polling pathway** (US-041): time-deferred notifications (48-hour check-ins)

Both pathways share the same Twilio/SendGrid clients and opt-out enforcement logic.

**Polling query:**

```sql
SELECT sn.*, p.first_name, p.preferred_contact, p.notification_opt_out,
       p.phone, p.email
FROM   scheduled_notification sn
JOIN   patient p ON p.id = sn.patient_id
WHERE  sn.send_at <= NOW()
AND    sn.delivery_status = 'PENDING'
AND    sn.deleted_at IS NULL
ORDER  BY sn.send_at ASC
LIMIT  100
```

Polling frequency: every 5 minutes (US-041 Technical Notes). APScheduler `AsyncIOScheduler` (already used in US-064 for retry scheduling) manages the interval job.

**Check-in message content** (US-041 Technical Notes):

```
Hi [first_name], it's been 48 hours since your discharge. How are you feeling?
Reply to let us know or call [care_team_number] with any concerns.
```

`first_name` is decrypted at dispatch time from the encrypted `patient.first_name` field (ADR-007). The care team number is resolved from the application configuration (not from a patient field).

**PHI handling:**
- `patient.first_name` (decrypted by ORM `EncryptedString` type) — included in message body
- `patient.phone` / `patient.email` (decrypted) — used as dispatch recipient
- Neither field is logged; only `scheduled_notification.id` and `encounter_id` appear in structured logs (BR-020, AIR-021)

**Design references:**
- design.md §3.1 — Notification Service Cloud Run: Python, Twilio SDK + SendGrid SDK
- design.md §9.2 — `notification-svc`: min=1, max=5, 1 vCPU, 512 MB, Concurrency=50
- US-041 Technical Notes — polling every 5 min; `send_at` from `discharge_time + 48h`
- US-041 AC Scenario 3 — email sent to `patient.email` using "48-hour check-in" SendGrid template
- US-041 AC Scenario 4 — `patient.notification_opt_out=True` → `delivery_status=OPTED_OUT`, no send
- AIR-040 — Notification Service dispatches via Twilio or SendGrid based on `channel` field
- AIR-041 — Twilio delivery webhook updates status (reused from US-064)

---

## Acceptance Criteria Addressed

| US-041 AC Scenario | Coverage |
|---|---|
| **Scenario 3** | Email dispatched via SendGrid "48-hour check-in" Dynamic Template; `delivery_status` updated to `SENT` |
| **Scenario 4** | `patient.notification_opt_out=True` → `delivery_status=OPTED_OUT`; no SMS/email sent |

---

## Implementation Steps

### 1. Create `notification-service/app/scheduled_dispatcher.py`

```python
"""Scheduled notification polling dispatcher — US-041.

Runs every 5 minutes (APScheduler AsyncIOScheduler) to query
`scheduled_notification` for rows where:
    send_at <= NOW()  AND  delivery_status = PENDING

For each due notification:
    1. Check patient opt-out flag  → mark OPTED_OUT and continue
    2. Decrypt patient contact details (phone / email) from ORM EncryptedString
    3. Dispatch via Twilio (SMS) or SendGrid (email)
    4. Update delivery_status to SENT on success, FAILED on error

PHI handling:
    Only patient.first_name appears in the message body.
    Logs contain only scheduled_notification.id and encounter_id (no PHI).
    Patient phone / email are never written to structured logs (ADR-007, AIR-021).

Design refs:
    US-041 AC Scenarios 3, 4
    US-041 Technical Notes — poll every 5 min; PHI minimisation (first_name only)
    design.md §3.1 — Notification Service
    AIR-040 — dispatch via Twilio (SMS) or SendGrid (email)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.patient import Patient
from app.models.scheduled_notification import (
    DeliveryStatus,
    NotificationChannel,
    ScheduledNotification,
)
from app.services.email_service import send_checkin_email
from app.services.sms_service import send_checkin_sms

logger = logging.getLogger(__name__)

# US-041 Technical Notes: poll every 5 minutes
POLL_INTERVAL_SECONDS: int = 300
POLL_BATCH_LIMIT: int = 100


async def dispatch_due_notifications(session_factory: async_sessionmaker) -> None:
    """Query and dispatch all scheduled notifications with send_at <= now().

    Called by APScheduler every POLL_INTERVAL_SECONDS seconds.
    """
    now = datetime.now(tz=timezone.utc)

    async with session_factory() as session:
        result = await session.execute(
            select(ScheduledNotification)
            .options(joinedload(ScheduledNotification.patient))
            .where(
                ScheduledNotification.send_at <= now,
                ScheduledNotification.delivery_status == DeliveryStatus.PENDING,
                ScheduledNotification.deleted_at.is_(None),
            )
            .order_by(ScheduledNotification.send_at.asc())
            .limit(POLL_BATCH_LIMIT)
        )
        due: list[ScheduledNotification] = list(result.scalars().all())

    logger.info("scheduled_dispatch_poll", extra={"due_count": len(due), "poll_time": now.isoformat()})

    for notification in due:
        await _process_notification(session_factory=session_factory, notification=notification)


async def _process_notification(
    *,
    session_factory: async_sessionmaker,
    notification: ScheduledNotification,
) -> None:
    """Dispatch a single ScheduledNotification and update its delivery_status."""
    patient: Patient = notification.patient

    # US-041 AC Scenario 4 — opt-out check before any dispatch
    if patient.notification_opt_out:
        await _update_status(
            session_factory=session_factory,
            notification_id=notification.id,
            new_status=DeliveryStatus.OPTED_OUT,
        )
        logger.info(
            "notification_opted_out",
            extra={
                "scheduled_notification_id": str(notification.id),
                "encounter_id": str(notification.encounter_id),
            },
        )
        return

    # Decrypt contact details via ORM EncryptedString (transparent to caller)
    first_name: str = patient.first_name  # decrypted by SQLAlchemy TypeDecorator
    care_team_number: str = settings.care_team_contact_number

    try:
        if notification.channel == NotificationChannel.SMS:
            phone: str = patient.phone  # decrypted
            await send_checkin_sms(
                to_phone=phone,
                first_name=first_name,
                care_team_number=care_team_number,
            )
        else:
            email: str = patient.email  # decrypted
            await send_checkin_email(
                to_email=email,
                first_name=first_name,
                care_team_number=care_team_number,
            )

        await _update_status(
            session_factory=session_factory,
            notification_id=notification.id,
            new_status=DeliveryStatus.SENT,
        )
        logger.info(
            "notification_sent",
            extra={
                "scheduled_notification_id": str(notification.id),
                "encounter_id": str(notification.encounter_id),
                "channel": notification.channel.value,
            },
        )

    except Exception as exc:
        await _update_status(
            session_factory=session_factory,
            notification_id=notification.id,
            new_status=DeliveryStatus.FAILED,
        )
        logger.error(
            "notification_dispatch_failed",
            extra={
                "scheduled_notification_id": str(notification.id),
                "encounter_id": str(notification.encounter_id),
                "error": str(exc),
            },
        )


async def _update_status(
    *,
    session_factory: async_sessionmaker,
    notification_id,
    new_status: DeliveryStatus,
) -> None:
    """Update delivery_status in a separate DB session to avoid long-lived transactions."""
    async with session_factory() as session:
        async with session.begin():
            result = await session.get(ScheduledNotification, notification_id)
            if result:
                result.delivery_status = new_status


def register_scheduled_dispatcher(scheduler: AsyncIOScheduler, session_factory: async_sessionmaker) -> None:
    """Register the polling job with an existing APScheduler instance.

    Call this from notification-service/app/main.py during startup.
    """
    scheduler.add_job(
        dispatch_due_notifications,
        trigger="interval",
        seconds=POLL_INTERVAL_SECONDS,
        kwargs={"session_factory": session_factory},
        id="scheduled_notification_dispatcher",
        replace_existing=True,
        misfire_grace_time=60,
    )
    logger.info(
        "scheduled_dispatcher_registered",
        extra={"poll_interval_seconds": POLL_INTERVAL_SECONDS},
    )
```

### 2. Create `notification-service/app/services/sms_service.py` (check-in variant)

```python
"""SMS dispatch for 48-hour post-discharge check-in notifications.

Message template (US-041 Technical Notes):
    "Hi {first_name}, it's been 48 hours since your discharge. How are you feeling?
     Reply to let us know or call {care_team_number} with any concerns."

PHI minimisation: only first_name is included in the message body.
MRN, last name, DOB, and phone number are NOT included (AIR-021).
"""
from __future__ import annotations

from twilio.rest import Client as TwilioClient

from app.config import settings


async def send_checkin_sms(
    *,
    to_phone: str,
    first_name: str,
    care_team_number: str,
) -> None:
    """Send the 48-hour check-in SMS via Twilio.

    Args:
        to_phone: Patient's decrypted phone number (E.164 format).
        first_name: Patient's decrypted first name (PHI — not logged).
        care_team_number: Care team contact number from app config.

    Raises:
        TwilioRestException: On Twilio API error (caller handles retry).
    """
    client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    body = (
        f"Hi {first_name}, it's been 48 hours since your discharge. "
        f"How are you feeling? Reply to let us know or call "
        f"{care_team_number} with any concerns."
    )
    client.messages.create(
        body=body,
        from_=settings.twilio_from_number,
        to=to_phone,
    )
```

### 3. Create `notification-service/app/services/email_service.py` (check-in variant)

```python
"""Email dispatch for 48-hour post-discharge check-in notifications.

Uses a SendGrid Dynamic Template (AIR-042). Template substitutions:
    {{first_name}}         — patient's first name (only PHI in substitutions)
    {{care_team_number}}   — care team phone number from config

Design refs:
    US-041 AC Scenario 3 — "48-hour check-in" SendGrid template
    AIR-042 — SendGrid Dynamic Templates versioned in source control
"""
from __future__ import annotations

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, To, DynamicTemplateData

from app.config import settings


async def send_checkin_email(
    *,
    to_email: str,
    first_name: str,
    care_team_number: str,
) -> None:
    """Send the 48-hour check-in email via SendGrid Dynamic Template.

    Args:
        to_email: Patient's decrypted email address (PHI — not logged).
        first_name: Patient's decrypted first name (included in template substitution).
        care_team_number: Care team contact number from app config.

    Raises:
        Exception: On SendGrid API error (caller handles status update to FAILED).
    """
    message = Mail(
        from_email=settings.sendgrid_from_email,
        to_emails=To(to_email),
    )
    message.template_id = settings.sendgrid_checkin_48h_template_id
    message.dynamic_template_data = DynamicTemplateData({
        "first_name": first_name,
        "care_team_number": care_team_number,
    })

    sg = SendGridAPIClient(settings.sendgrid_api_key)
    response = sg.send(message)
    response.raise_for_status()
```

### 4. Register polling job in `notification-service/app/main.py`

```python
# Add to existing startup lifespan in main.py:
from app.scheduled_dispatcher import register_scheduled_dispatcher

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Existing: start Pub/Sub consumer, APScheduler for retry
    scheduler.start()
    register_scheduled_dispatcher(scheduler=scheduler, session_factory=async_session)
    yield
    scheduler.shutdown()
```

### 5. Add `settings` fields to `notification-service/app/config.py`

```python
# Add to existing Settings (pydantic-settings BaseSettings):
sendgrid_checkin_48h_template_id: str  # from Secret Manager
care_team_contact_number: str           # from Secret Manager or env
```

---

## Validation

- [ ] APScheduler job `scheduled_notification_dispatcher` appears in `scheduler.get_jobs()` on startup
- [ ] Manual trigger: insert a `ScheduledNotification` with `send_at = NOW() - 1 minute`, `delivery_status=PENDING` → polling loop dispatches within 5 minutes, `delivery_status` updated to `SENT`
- [ ] Opt-out: patient with `notification_opt_out=True` → `delivery_status=OPTED_OUT`, no Twilio/SendGrid call made
- [ ] Preferred contact `email` → `send_checkin_email()` called; `sms` (or null) → `send_checkin_sms()` called
- [ ] Twilio error raises exception → `delivery_status=FAILED`
- [ ] Structured log for `notification_sent` contains `scheduled_notification_id` and `encounter_id` only — no `first_name`, `phone`, or `email`
- [ ] `mypy notification-service/app/scheduled_dispatcher.py --strict` exits 0
- [ ] `ruff check notification-service/app/scheduled_dispatcher.py` exits 0

---

## Files Produced

| File | Change |
|------|--------|
| `notification-service/app/scheduled_dispatcher.py` | New — polling loop |
| `notification-service/app/services/sms_service.py` | New — check-in SMS helper |
| `notification-service/app/services/email_service.py` | New — check-in email helper |
| `notification-service/app/main.py` | Modified — register polling job in startup lifespan |
| `notification-service/app/config.py` | Modified — add `sendgrid_checkin_48h_template_id`, `care_team_contact_number` |
