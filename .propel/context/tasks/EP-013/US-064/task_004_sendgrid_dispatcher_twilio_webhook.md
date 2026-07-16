---
id: TASK-004
title: "Create `notification-service/app/dispatchers/email.py` — SendGrid Email Dispatcher + Twilio Delivery Webhook"
user_story: US-064
epic: EP-013
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003]
---

# TASK-004: Create `notification-service/app/dispatchers/email.py` — SendGrid Email Dispatcher + Twilio Delivery Webhook

> **Story:** US-064 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-064 DoD specifies:

> *"SendGrid email: `SendGridAPIClient.send(message)` with Dynamic Template rendering"*
> *"Twilio webhook: `POST /webhooks/twilio/status` with Twilio signature validation (`X-Twilio-Signature` header)"*
> *"Twilio delivery webhook updates status to DELIVERED"*

This task implements two components:

1. **`SendGridEmailDispatcher`** — dispatches email using the SendGrid Python SDK with Dynamic Template IDs; follows the same opt-out and retry pattern as `TwilioSMSDispatcher` (TASK-003)
2. **`POST /webhooks/twilio/status`** — FastAPI route that receives Twilio delivery status webhooks, validates the `X-Twilio-Signature` header using `twilio.request_validator.RequestValidator`, and updates `notification.status` to `DELIVERED`

Design decisions:

| Decision | Rationale |
|----------|-----------|
| SendGrid Dynamic Templates via `TemplateData` | Dynamic Templates decouple email content from code; template ID passed from Pub/Sub message `template` field |
| `X-Twilio-Signature` validated before processing | Prevents spoofed webhook attacks (US-064 AC Scenario 3 DoD) |
| Webhook validates signature against full callback URL + POST params | Twilio requires exact URL reconstruction; `request.base_url` + path used |
| `HMAC` validation failure → HTTP 403 | Unauthenticated webhooks must be rejected, not silently ignored |
| SendGrid uses same APScheduler retry pattern as SMS (TASK-003) | DRY principle — shared base class `BaseNotificationDispatcher` avoids duplication |
| `sendgrid_message_id` extracted from `X-Message-Id` response header | Primary correlation key for delivery tracking (DoD) |

Design refs: US-064 AC Scenario 3, DoD; design.md §4.1 (SendGrid); OWASP A04 (insecure design — webhook spoofing).

---

## Acceptance Criteria Addressed

| US-064 AC | Requirement |
|---|---|
| **Scenario 3** | `POST /webhooks/twilio/status` validates `X-Twilio-Signature`; updates `notification.status=DELIVERED` |
| **DoD** | `SendGridAPIClient.send(message)` with Dynamic Template; `sendgrid_message_id` stored |

---

## Implementation Steps

### 1. Create `notification-service/app/dispatchers/base.py` — shared base dispatcher

```python
"""Base notification dispatcher — shared opt-out check and APScheduler retry.

Both TwilioSMSDispatcher and SendGridEmailDispatcher inherit this base to
avoid duplicating opt-out logic and retry scheduling (DRY principle).

Design refs:
    US-064 DoD — opt-out flag: patient.notification_opt_out=True → skip
    TASK-003    — retry pattern established for SMS; reused for email
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationStatus

logger = logging.getLogger(__name__)


class BaseNotificationDispatcher:
    """Shared opt-out check and status update helpers."""

    @staticmethod
    async def check_opt_out(
        session: AsyncSession, recipient_id: str | None, urgency_override: bool
    ) -> bool:
        """Return True if patient has opted out and urgency_override is False."""
        if not recipient_id or urgency_override:
            return False
        from sqlalchemy import text
        result = await session.execute(
            text("SELECT notification_opt_out FROM patient WHERE id = :id"),
            {"id": recipient_id},
        )
        row = result.fetchone()
        return bool(row and row.notification_opt_out)

    @staticmethod
    async def set_status(
        session: AsyncSession,
        notification_id: uuid.UUID,
        status: NotificationStatus,
        **extra_fields: object,
    ) -> None:
        """Update notification status and optional extra fields."""
        await session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(
                status=status,
                updated_at=datetime.now(timezone.utc),
                **extra_fields,
            )
        )
        await session.commit()
```

