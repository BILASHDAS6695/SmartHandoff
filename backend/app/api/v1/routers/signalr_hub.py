"""Router: POST /api/v1/signalr/task-updated

Internal broadcast endpoint called by AI agents after each AgentTask status
transition. Validates the payload and delegates to SignalRBroadcaster.

Security:
  - Requires a valid service-to-service JWT (internal scope claim).
  - Not exposed through Cloud Armor to public internet — ingress restricted to
    Cloud Run internal traffic only (VPC connector).

US-022 DoD:
  - POST /api/v1/signalr/task-updated broadcasts to correct groups.
  - Group naming: encounter-{id}, unit-{unitId}, role-{roleName}.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response

from app.core.auth.dependencies import get_current_internal_service
from app.signalr.broadcaster import SignalRBroadcaster
from app.signalr.schemas import TaskUpdatedPayload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signalr", tags=["signalr"])


# Dependency injection for SignalRBroadcaster
# This will be provided by main.py lifespan
_broadcaster_instance: SignalRBroadcaster | None = None


def get_signalr_broadcaster() -> SignalRBroadcaster:
    """FastAPI dependency: returns the singleton SignalRBroadcaster."""
    if _broadcaster_instance is None:
        raise RuntimeError("SignalRBroadcaster not initialised — check lifespan setup")
    return _broadcaster_instance


def get_signalr_broadcaster_optional() -> SignalRBroadcaster | None:
    """FastAPI dependency: returns broadcaster or None when not configured."""
    return _broadcaster_instance


def set_signalr_broadcaster(broadcaster: SignalRBroadcaster) -> None:
    """Set the global broadcaster instance. Called by main.py lifespan."""
    global _broadcaster_instance
    _broadcaster_instance = broadcaster


@router.post(
    "/task-updated",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Broadcast AgentTask status update to SignalR groups",
    description=(
        "Called by AI agents after each status transition. "
        "Broadcasts task_updated event to encounter-{id}, unit-{unitId}, role-{roleName} groups."
    ),
)
async def broadcast_task_updated(
    payload: TaskUpdatedPayload,
    _caller: Annotated[None, Depends(get_current_internal_service)],
    broadcaster: Annotated[SignalRBroadcaster, Depends(get_signalr_broadcaster)],
) -> Response:
    """Broadcast task_updated to all three SignalR groups.

    Returns 202 Accepted immediately — broadcast is fire-and-forget.
    Broadcast errors are logged but never returned as 5xx to the caller
    so that agent task updates are never blocked by SignalR failures.
    """
    logger.info(
        "Received task-updated broadcast request",
        extra={
            "task_id": str(payload.task_id),
            "encounter_id": str(payload.encounter_id),
            "new_status": payload.new_status,
        },
    )
    await broadcaster.broadcast_task_updated(payload)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/dev/broadcast-adt",
    status_code=status.HTTP_202_ACCEPTED,
    summary="DEV ONLY: broadcast a fake ADT event",
    description="Broadcasts a synthetic adt_event_received message to a unit group for UI testing.",
)
async def dev_broadcast_adt(
    broadcaster: Annotated[SignalRBroadcaster, Depends(get_signalr_broadcaster)],
) -> Response:
    """Send a fake ADT event to Azure SignalR for local dashboard testing.

    In production this endpoint should be removed or guarded.
    """
    payload = {
        "eventType": "A01",
        "patientUnit": "ICU",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "encounterId": str(uuid.uuid4()),
        "patientDisplayName": "Test, Patient",
    }
    await broadcaster.broadcast_adt_event_to_all(payload)
    logger.info("DEV broadcast ADT event", extra={"unit": "ICU"})
    return Response(status_code=status.HTTP_202_ACCEPTED)
