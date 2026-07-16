---
id: TASK-003
title: "Create `notification-service/app/dispatchers/sms.py` — Twilio SMS Dispatcher with APScheduler Retry"
user_story: US-064
epic: EP-013
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Create `notification-service/app/dispatchers/sms.py` — Twilio SMS Dispatcher with APScheduler Retry

> **Story:** US-064 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-064 DoD specifies:

> *"Twilio SMS: `twilio.rest.Client.messages.create(to, from, template_id, substitutions)`"*
> *"Retry: APScheduler retries failed notifications 3× with 30s/60s/120s backoff"*
> *"Opt-out flag: `patient.notification_opt_out=True` → skip send + log"*

US-064 AC Scenario 4 mandates:

> *"If all 3 fail, `notification.status=FAILED` and a `CARE_TEAM_ALERT` is published for manual follow-up."*

This task implements `TwilioSMSDispatcher` — the component that wraps the Twilio REST SDK, enforces the patient opt-out check, and schedules APScheduler jobs for retry with the 30 s/60 s/120 s backoff schedule on transient failures.

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Twilio credentials loaded from Secret Manager at runtime | Never hardcoded; `account_sid` and `auth_token` fetched via `google-cloud-secret-manager` (US-064 Technical Notes) |
| APScheduler `BackgroundScheduler` for retry | Cloud Run containers are long-lived (min-instances=1); APScheduler runs in-process without needing a separate worker or Celery broker |
| Retry delays 30 s / 60 s / 120 s | Matches US-064 DoD explicitly; these are wall-clock delays, not backoff from first send |
| Opt-out check queries `patient.notification_opt_out` before any Twilio call | Prevents PHI-bearing SMS to opted-out patients; status set to `OPTED_OUT` and logged |
| `CARE_TEAM_ALERT` published to `notification-requests` DLQ / dedicated topic on final failure | Decouples alert from SMS path; staff alert can use email/different channel |
| HTTP 503 from Twilio → `RetryableError`; HTTP 400 → immediate `FAILED` | Transient Twilio errors are retried; permanent config errors (invalid number, banned content) are not |

Design refs: US-064 AC Scenarios 1, 3, 4; design.md §4.1 (Twilio SMS row); TR-015.

---

## Acceptance Criteria Addressed

| US-064 AC | Requirement |
|---|---|
| **Scenario 1** | SMS sent via Twilio within 30 s; `notification.status=SENT`, `twilio_message_sid` stored |
| **Scenario 4** | Twilio 503 → retry after 30 s; retry 2 after 60 s; retry 3 after 120 s; all fail → `FAILED` + `CARE_TEAM_ALERT` |
| **DoD opt-out** | `patient.notification_opt_out=True` → skip send, set `OPTED_OUT` status |

---

## Implementation Steps

### 1. Create `notification-service/app/core/secrets.py` — Secret Manager client

```python
"""GCP Secret Manager helper for runtime credential retrieval.

Loads Twilio and SendGrid credentials from Secret Manager on first access.
Values are cached in-process for the container lifetime.

Design refs:
    US-064 Technical Notes — Twilio credentials from Secret Manager
    ADR-007 — No credentials in environment variables or source code
"""
from __future__ import annotations

import functools
import os

from google.cloud import secretmanager


@functools.lru_cache(maxsize=None)
def get_secret(secret_id: str) -> str:
    """Retrieve the latest version of a Secret Manager secret.

    Args:
        secret_id: Secret resource name suffix, e.g. ``twilio-account-sid``.

    Returns:
        Secret payload as a UTF-8 string.
    """
    project_id = os.environ["GCP_PROJECT_ID"]
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")
```

### 2. Create `notification-service/app/dispatchers/sms.py`

