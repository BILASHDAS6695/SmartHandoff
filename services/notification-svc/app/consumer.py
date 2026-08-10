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

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from google.cloud import pubsub_v1
from pydantic import ValidationError
import sqlalchemy as sa
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
    # Run blocking acknowledge() in thread pool
    await asyncio.to_thread(
        subscriber.acknowledge,
        request=pubsub_v1.types.AcknowledgeRequest(
            subscription=subscription_path, ack_ids=[ack_id]
        ),
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
    now = datetime.now(timezone.utc)
    result = await session.execute(
        sa.text(
            """
            INSERT INTO notification (
                id, idempotency_key, type, recipient_id, phone_or_email,
                template, substitutions, delivery_status, retry_count, urgency_override, created_at, updated_at
            ) VALUES (
                :id, :idempotency_key, :type, :recipient_id, :phone_or_email,
                :template, :substitutions, 'PENDING', 0, :urgency_override, :created_at, :updated_at
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
            "urgency_override": request.urgency_override,
            "created_at": now,
            "updated_at": now,
        },
    )
    await session.commit()
    return result.rowcount


async def run_consumer(project_id: str, subscription_id: str) -> None:
    """Start the Pub/Sub pull loop for notification-requests.

    Pulls up to 10 messages per batch, processes each, and ACKs/NACKs
    based on processing outcome. Runs indefinitely until cancelled.
    
    Uses asyncio.to_thread() to run blocking subscriber.pull() calls
    in a thread pool to avoid blocking the event loop.

    Args:
        project_id: GCP project ID.
        subscription_id: Pub/Sub subscription ID (e.g. ``notification-service-sub``).
    """
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(project_id, subscription_id)
    logger.info("notification_consumer.started", extra={"subscription": subscription_path})

    while True:
        # Run blocking pull() in thread pool to avoid blocking event loop
        response = await asyncio.to_thread(
            subscriber.pull,
            request=pubsub_v1.types.PullRequest(
                subscription=subscription_path,
                max_messages=10,
            ),
            timeout=30,
        )

        for received_message in response.received_messages:
            # message.data is already decoded bytes from the Pub/Sub client
            data = received_message.message.data
            try:
                await _process_message(
                    message_data=data,
                    ack_id=received_message.ack_id,
                    subscriber=subscriber,
                    subscription_path=subscription_path,
                )
            except Exception as exc:
                logger.exception(
                    "notification_consumer.unexpected_error",
                    extra={"error": str(exc)},
                )
                # ACK the message to avoid infinite redelivery loops.
                # Permanent failures (e.g. FK violation) should not block the consumer.
                await asyncio.to_thread(
                    subscriber.acknowledge,
                    request=pubsub_v1.types.AcknowledgeRequest(
                        subscription=subscription_path, ack_ids=[received_message.ack_id]
                    ),
                )
