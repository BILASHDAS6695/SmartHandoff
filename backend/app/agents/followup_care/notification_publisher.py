"""Pub/Sub publisher for care manager alert notifications.

Publishes `CARE_MANAGER_ALERT` messages to the `notification-requests` Pub/Sub topic
after an appointment is created for a HIGH-risk patient.

Publish pattern: publish-after-commit — the Pub/Sub message is published only after
the DB transaction commits to avoid sending alerts for rolled-back appointments.

Idempotency: the `idempotency_key` field in the payload prevents the Notification
Service from sending duplicate SMS/email if this message is redelivered (AIR-040).

Design refs:
    design.md §7.5 AIR-040 — notification-requests topic; idempotency key
    US-040 AC Scenario 1 — CARE_MANAGER_ALERT payload specification
    ADR-001 — Pub/Sub topic per logical channel (notification-requests)
"""
from __future__ import annotations

import asyncio
import json
import logging

from google.cloud import pubsub_v1

from app.agents.followup_care.schemas import CareManagerAlertPayload

logger = logging.getLogger(__name__)


class NotificationPublisher:
    """Thin wrapper around google-cloud-pubsub for alert dispatch.

    Args:
        project_id:          GCP project ID (from environment / Secret Manager).
        topic_id:            Pub/Sub topic name (default: notification-requests).
        publisher_client:    Optional pre-built PublisherClient for testing injection.
    """

    def __init__(
        self,
        project_id: str,
        topic_id: str = "notification-requests",
        publisher_client: pubsub_v1.PublisherClient | None = None,
    ) -> None:
        self._topic_path = f"projects/{project_id}/topics/{topic_id}"
        self._client = publisher_client or pubsub_v1.PublisherClient()

    async def publish_care_manager_alert(self, payload: CareManagerAlertPayload) -> str:
        """Publish a CARE_MANAGER_ALERT to the notification-requests topic.

        Args:
            payload: Validated CareManagerAlertPayload Pydantic model.

        Returns:
            Pub/Sub message ID (string) returned by the broker.

        Raises:
            google.api_core.exceptions.GoogleAPIError: On Pub/Sub publish failure.
                Caller (FollowUpCareAgent.process) is responsible for retry/nack.
        """
        data = payload.model_dump_json().encode("utf-8")
        future = self._client.publish(
            self._topic_path,
            data=data,
            idempotency_key=payload.idempotency_key,
        )
        message_id: str = await asyncio.to_thread(future.result, timeout=10)

        logger.info(
            "CARE_MANAGER_ALERT published",
            extra={
                "encounter_id": payload.encounter_id,
                "risk_tier": payload.risk_tier,
                "appointment_id": payload.appointment_id,
                "pubsub_message_id": message_id,
            },
        )
        return message_id
