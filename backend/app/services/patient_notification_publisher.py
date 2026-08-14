"""Patient-facing SMS/email notification publisher.

Publishes directly to the notification-requests topic consumed by
services/notification-svc. The notification service decides whether to
send SMS or EMAIL based on the `type` field and handles idempotency,
opt-out checks, retries, and audit logging.

Usage:
    from app.services.patient_notification_publisher import PatientNotificationPublisher

    publisher = PatientNotificationPublisher()
    await publisher.send_sms(
        phone="+919942847052",
        patient_id="uuid",
        body="Your discharge summary is ready.",
    )
    await publisher.send_email(
        email="patient@example.com",
        patient_id="uuid",
        subject="SmartHandoff Notification",
        body="Your discharge summary is ready.",
    )

Design refs:
    US-064 DoD — notification-requests Pub/Sub topic
    ADR-001    — Pub/Sub event-driven notifications
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from google.api_core import exceptions as gapi_exceptions
from google.cloud import pubsub_v1
from google.auth import exceptions as auth_exceptions

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class PatientNotificationPublisher:
    """Publish patient-facing SMS/EMAIL notifications to notification-requests."""

    def __init__(self, project_id: str | None = None) -> None:
        self._client: pubsub_v1.PublisherClient | None = None
        self._topic_path: str | None = None
        try:
            settings = get_settings()
            self._project_id = project_id or settings.GCP_PROJECT_ID
            self._topic_id = getattr(settings, "NOTIFICATION_TOPIC_ID", "notification-requests")
            self._client = pubsub_v1.PublisherClient()
            self._topic_path = self._client.topic_path(self._project_id, self._topic_id)
        except Exception as exc:
            self._project_id = project_id or os.environ.get("GCP_PROJECT_ID", "")
            self._topic_id = "notification-requests"
            logger.warning(
                "GCP Pub/Sub unavailable; patient notifications will be logged, not published. error=%s",
                exc,
            )

    async def _publish(
        self,
        idempotency_key: str,
        notification_type: str,
        patient_id: str | None,
        template: str,
        substitutions: dict[str, Any],
        phone: str | None = None,
        email: str | None = None,
        priority: str = "NORMAL",
        urgency_override: bool = False,
    ) -> str:
        """Publish a notification message to notification-requests.

        Returns:
            Pub/Sub message ID.
        """
        payload = {
            "idempotency_key": idempotency_key,
            "type": notification_type,
            "priority": priority,
            "recipient_id": patient_id,
            "template": template,
            "substitutions": substitutions,
            "urgency_override": urgency_override,
        }
        if notification_type == "SMS":
            payload["phone"] = phone
        elif notification_type == "EMAIL":
            payload["email"] = email

        data = json.dumps(payload, default=str).encode("utf-8")

        # Local/dev fallback when GCP credentials are unavailable.
        if self._client is None or self._topic_path is None:
            logger.info(
                "patient_notification_skipped (no Pub/Sub client)",
                extra={
                    "channel": notification_type,
                    "patient_id": patient_id,
                    "idempotency_key": idempotency_key,
                    "payload": payload,
                },
            )
            return "skipped-no-gcp-credentials"

        future = self._client.publish(
            self._topic_path,
            data=data,
            idempotency_key=idempotency_key,
            channel=notification_type,
        )
        message_id: str = await asyncio.to_thread(future.result, timeout=10)
        logger.info(
            "patient_notification_published",
            extra={
                "pubsub_message_id": message_id,
                "channel": notification_type,
                "patient_id": patient_id,
                "idempotency_key": idempotency_key,
            },
        )
        return message_id

    async def send_sms(
        self,
        phone: str,
        body: str,
        patient_id: str | None = None,
        priority: str = "NORMAL",
        urgency_override: bool = False,
    ) -> str:
        """Publish an SMS notification.

        Args:
            phone: E.164 phone number, e.g. +919942847052.
            body: Plain-text message body (max ~1600 chars for Twilio).
            patient_id: Optional patient UUID for opt-out/audit correlation.
            priority: NORMAL | HIGH | LOW.
            urgency_override: True to bypass patient opt-out (use carefully).
        """
        return await self._publish(
            idempotency_key=f"sms-{patient_id or phone}-{uuid.uuid4().hex[:8]}-{datetime.now(timezone.utc).isoformat()}",
            notification_type="SMS",
            patient_id=patient_id,
            template=body,
            substitutions={},
            phone=phone,
            priority=priority,
            urgency_override=urgency_override,
        )

    async def send_email(
        self,
        email: str,
        subject: str,
        body: str,
        patient_id: str | None = None,
        priority: str = "NORMAL",
        urgency_override: bool = False,
    ) -> str:
        """Publish an email notification.

        Args:
            email: Recipient email address.
            subject: Email subject line (becomes `template` in payload).
            body: Plain-text email body (passed via substitutions.body).
            patient_id: Optional patient UUID for opt-out/audit correlation.
            priority: NORMAL | HIGH | LOW.
            urgency_override: True to bypass patient opt-out (use carefully).
        """
        return await self._publish(
            idempotency_key=f"email-{patient_id or email}-{uuid.uuid4().hex[:8]}-{datetime.now(timezone.utc).isoformat()}",
            notification_type="EMAIL",
            patient_id=patient_id,
            template=subject,
            substitutions={"body": body},
            email=email,
            priority=priority,
            urgency_override=urgency_override,
        )

    async def send_both(
        self,
        phone: str | None,
        email: str | None,
        subject: str,
        body: str,
        patient_id: str | None = None,
        priority: str = "NORMAL",
        urgency_override: bool = False,
    ) -> dict[str, str | None]:
        """Publish both SMS and email notifications for the same event.

        Returns:
            Dict with `sms_message_id` and `email_message_id`.
        """
        sms_id: str | None = None
        email_id: str | None = None
        if phone:
            sms_id = await self.send_sms(
                phone=phone,
                body=body,
                patient_id=patient_id,
                priority=priority,
                urgency_override=urgency_override,
            )
        if email:
            email_id = await self.send_email(
                email=email,
                subject=subject,
                body=body,
                patient_id=patient_id,
                priority=priority,
                urgency_override=urgency_override,
            )
        return {"sms_message_id": sms_id, "email_message_id": email_id}
