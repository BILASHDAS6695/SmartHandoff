"""Physician alert resource router — RBAC-protected endpoints.

Design refs:
    US-030 extension — Physician medication review alerts created by the
    Medication Reconciliation Agent and resolved by physicians or admins.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims, sub_to_uuid
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db, get_write_db
from app.models.physician_alert import PhysicianAlert
from app.schemas.physician_alert import (
    PhysicianAlertCreate,
    PhysicianAlertRead,
    PhysicianAlertResolveRequest,
)
from app.signalr.broadcaster import SignalRBroadcaster
from app.api.v1.routers.signalr_hub import get_signalr_broadcaster_optional

logger_router = __import__("logging").getLogger(__name__)

router = APIRouter(prefix="/physician-alerts", tags=["physician-alerts"])


@router.post(
    "/encounters/{encounter_id}",
    response_model=PhysicianAlertRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a physician review alert for an encounter",
)
async def create_physician_alert(
    encounter_id: uuid.UUID,
    payload: PhysicianAlertCreate,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "write"))],
    broadcaster: SignalRBroadcaster | None = Depends(get_signalr_broadcaster_optional),
) -> PhysicianAlertRead:
    """Persist a physician alert and broadcast it to the physician role group."""
    alert = PhysicianAlert(
        encounter_id=encounter_id,
        patient_id=payload.patient_id,
        alert_type=payload.alert_type,
        severity=payload.severity,
        title=payload.title,
        message=payload.message,
        status="ACTIVE",
        metadata_=payload.metadata_,
    )
    db.add(alert)
    await db.flush()
    await db.commit()
    await db.refresh(alert)

    if broadcaster is not None:
        try:
            await broadcaster.broadcast_alert_created(
                alert_id=str(alert.id),
                encounter_id=str(encounter_id),
                patient_unit="unknown",
                severity=payload.severity,
                title=payload.title,
                message=payload.message or "Physician review required",
                target_role="physician",
            )
        except Exception as exc:
            logger_router.warning("Failed to broadcast physician alert: %s", exc)

    return PhysicianAlertRead.model_validate(alert)


@router.get(
    "",
    response_model=list[PhysicianAlertRead],
    summary="List physician alerts for the caller",
)
async def list_physician_alerts(
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "list"))],
    db: Annotated[AsyncSession, Depends(get_read_db)],
    status_filter: str | None = None,
) -> list[PhysicianAlertRead]:
    """List physician alerts.

    Query params:
        status_filter: Optional filter (ACTIVE | RESOLVED).
    """
    stmt = select(PhysicianAlert)
    if status_filter:
        stmt = stmt.where(PhysicianAlert.status == status_filter.upper())
    stmt = stmt.order_by(PhysicianAlert.created_at.desc())
    result = await db.execute(stmt)
    alerts = list(result.scalars().all())
    return [PhysicianAlertRead.model_validate(alert) for alert in alerts]


@router.get(
    "/{alert_id}",
    response_model=PhysicianAlertRead,
    summary="Get a single physician alert",
)
async def get_physician_alert(
    alert_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "read"))],
    db: Annotated[AsyncSession, Depends(get_read_db)],
) -> PhysicianAlertRead:
    """Get a single physician alert by ID."""
    alert: PhysicianAlert | None = await db.get(PhysicianAlert, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Physician alert {alert_id} not found.",
        )
    return PhysicianAlertRead.model_validate(alert)


@router.patch(
    "/{alert_id}/resolve",
    response_model=PhysicianAlertRead,
    status_code=status.HTTP_200_OK,
    summary="Resolve a physician alert",
)
async def resolve_physician_alert(
    alert_id: uuid.UUID,
    payload: PhysicianAlertResolveRequest,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "resolve"))],
) -> PhysicianAlertRead:
    """Resolve a physician alert.

    Restricted to PHYSICIAN and ADMIN roles (enforced via alert:resolve permission).
    """
    alert: PhysicianAlert | None = await db.get(PhysicianAlert, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Physician alert {alert_id} not found.",
        )

    if alert.status == "RESOLVED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Physician alert {alert_id} is already resolved.",
        )

    now_utc = datetime.now(timezone.utc)
    alert.status = "RESOLVED"
    alert.resolution_type = payload.resolution_type
    alert.resolution_note = payload.resolution_note
    alert.resolved_by_user_id = sub_to_uuid(current_user.sub)
    alert.resolved_at = now_utc

    db.add(alert)
    await db.flush()
    await db.commit()
    await db.refresh(alert)

    return PhysicianAlertRead.model_validate(alert)
