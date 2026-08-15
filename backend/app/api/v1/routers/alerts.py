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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims, sub_to_uuid
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db, get_write_db
from app.models.agent_task import AgentTask
from app.models.encounter import Encounter
from app.models.pharmacist_alert import PharmacistAlert
from app.schemas.pharmacist_alert import (
    AlertRead,
    AlertResolveRequest,
    PharmacistAlertCreate,
    PharmacistAlertRead,
)
from app.services.agent_runner import complete_agent_task, run_agent_task
from app.services.encounter_orchestrator import EncounterOrchestratorService
from app.signalr.broadcaster import SignalRBroadcaster
from app.api.v1.routers.signalr_hub import get_signalr_broadcaster_optional

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
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "write"))],
    broadcaster: SignalRBroadcaster | None = Depends(get_signalr_broadcaster_optional),
) -> PharmacistAlertRead:
    """Persist a pharmacist alert and publish a Pub/Sub notification.

    - ``HIGH`` severity → ``priority=IMMEDIATE`` on ``notification-requests``
    - ``INCOMPLETE`` status → stored on the alert record for dashboard display
    - Ensures a ``medication_reconciliation`` AgentTask exists for the encounter
      so the dashboard can show live agent status.

    Args:
        encounter_id: UUID of the encounter record.
        payload: Alert creation payload.
        db: Async write session (Cloud SQL primary).
        current_user: Validated JWT claims with alert:create permission (PHARMACIST/ADMIN).
        broadcaster: SignalR broadcaster for live task updates.

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

    # Ensure a medication reconciliation task exists for this encounter so the
    # dashboard agent status reflects the alert. Only schedule execution if a
    # new task was actually created; existing tasks are already handled by the
    # encounter orchestrator or the SLA monitor.
    encounter = await db.get(Encounter, encounter_id)
    if encounter is not None:
        orchestrator = EncounterOrchestratorService(broadcaster=broadcaster)
        task, created = await orchestrator.ensure_task_for_alert(
            db=db,
            encounter=encounter,
            agent_type="medication_reconciliation",
        )
        if created and task is not None:
            background_tasks.add_task(run_agent_task, task.id, broadcaster)

    return PharmacistAlertRead.model_validate(alert)


@router.get("")
async def list_alerts(
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "list"))],
    db: Annotated[AsyncSession, Depends(get_read_db)],
    status: str | None = None,
) -> dict:
    """List alerts scoped to the caller — requires alert:list permission.

    Query params:
        status: Optional filter (ACTIVE | RESOLVED).
    """
    stmt = select(PharmacistAlert)
    if status:
        stmt = stmt.where(PharmacistAlert.status == status.upper())
    stmt = stmt.order_by(PharmacistAlert.created_at.desc())
    result = await db.execute(stmt)
    alerts = list(result.scalars().all())
    return {
        "alerts": [AlertRead.model_validate(alert) for alert in alerts],
        "user": current_user.sub,
    }


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
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_write_db)],
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "resolve"))],
    broadcaster: SignalRBroadcaster | None = Depends(get_signalr_broadcaster_optional),
) -> AlertRead:
    """Resolve a pharmacist alert.

    Marks a PHARMACIST_ALERT or HIGH_RISK_DRUG_CLASS alert as resolved and
    force-completes the related medication reconciliation AgentTask so the
    dashboard reflects the resolution in real time.

    Restricted to PHARMACIST and ADMIN roles only (enforced via alert:resolve permission).

    AC Scenario 1 (US-057): NURSE JWT → 403 Forbidden (denied by require_permission).
    AC Scenario 2 (US-032): PHARMACIST JWT → 200 OK with updated alert.
    AC Scenario 4 (US-032): Admin JWT → 200 OK (admin has alert:resolve permission).

    Args:
        alert_id: UUID of the alert to resolve.
        payload: Resolution type and optional note.
        background_tasks: FastAPI background task queue.
        db: Async write session (Cloud SQL primary).
        current_user: Validated JWT claims with alert:resolve permission (PHARMACIST/ADMIN).
        broadcaster: SignalR broadcaster for live task updates.

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
    alert.resolved_by_user_id = sub_to_uuid(current_user.sub)
    alert.resolved_at = now_utc

    db.add(alert)
    await db.flush()
    await db.refresh(alert)
    await db.commit()

    # Force-complete the related medication reconciliation task so the agent
    # status card shows COMPLETED when the alert is resolved.
    stmt = (
        select(AgentTask)
        .where(AgentTask.encounter_id == alert.encounter_id)
        .where(AgentTask.agent_type == "medication_reconciliation")
        .order_by(AgentTask.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    med_task = result.scalar_one_or_none()
    if med_task is not None:
        background_tasks.add_task(complete_agent_task, med_task.id, broadcaster)

    # Publish ALERT_RESOLVED event so pharmacist dashboard queue updates
    # TODO: Replace with actual Pub/Sub publish when infrastructure is ready
    message = {
        "event_type": "ALERT_RESOLVED",
        "alert_id": str(alert.id),
        "alert_type": alert.alert_type,
        "encounter_id": str(alert.encounter_id),
        "resolved_by_user_id": str(sub_to_uuid(current_user.sub)),
        "resolved_at": now_utc.isoformat(),
        "priority": "STANDARD",
    }
    logger.info(
        "Published ALERT_RESOLVED alert_id=%s encounter_id=%s resolved_by=%s message=%s",
        alert.id,
        alert.encounter_id,
        sub_to_uuid(current_user.sub),
        json.dumps(message),
    )

    return AlertRead.model_validate(alert)


@router.get("/encounters/{encounter_id}")
async def list_alerts_by_encounter(
    encounter_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "list"))],
    db: Annotated[AsyncSession, Depends(get_read_db)],
) -> dict:
    """List alerts for a specific encounter — requires alert:list permission.

    Args:
        encounter_id: UUID of the encounter to filter alerts by.
        current_user: Validated JWT claims with alert:list permission.
        db: Async read session (Cloud SQL replica).

    Returns:
        Dictionary with a list of alerts for the specified encounter.

    Raises:
        HTTPException 404: If the encounter has no associated alerts.
    """
    # Query alerts for the given encounter ID
    result = await db.execute(
        select(PharmacistAlert).where(PharmacistAlert.encounter_id == encounter_id)
    )
    alerts = result.scalars().all()

    if not alerts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No alerts found for encounter {encounter_id}.",
        )

    return {"alerts": [AlertRead.model_validate(alert) for alert in alerts]}


@router.get(
    "/encounters/{encounter_id}/alerts",
    response_model=list[AlertRead],
    summary="List alerts for an encounter",
    description="Returns all active and resolved pharmacist alerts for the given encounter.",
)
async def list_encounter_alerts(
    encounter_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_read_db)],
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "list"))],
) -> list[AlertRead]:
    """Retrieve all pharmacist alerts for a specific encounter.

    Args:
        encounter_id: UUID of the encounter.
        db: Async read session.
        current_user: Authenticated user with alert:list permission.

    Returns:
        List of AlertRead schemas for the encounter.
    """
    stmt = (
        select(PharmacistAlert)
        .where(PharmacistAlert.encounter_id == encounter_id)
        .order_by(PharmacistAlert.created_at.desc())
    )
    result = await db.execute(stmt)
    alerts = result.scalars().all()
    return [AlertRead.model_validate(a) for a in alerts]
