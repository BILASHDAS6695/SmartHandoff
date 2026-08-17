"""Helper service for creating physician review alerts.

Centralises alert creation + broadcast so it can be reused by the medication
reconciliation agent runner and by encounter lifecycle endpoints.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.physician_alert import PhysicianAlert
from app.signalr.broadcaster import SignalRBroadcaster

if TYPE_CHECKING:
    from app.models.encounter import Encounter

logger = logging.getLogger(__name__)


async def create_physician_medication_review_alert(
    db: AsyncSession,
    encounter: Encounter,
    title: str | None = None,
    message: str | None = None,
    broadcaster: SignalRBroadcaster | None = None,
) -> PhysicianAlert:
    """Persist a physician medication-review alert and broadcast it.

    Args:
        db: Write database session.
        encounter: Encounter requiring physician medication review.
        title: Optional alert title; defaults to a standard review title.
        message: Optional alert body; defaults to a standard message.
        broadcaster: Optional SignalR broadcaster for real-time notifications.

    Returns:
        The persisted PhysicianAlert instance.
    """
    patient = encounter.patient
    patient_name = "Patient"
    if patient is not None:
        patient_name = f"{patient.first_name or ''} {patient.last_name or ''}".strip() or "Patient"

    alert_title = title or "Medication review required"
    alert_message = message or (
        f"Encounter updated for {patient_name}. Please review, update, or add "
        "medications for this encounter."
    )

    alert = PhysicianAlert(
        encounter_id=encounter.id,
        patient_id=patient.id if patient else None,
        alert_type="MEDICATION_REVIEW",
        severity="MEDIUM",
        title=alert_title,
        message=alert_message,
        status="ACTIVE",
    )
    db.add(alert)
    await db.flush()
    await db.refresh(alert)

    if broadcaster is not None:
        try:
            await broadcaster.broadcast_alert_created(
                alert_id=str(alert.id),
                encounter_id=str(encounter.id),
                patient_unit=encounter.unit or "unknown",
                severity="MEDIUM",
                title=alert_title,
                message=alert_message,
                target_role="physician",
            )
        except Exception as exc:
            logger.warning("Failed to broadcast physician alert for encounter %s: %s", encounter.id, exc)

    logger.info(
        "Physician medication review alert created encounter=%s alert=%s",
        encounter.id,
        alert.id,
    )
    return alert
