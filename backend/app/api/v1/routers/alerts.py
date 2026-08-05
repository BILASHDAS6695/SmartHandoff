"""Alert resource router — RBAC-protected endpoints.

Design refs:
    US-031 AC Scenario 1   — POST /alerts creates PHARMACIST_ALERT
    US-032 AC Scenario 2   — PATCH /alerts/{id}/resolve with PHARMACIST role
    US-032 AC Scenario 4   — NURSE role returns 403 Forbidden
    US-057 AC Scenarios 1-2 — RBAC boundary testing
    design.md §3.2         — Agent container pattern; alert workflow
    ADR-001                — Pub/Sub before DB mutations

Key boundary tested in US-057 AC Scenarios 1 and 2:
    NURSE      → PATCH /alerts/{id}/resolve → 403 Forbidden
    PHARMACIST → PATCH /alerts/{id}/resolve → 2xx

US-031 Pharmacist Alert Endpoint:
    POST /api/v1/encounters/{encounter_id}/alerts → Creates pharmacist drug interaction alert

US-032 Alert Resolution Endpoint:
    PATCH /api/v1/alerts/{id}/resolve → Resolves HIGH_RISK_DRUG_CLASS or PHARMACIST_ALERT
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_write_db
from app.models.pharmacist_alert import PharmacistAlert
from app.schemas.pharmacist_alert import (
    AlertRead,
    AlertResolveRequest,
    PharmacistAlertCreate,
    PharmacistAlertRead,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])


_NOTIFICATION_TOPIC = "notification-requests"


@router.post(
    "/encounters/{encounter_id}/pharmacist-alerts",
    response_model=PharmacistAlertRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a pharmacist interaction alert for an encounter",
)
async def create_pharmacist_alert(
    encounter_id: uuid.UUID,
    payload: PharmacistAlertCreate,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "write"))],
) -> PharmacistAlertRead:
    """Persist a pharmacist alert and publish a Pub/Sub notification.

    - ``HIGH`` severity → ``priority=IMMEDIATE`` on ``notification-requests``
    - ``INCOMPLETE`` status → stored on the alert record for dashboard display

    Args:
        encounter_id: UUID of the encounter record.
        payload: Alert creation payload.
        db: Async write session (Cloud SQL primary).
        current_user: Validated JWT claims with alert:create permission (PHARMACIST/ADMIN).

    Returns:
        Newly created ``PharmacistAlertRead`` schema.

    Raises:
        HTTPException 422: If severity or source fields fail validation.
    """
    alert = PharmacistAlert(
        encounter_id=encounter_id,
        alert_type=payload.alert_type,
        severity=payload.severity,
        drug_pair=payload.drug_pair,
        interaction_description=payload.interaction_description,
        source=payload.source,
        interaction_check_status=payload.interaction_check_status,
        metadata_=payload.metadata_,
    )
    db.add(alert)
    await db.flush()  # Assign PK before publishing

    # Publish notification (simulated for now - actual GCP Pub/Sub integration needed)
    notification_priority = "IMMEDIATE" if payload.severity == "HIGH" else "STANDARD"
    message = {
        "event_type": "PHARMACIST_ALERT",
        "alert_id": str(alert.id),
        "encounter_id": str(encounter_id),
        "severity": payload.severity,
        "priority": notification_priority,
        "drug_pair": payload.drug_pair,
        "interaction_check_status": payload.interaction_check_status,
    }

    # TODO: Replace with actual Pub/Sub publish when infrastructure is ready
    # await pubsub.publish(topic=_NOTIFICATION_TOPIC, data=json.dumps(message).encode())
    logger.info(
        "Published PHARMACIST_ALERT alert_id=%s encounter_id=%s priority=%s message=%s",
        alert.id,
        encounter_id,
        notification_priority,
        json.dumps(message),
    )

    await db.commit()
    await db.refresh(alert)

    return PharmacistAlertRead.model_validate(alert)


@router.get("")
async def list_alerts(
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "list"))],
) -> dict:
    """List alerts — requires alert:list permission."""
    return {"alerts": [], "user": current_user.sub}


@router.get("/{alert_id}")
async def get_alert(
    alert_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "read"))],
) -> dict:
    """Get a single alert — requires alert:read permission."""
    return {"alert_id": str(alert_id), "user": current_user.sub}


@router.patch(
    "/{alert_id}/resolve",
    response_model=AlertRead,
    status_code=status.HTTP_200_OK,
    summary="Resolve a pharmacist alert",
    description=(
        "Marks a PHARMACIST_ALERT or HIGH_RISK_DRUG_CLASS alert as resolved. "
        "Restricted to PHARMACIST and ADMIN roles only (403 for all other roles)."
    ),
)
async def resolve_alert(
    alert_id: uuid.UUID,
    payload: AlertResolveRequest,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "resolve"))],
) -> AlertRead:
    """Resolve a pharmacist alert.

    Marks a PHARMACIST_ALERT or HIGH_RISK_DRUG_CLASS alert as resolved.
    Restricted to PHARMACIST and ADMIN roles only (enforced via alert:resolve permission).

    AC Scenario 1 (US-057): NURSE JWT → 403 Forbidden (denied by require_permission).
    AC Scenario 2 (US-032): PHARMACIST JWT → 200 OK with updated alert.
    AC Scenario 4 (US-032): Admin JWT → 200 OK (admin has alert:resolve permission).

    Args:
        alert_id: UUID of the alert to resolve.
        payload: Resolution type and optional note.
        db: Async write session (Cloud SQL primary).
        current_user: Validated JWT claims with alert:resolve permission (PHARMACIST/ADMIN).

    Returns:
        Updated :class:`AlertRead` reflecting the resolved state.

    Raises:
        HTTPException 404: Alert not found.
        HTTPException 409: Alert already resolved.
        HTTPException 403: Raised by RBAC dependency for non-pharmacist/admin roles.
    """
    # Look up alert by ID
    alert: PharmacistAlert | None = await db.get(PharmacistAlert, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found.",
        )

    # Check if already resolved
    if alert.status == "RESOLVED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alert {alert_id} is already resolved.",
        )

    # Update resolution fields
    now_utc = datetime.now(timezone.utc)
    alert.status = "RESOLVED"
    alert.resolution_type = payload.resolution_type
    alert.resolution_note = payload.resolution_note
    alert.resolved_by_user_id = current_user.user_id
    alert.resolved_at = now_utc

    db.add(alert)
    await db.flush()
    await db.refresh(alert)
    await db.commit()

    # Publish ALERT_RESOLVED event so pharmacist dashboard queue updates
    # TODO: Replace with actual Pub/Sub publish when infrastructure is ready
    message = {
        "event_type": "ALERT_RESOLVED",
        "alert_id": str(alert.id),
        "alert_type": alert.alert_type,
        "encounter_id": str(alert.encounter_id),
        "resolved_by_user_id": str(current_user.user_id),
        "resolved_at": now_utc.isoformat(),
        "priority": "STANDARD",
    }
    logger.info(
        "Published ALERT_RESOLVED alert_id=%s encounter_id=%s resolved_by=%s message=%s",
        alert.id,
        alert.encounter_id,
        current_user.user_id,
        json.dumps(message),
    )

    return AlertRead.model_validate(alert)
