"""SendGrid email dispatcher with Dynamic Template rendering.

Dispatches email notifications via SendGrid using Dynamic Template IDs.
Follows the same opt-out check and APScheduler retry pattern as
TwilioSMSDispatcher (TASK-003).

Template ID resolution (US-066 TASK-003):
    The `template` field from the Pub/Sub message is a template name
    (e.g., "patient_portal_link"). This is resolved to a SendGrid
    Dynamic Template ID via ``app.core.sendgrid_config.get_template_id()``,
    which reads from ``config/sendgrid_templates.yaml`` (populated by
    the CI/CD upload script).

    The `substitutions` dict is validated against the corresponding
    Pydantic schema from ``TEMPLATE_SCHEMA_REGISTRY`` before sending.

Design refs:
    US-064 DoD — SendGrid email with Dynamic Template
    US-066 TASK-003 — Template ID registry
    TASK-003   — retry pattern (30s/60s/120s, 3 attempts max)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Mail, To, DynamicTemplateData
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secrets import get_secret
from app.core.sendgrid_config import TemplateConfigError, get_template_id
from app.db.session import AsyncSessionFactory
from app.dispatchers.base import BaseNotificationDispatcher
from app.models.notification import Notification, NotificationStatus
from app.schemas import NotificationRequest
from app.schemas.sendgrid_templates import TEMPLATE_SCHEMA_REGISTRY

logger = logging.getLogger(__name__)

_RETRY_DELAYS: tuple[int, ...] = (30, 60, 120)
_MAX_RETRIES: int = len(_RETRY_DELAYS)
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 503, 504})


def _build_sendgrid_client() -> SendGridAPIClient:
    """Construct a SendGrid client using Secret Manager API key."""
    api_key = get_secret("sendgrid-api-key")
    return SendGridAPIClient(api_key=api_key)


class SendGridEmailDispatcher(BaseNotificationDispatcher):
    """Dispatches email via SendGrid Dynamic Templates or plain text fallback.

    Usage::

        dispatcher = SendGridEmailDispatcher()
        await dispatcher.dispatch(session, notification_id, request)
    """

    def __init__(self) -> None:
        self._from_email: str = os.environ.get(
            "SENDGRID_FROM_EMAIL"
        ) or get_secret("sendgrid-from-email")

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
            await self.set_status(
                session, 
                notification_id, 
                NotificationStatus.OPTED_OUT,
                urgency_override=request.urgency_override
            )
            await BaseNotificationDispatcher.write_audit_log(
                action="NOTIFICATION_SUPPRESSED_OPT_OUT",
                patient_id=uuid.UUID(request.recipient_id) if request.recipient_id else None,
                encounter_id=None,
                notification_type=request.template,
                channel="EMAIL",
                urgency_override=request.urgency_override,
                session=session,
            )
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

        Resolves template name → SendGrid template ID via the registry.
        Validates substitution data against the Pydantic schema.

        Args:
            session: Active async DB session.
            notification_id: UUID of the notification row.
            request: Validated notification request (template field = name).
            attempt: Current attempt number (1-indexed).
        """
        # Resolve template name → SendGrid template ID.
        # If no dynamic template is configured, fall back to a plain text email
        # where `template` becomes the subject and substitutions["body"] (or the
        # template itself) becomes the message body.
        template_id: str | None = None
        message = Mail(from_email=self._from_email, to_emails=To(request.email))
        try:
            template_id = get_template_id(request.template)
        except TemplateConfigError as exc:
            logger.warning(
                "email_dispatcher.no_dynamic_template",
                extra={
                    "notification_id": str(notification_id),
                    "template_name": request.template,
                    "error": str(exc),
                },
            )

        client = _build_sendgrid_client()
        if template_id:
            # Validate substitutions against the Pydantic schema
            schema_class = TEMPLATE_SCHEMA_REGISTRY.get(request.template)
            if schema_class:
                try:
                    # Validate substitutions by instantiating the schema
                    validated = schema_class(
                        template_name=request.template, **request.substitutions
                    )
                    # Use validated model's dict (excludes template_name field)
                    substitutions = validated.model_dump(exclude={"template_name"})
                except Exception as exc:
                    logger.error(
                        "email_dispatcher.substitution_validation_failed",
                        extra={
                            "notification_id": str(notification_id),
                            "template_name": request.template,
                            "error": str(exc),
                        },
                    )
                    # Validation failure is non-retryable
                    await self._handle_final_failure(session, notification_id, request, str(exc))
                    return
            else:
                # No schema registered; use raw substitutions
                logger.warning(
                    "email_dispatcher.no_schema_registered",
                    extra={
                        "notification_id": str(notification_id),
                        "template_name": request.template,
                    },
                )
                substitutions = request.substitutions

            message.template_id = template_id
            message.dynamic_template_data = DynamicTemplateData(substitutions)
        else:
            subject = request.template[:200] if request.template else "SmartHandoff Notification"
            body = str(request.substitutions.get("body", request.template or ""))
            message.subject = subject
            message.add_content(Content(mime_type="text/plain", content=body))

        try:
            response = client.send(message)
            sendgrid_message_id = response.headers.get("X-Message-Id", "")

            await self.set_status(
                session,
                notification_id,
                NotificationStatus.SENT,
                urgency_override=request.urgency_override,
                sendgrid_message_id=sendgrid_message_id,
                sent_at=datetime.now(timezone.utc),
                retry_count=attempt - 1,
            )
            await BaseNotificationDispatcher.write_audit_log(
                action="NOTIFICATION_DISPATCHED",
                patient_id=uuid.UUID(request.recipient_id) if request.recipient_id else None,
                encounter_id=None,
                notification_type=request.template,
                channel="EMAIL",
                urgency_override=request.urgency_override,
                session=session,
            )
            logger.info(
                "email_dispatcher.sent",
                extra={
                    "notification_id": str(notification_id),
                    "sendgrid_id": sendgrid_message_id,
                    "template_name": request.template,
                    "template_id": template_id,
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

        await BaseNotificationDispatcher.write_audit_log(
            action="NOTIFICATION_FAILED",
            patient_id=uuid.UUID(request.recipient_id) if request.recipient_id else None,
            encounter_id=None,
            notification_type=request.template,
            channel="EMAIL",
            urgency_override=request.urgency_override,
            session=session,
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