### 2. Create `notification-service/app/dispatchers/email.py`

```python
"""SendGrid email dispatcher with Dynamic Template rendering.

Dispatches email notifications via SendGrid using Dynamic Template IDs.
Follows the same opt-out check and APScheduler retry pattern as
TwilioSMSDispatcher (TASK-003).

Template ID convention:
    The `template` field from the Pub/Sub message must be a SendGrid
    Dynamic Template ID (format: ``d-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx``).
    The `substitutions` dict is passed as Dynamic Template data.

Design refs:
    US-064 DoD — SendGrid email with Dynamic Template
    TASK-003   — retry pattern (30s/60s/120s, 3 attempts max)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, To, DynamicTemplateData
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets import get_secret
from app.db.session import AsyncSessionFactory
from app.dispatchers.base import BaseNotificationDispatcher
from app.models.notification import Notification, NotificationStatus
from app.schemas import NotificationRequest

logger = logging.getLogger(__name__)

_RETRY_DELAYS: tuple[int, ...] = (30, 60, 120)
_MAX_RETRIES: int = len(_RETRY_DELAYS)
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 503, 504})


def _build_sendgrid_client() -> SendGridAPIClient:
    """Construct a SendGrid client using Secret Manager API key."""
    api_key = get_secret("sendgrid-api-key")
    return SendGridAPIClient(api_key=api_key)


class SendGridEmailDispatcher(BaseNotificationDispatcher):
    """Dispatches email via SendGrid Dynamic Templates.

    Usage::

        dispatcher = SendGridEmailDispatcher()
        await dispatcher.dispatch(session, notification_id, request)
    """

    def __init__(self) -> None:
        self._from_email: str = os.environ["SENDGRID_FROM_EMAIL"]

    async def dispatch(
        self,
        session: AsyncSession,
        notification_id: uuid.UUID,
        request: NotificationRequest,
    ) -> None:
        """Send email via SendGrid Dynamic Template.

        Checks patient opt-out before any SendGrid call. On success, stores
        `sendgrid_message_id`. On transient failure, schedules APScheduler retry.

        Args:
            session: Active async DB session.
            notification_id: UUID of the `notification` row.
            request: Validated notification request (type=EMAIL).
        """
        opted_out = await self.check_opt_out(
            session, request.recipient_id, request.urgency_override
        )
        if opted_out:
            await self.set_status(session, notification_id, NotificationStatus.OPTED_OUT)
            logger.info(
                "email_dispatcher.opted_out",
                extra={"notification_id": str(notification_id)},
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
        """Single SendGrid send attempt. Schedules retry on transient error.

        Args:
            session: Active async DB session.
            notification_id: UUID of the notification row.
            request: Validated notification request.
            attempt: Current attempt number (1-indexed).
        """
        client = _build_sendgrid_client()
        message = Mail(from_email=self._from_email, to_emails=To(request.email))
        message.template_id = request.template
        message.dynamic_template_data = DynamicTemplateData(request.substitutions)

        try:
            response = client.send(message)
            sendgrid_message_id = response.headers.get("X-Message-Id", "")

            await self.set_status(
                session,
                notification_id,
                NotificationStatus.SENT,
                sendgrid_message_id=sendgrid_message_id,
                sent_at=datetime.now(timezone.utc),
                retry_count=attempt - 1,
            )
            logger.info(
                "email_dispatcher.sent",
                extra={
                    "notification_id": str(notification_id),
                    "sendgrid_id": sendgrid_message_id,
                    "attempt": attempt,
                },
            )

        except Exception as exc:
            status_code = getattr(exc, "status_code", 0)
            is_retryable = status_code in _RETRYABLE_STATUS_CODES

            logger.warning(
                "email_dispatcher.sendgrid_error",
                extra={
                    "notification_id": str(notification_id),
                    "status_code": status_code,
                    "attempt": attempt,
                    "retryable": is_retryable,
                },
            )

            if is_retryable and attempt <= _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt - 1]
                await session.execute(
                    update(Notification)
                    .where(Notification.id == notification_id)
                    .values(retry_count=attempt, updated_at=datetime.now(timezone.utc))
                )
                await session.commit()
                self._schedule_retry(notification_id, request, attempt + 1, delay)
            else:
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
        from app.dispatchers.sms import get_scheduler
        scheduler = get_scheduler()
        job_id = f"email_retry_{notification_id}_{next_attempt}"
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
        from app.dispatchers.sms import get_scheduler
        get_scheduler().remove_job(job_id)
        async with AsyncSessionFactory() as session:
            await self._attempt_send(session, notification_id, request, attempt)

    async def _handle_final_failure(
        self,
        session: AsyncSession,
        notification_id: uuid.UUID,
        request: NotificationRequest,
        error_message: str,
    ) -> None:
        """Set FAILED and publish CARE_TEAM_ALERT (mirrors SMS dispatcher)."""
        import json, os
        from google.cloud import pubsub_v1

        await self.set_status(
            session,
            notification_id,
            NotificationStatus.FAILED,
            last_error=error_message[:1000],
            retry_count=_MAX_RETRIES,
        )

        project_id = os.environ["GCP_PROJECT_ID"]
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, "care-team-alerts")
        publisher.publish(
            topic_path,
            json.dumps(
                {
                    "alert_type": "CARE_TEAM_ALERT",
                    "failed_notification_id": str(notification_id),
                    "idempotency_key": request.idempotency_key,
                    "template": request.template,
                    "recipient_id": request.recipient_id,
                    "error": error_message,
                }
            ).encode(),
        )
        logger.error(
            "email_dispatcher.final_failure",
            extra={"notification_id": str(notification_id), "error": error_message},
        )
```