```python
"""Twilio SMS dispatcher with APScheduler-based retry.

Dispatches SMS notifications via Twilio Programmable SMS using template-based
messaging. Enforces patient opt-out check and retries transient failures
3 times with a 30 s/60 s/120 s backoff schedule (US-064 DoD).

Retry schedule:
    Attempt 1 → failure → wait 30 s → Attempt 2
    Attempt 2 → failure → wait 60 s → Attempt 3
    Attempt 3 → failure → FAILED + CARE_TEAM_ALERT published

Design refs:
    US-064 DoD, AC Scenarios 1 and 4
    design.md §4.1 — Twilio Programmable SMS
    ADR-007 — Secret Manager for credentials
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from google.cloud import pubsub_v1
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client as TwilioClient

from app.core.secrets import get_secret
from app.db.session import AsyncSessionFactory
from app.models.notification import Notification, NotificationStatus
from app.schemas import NotificationRequest

logger = logging.getLogger(__name__)

# Retry backoff delays in seconds (US-064 DoD: 30 s, 60 s, 120 s)
_RETRY_DELAYS: tuple[int, ...] = (30, 60, 120)
_MAX_RETRIES: int = len(_RETRY_DELAYS)

# Transient Twilio HTTP status codes that warrant retry
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 503, 504})

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Return the shared APScheduler instance, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
        _scheduler.start()
        logger.info("apscheduler.started")
    return _scheduler


def _build_twilio_client() -> TwilioClient:
    """Construct a Twilio REST client using Secret Manager credentials."""
    account_sid = get_secret("twilio-account-sid")
    auth_token = get_secret("twilio-auth-token")
    return TwilioClient(account_sid, auth_token)


class TwilioSMSDispatcher:
    """Dispatches SMS notifications via Twilio and schedules retries.

    Usage::

        dispatcher = TwilioSMSDispatcher()
        await dispatcher.dispatch(session, notification_id, request)
    """

    def __init__(self) -> None:
        self._from_number: str = os.environ["TWILIO_FROM_NUMBER"]

    async def dispatch(
        self,
        session: AsyncSession,
        notification_id: uuid.UUID,
        request: NotificationRequest,
    ) -> None:
        """Attempt SMS dispatch. Schedule retry on transient failure.

        Checks patient opt-out before any Twilio call. On success, updates
        notification status to SENT. On transient error, schedules retry.
        On permanent error, sets FAILED immediately.

        Args:
            session: Active async DB session.
            notification_id: UUID of the `notification` row created by consumer.
            request: Validated Pub/Sub notification request.
        """
        # --- Opt-out check ---
        opted_out = await self._check_opt_out(session, request)
        if opted_out and not request.urgency_override:
            await self._set_status(
                session, notification_id, NotificationStatus.OPTED_OUT
            )
            logger.info(
                "sms_dispatcher.opted_out",
                extra={
                    "notification_id": str(notification_id),
                    "idempotency_key": request.idempotency_key,
                },
            )
            return

        await self._attempt_send(session, notification_id, request, attempt=1)

    async def _attempt_send(
        self,
        session: AsyncSession,
        notification_id: uuid.UUID,
        request: NotificationRequest,
        attempt: int,
    ) -> None:
        """Single Twilio send attempt. Schedules retry on transient error.

        Args:
            session: Active async DB session.
            notification_id: UUID of the notification row.
            request: Validated notification request.
            attempt: Current attempt number (1-indexed).
        """
        client = _build_twilio_client()
        try:
            message = client.messages.create(
                to=request.phone,
                from_=self._from_number,
                body=self._render_template(request.template, request.substitutions),
            )
            # Success — update status and store SID
            await session.execute(
                update(Notification)
                .where(Notification.id == notification_id)
                .values(
                    status=NotificationStatus.SENT,
                    twilio_message_sid=message.sid,
                    sent_at=datetime.now(timezone.utc),
                    retry_count=attempt - 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            logger.info(
                "sms_dispatcher.sent",
                extra={
                    "notification_id": str(notification_id),
                    "twilio_sid": message.sid,
                    "attempt": attempt,
                },
            )

        except TwilioRestException as exc:
            is_retryable = exc.status in _RETRYABLE_STATUS_CODES
            logger.warning(
                "sms_dispatcher.twilio_error",
                extra={
                    "notification_id": str(notification_id),
                    "status": exc.status,
                    "attempt": attempt,
                    "retryable": is_retryable,
                },
            )

            if is_retryable and attempt <= _MAX_RETRIES:
                delay_seconds = _RETRY_DELAYS[attempt - 1]
                await self._set_retry_count(session, notification_id, attempt)
                self._schedule_retry(notification_id, request, attempt + 1, delay_seconds)
                logger.info(
                    "sms_dispatcher.retry_scheduled",
                    extra={
                        "notification_id": str(notification_id),
                        "next_attempt": attempt + 1,
                        "delay_seconds": delay_seconds,
                    },
                )
            else:
                # Permanent failure or retries exhausted
                await self._handle_final_failure(
                    session, notification_id, request, str(exc)
                )

    def _schedule_retry(
        self,
        notification_id: uuid.UUID,
        request: NotificationRequest,
        next_attempt: int,
        delay_seconds: int,
    ) -> None:
        """Schedule a retry send via APScheduler after `delay_seconds`.

        Args:
            notification_id: UUID of the notification row.
            request: Validated notification request.
            next_attempt: Attempt number for the scheduled retry.
            delay_seconds: Seconds to wait before the next attempt.
        """
        scheduler = get_scheduler()
        job_id = f"sms_retry_{notification_id}_{next_attempt}"
        scheduler.add_job(
            self._retry_job,
            trigger="interval",
            seconds=delay_seconds,
            id=job_id,
            max_instances=1,
            replace_existing=True,
            kwargs={
                "notification_id": notification_id,
                "request": request,
                "attempt": next_attempt,
                "job_id": job_id,
            },
        )

    async def _retry_job(
        self,
        notification_id: uuid.UUID,
        request: NotificationRequest,
        attempt: int,
        job_id: str,
    ) -> None:
        """APScheduler job: remove self and run send attempt.

        Args:
            notification_id: UUID of the notification row.
            request: Validated notification request.
            attempt: This attempt's number (2 or 3).
            job_id: APScheduler job ID for self-removal.
        """
        scheduler = get_scheduler()
        scheduler.remove_job(job_id)
        async with AsyncSessionFactory() as session:
            await self._attempt_send(session, notification_id, request, attempt)

    async def _handle_final_failure(
        self,
        session: AsyncSession,
        notification_id: uuid.UUID,
        request: NotificationRequest,
        error_message: str,
    ) -> None:
        """Set notification to FAILED and publish CARE_TEAM_ALERT.

        Called when all 3 retry attempts are exhausted (AC Scenario 4).

        Args:
            session: Active async DB session.
            notification_id: UUID of the notification row.
            request: Validated notification request.
            error_message: Last error message from Twilio.
        """
        await session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(
                status=NotificationStatus.FAILED,
                last_error=error_message[:1000],
                retry_count=_MAX_RETRIES,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

        await self._publish_care_team_alert(notification_id, request, error_message)
        logger.error(
            "sms_dispatcher.final_failure",
            extra={
                "notification_id": str(notification_id),
                "idempotency_key": request.idempotency_key,
                "error": error_message,
            },
        )

    async def _publish_care_team_alert(
        self,
        notification_id: uuid.UUID,
        request: NotificationRequest,
        error_message: str,
    ) -> None:
        """Publish a CARE_TEAM_ALERT to the notification-requests topic.

        Allows the care team to follow up manually on failed critical alerts
        (US-064 AC Scenario 4).

        Args:
            notification_id: UUID of the failed notification.
            request: Original notification request.
            error_message: Error from Twilio after all retries.
        """
        import json

        project_id = os.environ["GCP_PROJECT_ID"]
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, "care-team-alerts")
        alert_payload = json.dumps(
            {
                "alert_type": "CARE_TEAM_ALERT",
                "failed_notification_id": str(notification_id),
                "idempotency_key": request.idempotency_key,
                "template": request.template,
                "recipient_id": request.recipient_id,
                "error": error_message,
            }
        ).encode("utf-8")
        publisher.publish(topic_path, alert_payload)

    @staticmethod
    def _render_template(template: str, substitutions: dict[str, Any]) -> str:
        """Render a simple template string with substitution values.

        For Twilio Content API templates, this constructs the message body
        or passes the template SID. Kept simple: format substitution dict
        into a string for Twilio Basic SMS; upgrade to Content API as needed.

        Args:
            template: Template name or Twilio Content SID.
            substitutions: Key-value substitution map.

        Returns:
            Rendered message body string.
        """
        # Basic implementation — replace with Twilio Content API integration
        # if template SID starts with HX (Twilio Content SID format)
        body = template
        for key, value in substitutions.items():
            body = body.replace(f"{{{{{key}}}}}", str(value))
        return body

    @staticmethod
    async def _check_opt_out(
        session: AsyncSession, request: NotificationRequest
    ) -> bool:
        """Check if the patient has opted out of non-urgent notifications.

        Args:
            session: Active async DB session.
            request: Validated notification request.

        Returns:
            True if the patient has notification_opt_out=True; False otherwise
            (including when recipient_id is None).
        """
        if not request.recipient_id:
            return False

        from sqlalchemy import text as sa_text

        result = await session.execute(
            sa_text(
                "SELECT notification_opt_out FROM patient WHERE id = :patient_id"
            ),
            {"patient_id": request.recipient_id},
        )
        row = result.fetchone()
        return bool(row and row.notification_opt_out)

    @staticmethod
    async def _set_status(
        session: AsyncSession,
        notification_id: uuid.UUID,
        status: NotificationStatus,
    ) -> None:
        await session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(status=status, updated_at=datetime.now(timezone.utc))
        )
        await session.commit()

    @staticmethod
    async def _set_retry_count(
        session: AsyncSession, notification_id: uuid.UUID, attempt: int
    ) -> None:
        await session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(retry_count=attempt, updated_at=datetime.now(timezone.utc))
        )
        await session.commit()
```

