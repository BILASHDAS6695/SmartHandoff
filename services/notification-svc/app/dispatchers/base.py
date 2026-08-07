"""Base notification dispatcher — shared opt-out check and APScheduler retry.

Both TwilioSMSDispatcher and SendGridEmailDispatcher inherit this base to
avoid duplicating opt-out logic and retry scheduling (DRY principle).

Design refs:
    US-064 DoD — opt-out flag: patient.notification_opt_out=True → skip
    US-067 DoD — audit log entry for every notification delivery attempt (BR-012)
    TASK-003    — retry pattern established for SMS; reused for email
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import update, text
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
        urgency_override: bool = False,
        **extra_fields: object,
    ) -> None:
        """Update notification delivery_status, urgency_override, and optional extra fields."""
        await session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(
                delivery_status=status,
                urgency_override=urgency_override,
                updated_at=datetime.now(timezone.utc),
                **extra_fields,
            )
        )
        await session.commit()

    @staticmethod
    async def write_audit_log(
        action: str,
        patient_id: uuid.UUID | None,
        encounter_id: uuid.UUID | None,
        notification_type: str,
        channel: str,
        urgency_override: bool = False,
        session: AsyncSession | None = None,
    ) -> None:
        """Write a structured audit log entry for BR-012 compliance.

        All notification delivery attempts (dispatched, suppressed, failed)
        must produce an audit log entry. PHI is never included in log payload.

        Args:
            action: 'NOTIFICATION_DISPATCHED' | 'NOTIFICATION_SUPPRESSED_OPT_OUT' | 'NOTIFICATION_FAILED'
            patient_id: Patient UUID (non-PHI identifier).
            encounter_id: Encounter UUID (non-PHI identifier).
            notification_type: Notification type string.
            channel: SMS or EMAIL.
            urgency_override: Whether urgency override was active.
            session: AsyncSession for writing to audit_log table.
        """
        if session is None:
            return

        audit_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        try:
            await session.execute(
                text(
                    """
                    INSERT INTO audit_log (
                        id, created_at, user_id, user_role, resource_type, resource_id,
                        action, ip_address, user_agent, endpoint, request_id
                    ) VALUES (
                        :id, :created_at, NULL, 'SYSTEM', 'notification', :resource_id,
                        :action, NULL, 'notification-service', NULL, NULL
                    )
                    """
                ),
                {
                    "id": str(audit_id),
                    "created_at": now,
                    "resource_id": str(patient_id) if patient_id else "UNKNOWN",
                    "action": action,
                },
            )
            await session.commit()
            logger.info(
                "audit_log.notification_event",
                extra={
                    "action": action,
                    "patient_id": str(patient_id) if patient_id else None,
                    "encounter_id": str(encounter_id) if encounter_id else None,
                    "notification_type": notification_type,
                    "channel": channel,
                    "urgency_override": urgency_override,
                },
            )
        except Exception as exc:
            # Audit log write failure should NOT block notification dispatch
            logger.error(
                "audit_log.write_failed",
                extra={
                    "action": action,
                    "error": str(exc),
                },
            )