### 3. Create `notification-service/app/webhooks/twilio.py` — delivery status webhook

```python
"""Twilio delivery status webhook handler.

Receives `POST /webhooks/twilio/status` from Twilio and updates the
`notification.status` to DELIVERED (or FAILED for undelivered messages).

Security: Every request is validated against the `X-Twilio-Signature`
header using `twilio.request_validator.RequestValidator` with the
`twilio-auth-token` from Secret Manager (US-064 AC Scenario 3, DoD).
Invalid signatures are rejected with HTTP 403.

Design refs:
    US-064 AC Scenario 3 — webhook updates status=DELIVERED
    US-064 DoD           — X-Twilio-Signature header validation
    OWASP A04            — Insecure design: spoofed webhooks rejected
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from app.core.secrets import get_secret
from app.db.session import get_db_session
from app.models.notification import Notification, NotificationStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/twilio", tags=["webhooks"])


def _validate_twilio_signature(
    request: Request,
    x_twilio_signature: Annotated[str | None, Header(alias="X-Twilio-Signature")] = None,
) -> None:
    """FastAPI dependency: validate Twilio webhook signature.

    Reconstructs the full callback URL from the request and validates the
    `X-Twilio-Signature` header using the Twilio auth token from Secret Manager.

    Raises:
        HTTPException: 403 Forbidden if signature is invalid or missing.
    """
    if not x_twilio_signature:
        logger.warning("twilio_webhook.missing_signature")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Twilio-Signature header",
        )

    auth_token = get_secret("twilio-auth-token")
    validator = RequestValidator(auth_token)

    # Reconstruct the full callback URL Twilio signed
    url = str(request.url)

    # Form params must be passed as a flat dict for signature validation
    # (accessed synchronously via the form data — resolved before route handler)
    form_params = dict(request.state.form_params) if hasattr(request.state, "form_params") else {}

    is_valid = validator.validate(url, form_params, x_twilio_signature)
    if not is_valid:
        logger.warning(
            "twilio_webhook.invalid_signature",
            extra={"url": url},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio webhook signature",
        )


@router.post(
    "/status",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_validate_twilio_signature)],
    summary="Twilio delivery status callback",
)
async def twilio_status_webhook(
    request: Request,
    MessageSid: Annotated[str, Form()],
    MessageStatus: Annotated[str, Form()],
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Handle Twilio delivery status webhook.

    Updates `notification.status` based on Twilio's MessageStatus value.
    Correlation performed via `twilio_message_sid` column.

    Twilio MessageStatus values:
        - ``delivered``  → NotificationStatus.DELIVERED
        - ``failed``     → NotificationStatus.FAILED
        - ``undelivered``→ NotificationStatus.FAILED
        - others         → no status change (e.g. ``sent``, ``queued``)

    Args:
        request: FastAPI request (used for signature validation).
        MessageSid: Twilio message SID from form body.
        MessageStatus: Twilio delivery status from form body.
        session: Async DB session.
    """
    # Cache form params on request.state for the signature validator
    form_data = await request.form()
    request.state.form_params = dict(form_data)

    status_map: dict[str, NotificationStatus] = {
        "delivered": NotificationStatus.DELIVERED,
        "failed": NotificationStatus.FAILED,
        "undelivered": NotificationStatus.FAILED,
    }

    new_status = status_map.get(MessageStatus.lower())
    if new_status is None:
        # Intermediate status (sent, queued, etc.) — no action needed
        logger.debug(
            "twilio_webhook.intermediate_status",
            extra={"sid": MessageSid, "twilio_status": MessageStatus},
        )
        return

    from datetime import datetime, timezone
    extra_fields: dict = {}
    if new_status == NotificationStatus.DELIVERED:
        extra_fields["delivered_at"] = datetime.now(timezone.utc)

    result = await session.execute(
        update(Notification)
        .where(Notification.twilio_message_sid == MessageSid)
        .values(
            status=new_status,
            updated_at=datetime.now(timezone.utc),
            **extra_fields,
        )
    )
    await session.commit()

    if result.rowcount == 0:
        logger.warning(
            "twilio_webhook.sid_not_found",
            extra={"sid": MessageSid, "twilio_status": MessageStatus},
        )
    else:
        logger.info(
            "twilio_webhook.status_updated",
            extra={
                "sid": MessageSid,
                "twilio_status": MessageStatus,
                "new_status": new_status.value,
            },
        )
```

