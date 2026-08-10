"""Patient portal preferences router.

Endpoints:
    PATCH /api/v1/portal/preferences — Update patient notification opt-out preference.

Auth:
    Patient JWT required. Staff JWTs are rejected.
    Patient is identified from JWT ``sub`` claim (not from URL path — avoids PHI exposure).

Security:
    ``urgency_override`` is NOT settable via this endpoint.
    Only ``notification_opt_out`` is exposed to the patient.

Design refs:
    US-067 AC Scenario 4, design.md §3.3, SEC-006.
"""
from __future__ import annotations

import logging
from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import get_current_patient_user
from app.db.deps import get_write_db
from app.models.patient import Patient
from app.schemas.portal import PortalPreferencesResponse, PortalPreferencesUpdateRequest
from app.services.patient_notification_publisher import PatientNotificationPublisher

router = APIRouter(prefix="/portal/preferences", tags=["portal"])


@router.patch(
    "",
    response_model=PortalPreferencesResponse,
    status_code=status.HTTP_200_OK,
    summary="Update patient notification opt-out preference",
    description=(
        "Allows an authenticated patient to opt out of or back in to "
        "non-urgent notifications. Urgent notifications (urgency_override=True) "
        "are always delivered regardless of this preference."
    ),
)
async def update_portal_preferences(
    body: PortalPreferencesUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_patient: Annotated[Patient, Depends(get_current_patient_user)],
) -> PortalPreferencesResponse:
    """Persist the patient's notification opt-out preference.

    Identifies the patient from the JWT ``sub`` claim. Writes directly to the
    PostgreSQL primary for immediate consistency. Creates an audit log entry
    for BR-012 compliance.

    Args:
        body: Request body with ``notification_opt_out`` boolean.
        db: Write-primary AsyncSession (injected via dependency).
        current_patient: Patient entity resolved from portal JWT sub claim.

    Returns:
        PortalPreferencesResponse confirming the persisted preference.

    Raises:
        HTTPException 404: Patient record not found (should not occur with valid JWT).
    """
    patient_id: UUID = current_patient.id

    # Fetch patient to confirm existence and get current state
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id)
    )
    patient: Patient | None = result.scalar_one_or_none()

    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient record not found",
        )

    # Update opt-out preference
    await db.execute(
        update(Patient)
        .where(Patient.id == patient_id)
        .values(notification_opt_out=body.notification_opt_out)
    )
    await db.commit()

    # Audit log entry (BR-012: patient preference changes must be auditable)
    from app.models.audit_log import AuditLog
    audit_entry = AuditLog(
        action="PATIENT_NOTIFICATION_OPT_OUT_UPDATED",
        resource_type="patient",
        resource_id=str(patient_id),
        user_id=patient_id,  # Patient is the actor
        user_role="PATIENT",
    )
    db.add(audit_entry)
    await db.commit()

    # Confirm change via email/SMS when patient opts back in (US-064)
    if not body.notification_opt_out:
        try:
            notifier = PatientNotificationPublisher()
            await notifier.send_both(
                phone=patient.phone,
                email=patient.email,
                subject="SmartHandoff notifications enabled",
                body=(
                    "Hi, you've opted back in to SmartHandoff notifications. "
                    "You'll receive updates about your care by text and email."
                ),
                patient_id=str(patient_id),
            )
        except Exception as exc:
            logger = logging.getLogger(__name__)
            logger.error(
                "Failed to send preference update notification",
                extra={"patient_id": str(patient_id), "error": str(exc)},
            )

    return PortalPreferencesResponse(
        notification_opt_out=body.notification_opt_out,
    )
