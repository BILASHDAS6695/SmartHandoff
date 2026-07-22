"""Alert resource router — RBAC-protected endpoints.

Key boundary tested in US-057 AC Scenarios 1 and 2:
    NURSE      → PATCH /alerts/{id}/resolve → 403 Forbidden
    PHARMACIST → PATCH /alerts/{id}/resolve → 2xx
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission

router = APIRouter(prefix="/alerts", tags=["alerts"])


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


@router.patch("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("alert", "resolve"))],
) -> dict:
    """Resolve an alert — requires alert:resolve permission (PHARMACIST/ADMIN only).

    AC Scenario 1: NURSE JWT → 403 Forbidden (denied by require_permission).
    AC Scenario 2: PHARMACIST JWT → 2xx (granted by require_permission).
    """
    return {"alert_id": str(alert_id), "resolved": True, "user": current_user.sub}