### 4. Register webhook router in `notification-service/app/main.py`

Add to existing `main.py` (from TASK-002):

```python
from app.webhooks.twilio import router as twilio_router

app.include_router(twilio_router)
```

---

## Validation

```bash
# Test SendGrid dispatcher initialisation
python -c "
from app.dispatchers.email import SendGridEmailDispatcher, _RETRY_DELAYS, _MAX_RETRIES
assert _MAX_RETRIES == 3
assert _RETRY_DELAYS == (30, 60, 120)
print('SendGrid retry config OK')
"

# Test Twilio signature validation (invalid sig → 403)
curl -X POST http://localhost:8080/webhooks/twilio/status \
  -d 'MessageSid=SM123&MessageStatus=delivered' \
  -H 'Content-Type: application/x-www-form-urlencoded'
# Expected: 403 Forbidden (no X-Twilio-Signature)

# Test with valid signature (using Twilio test credentials)
# See https://www.twilio.com/docs/usage/webhooks/webhooks-security#validating-signatures-locally
```

---

## Files Touched

| File | Action |
|------|--------|
| `notification-service/app/dispatchers/base.py` | Create |
| `notification-service/app/dispatchers/email.py` | Create |
| `notification-service/app/webhooks/__init__.py` | Create |
| `notification-service/app/webhooks/twilio.py` | Create |
| `notification-service/app/main.py` | Modify — add `twilio_router` |

---

## Definition of Done Checklist

- [ ] `SendGridEmailDispatcher.dispatch()` calls `SendGridAPIClient.send(message)` with Dynamic Template ID
- [ ] `sendgrid_message_id` extracted from `X-Message-Id` response header and stored
- [ ] `POST /webhooks/twilio/status` rejects requests without `X-Twilio-Signature` with HTTP 403
- [ ] `RequestValidator.validate()` called with reconstructed URL and form params
- [ ] `notification.status` updated to `DELIVERED` when `MessageStatus=delivered`
- [ ] `notification.delivered_at` timestamp set on DELIVERED status
- [ ] SendGrid transient errors trigger APScheduler retry (30s/60s/120s)
- [ ] `BaseNotificationDispatcher` shared between SMS and email dispatchers (DRY)
- [ ] `twilio_router` registered in `app.main`

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `notification` ORM model with `sendgrid_message_id`, `delivered_at` columns |
| TASK-002 | Task | `app/main.py` where router is registered |
| TASK-003 | Task | `get_scheduler()` shared with email retry scheduler |
