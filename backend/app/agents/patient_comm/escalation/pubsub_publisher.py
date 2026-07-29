"""Pub/Sub publisher for care team escalation alerts (US-045).

Publishes to the 'notification-requests' topic consumed by the
Notification Service (design.md §7.5 AIR-040).

Fire-and-forget pattern:
    Called via asyncio.create_task() from the escalation endpoint.
    Publish failures are logged as error metrics but do NOT propagate
    a 500 to the patient (US-045 Technical Notes).
"""
from __future__ import annotations

import json
import logging

from google.cloud import pubsub_v1

from backend.app.agents.patient_comm.escalation.schemas import EscalationAlertPayload
from backend.app.core.config import settings  # GCP_PROJECT_ID, NOTIFICATION_TOPIC_ID

log = logging.getLogger(__name__)


async def publish_escalation_alert(payload: EscalationAlertPayload) -> None:
    """Publish escalation alert to 'notification-requests' Pub/Sub topic.

    Uses the Pub/Sub PublisherClient. Runs as a background asyncio task
    so it does NOT block the HTTP response returned to the patient.

    Error handling:
        Pub/Sub errors are caught and logged as 'escalation_pubsub_error'
        metric — the escalation DB row has already been committed at this
        point so the record exists regardless of publish outcome.
    """
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(
        settings.GCP_PROJECT_ID,
        settings.NOTIFICATION_TOPIC_ID,  # 'notification-requests'
    )
    message_data = json.dumps(
        payload.model_dump(mode="json")
    ).encode("utf-8")

    try:
        future = publisher.publish(topic_path, data=message_data)
        future.result(timeout=10)
        log.info(
            "escalation_pubsub_published",
            extra={
                "escalation_id": payload.escalation_id,
                "encounter_id": payload.encounter_id,
                "channel": payload.channel,
            },
        )
    except Exception:
        # Log error metric; do NOT raise — fire-and-forget
        log.exception(
            "escalation_pubsub_error",
            extra={
                "escalation_id": payload.escalation_id,
                "encounter_id": payload.encounter_id,
            },
        )