### 3. Create `notification-service/requirements.txt`

```
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
twilio>=9.0.0
sendgrid>=6.11.0
apscheduler>=3.10.4
google-cloud-pubsub>=2.21.0
google-cloud-secret-manager>=2.20.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.29.0
alembic>=1.13.0
pydantic[email]>=2.7.0
```

---

## Validation

```bash
# Unit test dry run (see TASK-005 for full test suite)
cd notification-service
python -c "
from app.dispatchers.sms import TwilioSMSDispatcher, _RETRY_DELAYS, _MAX_RETRIES
assert _MAX_RETRIES == 3
assert _RETRY_DELAYS == (30, 60, 120)
print('Retry config OK')
"

# Verify APScheduler initialises without error
python -c "
from app.dispatchers.sms import get_scheduler
s = get_scheduler()
assert s.running
print('Scheduler started OK')
"
```

---

## Files Touched

| File | Action |
|------|--------|
| `notification-service/app/core/secrets.py` | Create |
| `notification-service/app/dispatchers/__init__.py` | Create |
| `notification-service/app/dispatchers/sms.py` | Create |
| `notification-service/requirements.txt` | Create |

---

## Definition of Done Checklist

- [ ] `TwilioSMSDispatcher.dispatch()` calls `client.messages.create()` with `to`, `from_`, `body`
- [ ] Twilio credentials loaded from Secret Manager (`twilio-account-sid`, `twilio-auth-token`)
- [ ] Opt-out check: `patient.notification_opt_out=True` → `status=OPTED_OUT`, no Twilio call
- [ ] HTTP 503 from Twilio → APScheduler retry at +30 s, +60 s, +120 s
- [ ] After 3 failures → `status=FAILED`, `CARE_TEAM_ALERT` published to `care-team-alerts` topic
- [ ] `notification.twilio_message_sid` and `sent_at` set on success
- [ ] `retry_count` incremented on each attempt
- [ ] APScheduler `get_scheduler()` returns a running `AsyncIOScheduler`

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `Notification` ORM model with `status`, `twilio_message_sid`, `retry_count` columns |
| TASK-002 | Task | Consumer calls `TwilioSMSDispatcher.dispatch()` |
| US-006 | Story | `patient.notification_opt_out` column must exist |
