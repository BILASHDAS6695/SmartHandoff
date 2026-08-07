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
from sqlalchemy import select, update, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client as TwilioClient

from app.core.secrets import get_secret
from app.db.session import AsyncSessionFactory
from app.dispatchers.base import BaseNotificationDispatcher
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
        self._from_number: str = os.environ.get(
            "TWILIO_FROM_NUMBER"
        ) or get_secret("twilio-phone-number")

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
                session, notification_id, NotificationStatus.OPTED_OUT, request.urgency_override
            )
            await BaseNotificationDispatcher.write_audit_log(
                action="NOTIFICATION_SUPPRESSED_OPT_OUT",
                patient_id=uuid.UUID(request.recipient_id) if request.recipient_id else None,
                encounter_id=None,
                notification_type=request.template,
                channel="SMS",
                urgency_override=request.urgency_override,
                session=session,
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
            now = datetime.now(timezone.utc)
            await session.execute(
                sa_text(
                    """UPDATE notification 
                       SET delivery_status = :status, twilio_message_sid = :sid, 
                           sent_at = :sent_at, retry_count = :retry_count, 
                           urgency_override = :urgency_override,
                           updated_at = :updated_at 
                       WHERE id = :id"""
                ),
                {
                    "status": NotificationStatus.SENT.value,
                    "sid": message.sid,
                    "sent_at": now,
                    "retry_count": attempt - 1,
                    "urgency_override": request.urgency_override,
                    "updated_at": now,
                    "id": str(notification_id),
                },
            )
            await session.commit()
            await BaseNotificationDispatcher.write_audit_log(
                action="NOTIFICATION_DISPATCHED",
                patient_id=uuid.UUID(request.recipient_id) if request.recipient_id else None,
                encounter_id=None,
                notification_type=request.template,
                channel="SMS",
                urgency_override=request.urgency_override,
                session=session,
            )
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
            sa_text(
                """UPDATE notification 
                   SET delivery_status = :status, last_error = :last_error, 
                       retry_count = :retry_count, updated_at = :updated_at 
                   WHERE id = :id"""
            ),
            {
                "status": NotificationStatus.FAILED.value,
                "last_error": error_message[:1000],
                "retry_count": _MAX_RETRIES,
                "updated_at": datetime.now(timezone.utc),
                "id": str(notification_id),
            },
        )
        await session.commit()

        await BaseNotificationDispatcher.write_audit_log(
            action="NOTIFICATION_FAILED",
            patient_id=uuid.UUID(request.recipient_id) if request.recipient_id else None,
            encounter_id=None,
            notification_type=request.template,
            channel="SMS",
            urgency_override=request.urgency_override,
            session=session,
        )

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
        urgency_override: bool = False,
    ) -> None:
        """Update notification status using raw SQL for database compatibility."""
        await session.execute(
            sa_text(
                "UPDATE notification SET delivery_status = :status, urgency_override = :urgency_override, updated_at = :updated_at WHERE id = :id"
            ),
            {
                "status": status.value,
                "urgency_override": urgency_override,
                "updated_at": datetime.now(timezone.utc),
                "id": str(notification_id),
            },
        )
        await session.commit()

    @staticmethod
    async def _set_retry_count(
        session: AsyncSession, notification_id: uuid.UUID, attempt: int
    ) -> None:
        """Update retry count using raw SQL for database compatibility."""
        await session.execute(
            sa_text(
                "UPDATE notification SET retry_count = :retry_count, updated_at = :updated_at WHERE id = :id"
            ),
            {
                "retry_count": attempt,
                "updated_at": datetime.now(timezone.utc),
                "id": str(notification_id),
            },
        )
        await session.commit()
