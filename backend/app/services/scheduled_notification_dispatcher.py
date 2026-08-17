"""Dispatcher for pending ScheduledNotification records.

Polls the `scheduled_notification` table for rows where:
    - delivery_status = 'PENDING'
    - send_at <= NOW() (UTC)
    - deleted_at IS NULL

For each due notification the dispatcher:
    1. Loads the associated Patient (phone/email are decrypted by the ORM).
    2. Skips/opt-out if the patient has `notification_opt_out = True`.
    3. Resolves the delivery channel from `ScheduledNotification.channel`.
    4. Publishes the notification via `PatientNotificationPublisher`.
    5. Updates `delivery_status` to SENT, OPTED_OUT, or FAILED.

This dispatcher is intentionally decoupled from transport details; the actual
SMS/EMAIL delivery is handled by the notification service that consumes the
`notification-requests` Pub/Sub topic.

Design refs:
    US-041 / US-067 — scheduled patient notifications and opt-out
    ADR-001         — idempotency via ScheduledNotification.idempotency_key
    ADR-007         — PHI minimization; phone/email resolved at dispatch time
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.patient import Patient
from app.models.scheduled_notification import (
    DeliveryStatus,
    NotificationChannel,
    ScheduledNotification,
)
from app.services.patient_notification_publisher import PatientNotificationPublisher

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# How often the dispatcher polls for due notifications.
DEFAULT_POLL_INTERVAL_MINUTES: int = 1

# Maximum rows processed per tick.
DEFAULT_BATCH_SIZE: int = 100


class ScheduledNotificationDispatcher:
    """Polls and dispatches pending scheduled notifications.

    Args:
        session_factory: Async SQLAlchemy session factory (primary DB).
        publisher: PatientNotificationPublisher instance.
        scheduler: Shared APScheduler instance.
        poll_interval_minutes: Interval between polling ticks.
        batch_size: Maximum notifications to process per tick.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publisher: PatientNotificationPublisher,
        scheduler: AsyncIOScheduler,
        poll_interval_minutes: int = DEFAULT_POLL_INTERVAL_MINUTES,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._scheduler = scheduler
        self._poll_interval_minutes = poll_interval_minutes
        self._batch_size = batch_size

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self) -> None:
        """Register the dispatcher as an APScheduler interval job.

        Idempotent — safe to call multiple times (APScheduler deduplicates by job_id).
        """
        self._scheduler.add_job(
            self.run,
            trigger="interval",
            minutes=self._poll_interval_minutes,
            id="scheduled_notification_dispatcher",
            replace_existing=True,
            misfire_grace_time=30,
        )
        logger.info(
            "ScheduledNotificationDispatcher registered: interval=%d minutes, batch_size=%d",
            self._poll_interval_minutes,
            self._batch_size,
        )

    async def run(self) -> None:
        """Execute a single dispatch cycle.

        Exceptions for individual notifications are caught and logged; a single
        failure must not abort the batch or crash the scheduler.
        """
        now = datetime.now(timezone.utc)
        try:
            notifications = await self._fetch_due_notifications(now)
        except Exception as exc:
            logger.error(
                "scheduled_notification_dispatcher.fetch_failed",
                extra={"now": now.isoformat(), "error": str(exc)},
                exc_info=True,
            )
            return

        if not notifications:
            logger.debug("scheduled_notification_dispatcher.no_due_notifications")
            return

        logger.info(
            "scheduled_notification_dispatcher.due_notifications_found",
            extra={"count": len(notifications), "now": now.isoformat()},
        )

        for notification in notifications:
            try:
                await self._dispatch_one(notification)
            except Exception as exc:
                # Defensive catch-all; _dispatch_one already handles its own errors.
                logger.error(
                    "scheduled_notification_dispatcher.unexpected_error",
                    extra={
                        "notification_id": str(notification.id),
                        "error": str(exc),
                    },
                    exc_info=True,
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_due_notifications(
        self, now: datetime
    ) -> list[ScheduledNotification]:
        """Return pending notifications due for dispatch.

        Patient is eagerly loaded so phone/email can be resolved without N+1.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(ScheduledNotification)
                .options(joinedload(ScheduledNotification.patient))
                .where(
                    ScheduledNotification.delivery_status == DeliveryStatus.PENDING,
                    ScheduledNotification.send_at <= now,
                    ScheduledNotification.deleted_at.is_(None),
                )
                .order_by(ScheduledNotification.send_at.asc())
                .limit(self._batch_size)
            )
            return list(result.scalars().all())

    async def _dispatch_one(self, notification: ScheduledNotification) -> None:
        """Dispatch a single notification and persist its final status."""
        async with self._session_factory() as session:
            # Merge the detached notification into this session so we can update it.
            notification = await session.merge(notification)

            patient = notification.patient
            if patient is None:
                logger.error(
                    "scheduled_notification_dispatcher.patient_not_found",
                    extra={
                        "notification_id": str(notification.id),
                        "patient_id": str(notification.patient_id),
                    },
                )
                notification.delivery_status = DeliveryStatus.FAILED
                await session.commit()
                return

            # US-067: respect patient opt-out for non-urgent scheduled notifications.
            if patient.notification_opt_out:
                notification.delivery_status = DeliveryStatus.OPTED_OUT
                await session.commit()
                logger.info(
                    "scheduled_notification_dispatcher.opted_out",
                    extra={
                        "notification_id": str(notification.id),
                        "patient_id": str(patient.id),
                    },
                )
                return

            try:
                await self._publish(notification, patient)
                notification.delivery_status = DeliveryStatus.SENT
                await session.commit()
                logger.info(
                    "scheduled_notification_dispatcher.sent",
                    extra={
                        "notification_id": str(notification.id),
                        "patient_id": str(patient.id),
                        "channel": notification.channel.value,
                        "type": notification.type.value,
                    },
                )
            except Exception as exc:
                notification.delivery_status = DeliveryStatus.FAILED
                await session.commit()
                logger.error(
                    "scheduled_notification_dispatcher.publish_failed",
                    extra={
                        "notification_id": str(notification.id),
                        "patient_id": str(patient.id),
                        "channel": notification.channel.value,
                        "type": notification.type.value,
                        "error": str(exc),
                    },
                    exc_info=True,
                )

    async def _publish(
        self, notification: ScheduledNotification, patient: Patient
    ) -> None:
        """Publish the notification via PatientNotificationPublisher.

        Raises:
            ValueError: If the patient lacks the required contact info.
        """
        subject, body = _render_message(notification, patient)

        if notification.channel == NotificationChannel.SMS:
            phone = patient.phone
            if not phone:
                raise ValueError("Patient has no phone number for SMS dispatch")
            await self._publisher.send_sms(
                phone=phone,
                body=body,
                patient_id=str(patient.id),
                priority="NORMAL",
                urgency_override=False,
            )
        elif notification.channel == NotificationChannel.EMAIL:
            email = patient.email
            if not email:
                raise ValueError("Patient has no email address for EMAIL dispatch")
            await self._publisher.send_email(
                email=email,
                subject=subject,
                body=body,
                patient_id=str(patient.id),
                priority="NORMAL",
                urgency_override=False,
            )
        else:
            raise ValueError(f"Unsupported notification channel: {notification.channel}")


def _render_message(
    notification: ScheduledNotification, patient: Patient
) -> tuple[str, str]:
    """Return (subject, body) for a scheduled notification.

    Placeholder logic — replace with template rendering (e.g. Jinja) when ready.
    """
    first_name = patient.first_name or "there"

    if notification.type.value == "CHECK_IN_48H":
        subject = "48-Hour Post-Discharge Check-In"
        body = (
            f"Hi {first_name}, this is your 48-hour follow-up check-in after discharge. "
            "Please reply with any symptoms, questions, or concerns."
        )
    elif notification.type.value == "MEDICATION_REMINDER":
        subject = "Medication Reminder"
        body = (
            f"Hi {first_name}, remember to take your prescribed medications as directed. "
            "Reply if you need help or have questions."
        )
    else:
        subject = "SmartHandoff Notification"
        body = f"Hi {first_name}, you have a new notification from SmartHandoff."

    return subject, body
