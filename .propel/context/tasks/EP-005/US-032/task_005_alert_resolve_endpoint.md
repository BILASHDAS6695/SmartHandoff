---
id: TASK-005
title: "PATCH /api/v1/alerts/{id}/resolve — Pharmacist-Only Alert Resolution Endpoint"
user_story: US-032
epic: EP-005
sprint: 2
layer: Backend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-032/TASK-003, US-032/TASK-004, US-031/TASK-005]
---

# TASK-005: PATCH /api/v1/alerts/{id}/resolve — Pharmacist-Only Alert Resolution Endpoint

> **Story:** US-032 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task implements the `PATCH /api/v1/alerts/{id}/resolve` FastAPI endpoint that allows a pharmacist to mark a `HIGH_RISK_DRUG_CLASS` (or `PHARMACIST_ALERT`) as resolved. The endpoint:

1. Enforces RBAC: only the `PHARMACIST` role is authorised — any other role returns `403 Forbidden`.
2. Looks up the alert by `id`; returns `404 Not Found` if the alert does not exist or does not belong to an encounter the caller has access to.
3. Validates the `resolution_type` from `AlertResolveRequest`.
4. Sets `Alert.status = RESOLVED`, `Alert.resolved_by_user_id = caller_user_id`, `Alert.resolved_at = utcnow()`.
5. Persists to PostgreSQL and returns the updated `AlertRead` schema.
6. Publishes a `ALERT_RESOLVED` event to Pub/Sub `notification-requests` topic so the active pharmacist dashboard queue is updated in real-time.

**Design references:**
- US-032 AC Scenario 2 — `PATCH /api/v1/alerts/{id}/resolve`; pharmacist resolution workflow
- US-032 AC Scenario 4 — 403 Forbidden for non-pharmacist role
- design.md §3.3 — FastAPI routers; RBAC middleware; `/api/v1/alerts`
- design.md §8.3 — `alert: [resolve]` permission: `PHARMACIST` and `ADMIN` only

---

## Acceptance Criteria Addressed

| US-032 AC | Coverage |
|-----------|----------|
| **Scenario 2** | `status=RESOLVED`, `resolved_by_user_id`, `resolved_at` set; alert removed from active queue |
| **Scenario 4** | Nurse JWT → `403 Forbidden`; alert status unchanged |

---

## Implementation Steps

### 1. Create `backend/app/routers/alerts.py`

```python
"""FastAPI router for pharmacist alert operations.

Endpoints:
    PATCH /api/v1/alerts/{id}/resolve  — resolve a HIGH_RISK_DRUG_CLASS or PHARMACIST_ALERT

Design refs:
    US-032 AC Scenario 2 — resolution workflow
    US-032 AC Scenario 4 — 403 for non-pharmacist roles
    design.md §3.3        — RBAC middleware; /api/v1/alerts
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import get_current_user, require_role
from app.core.pubsub.publisher import publish_message
from app.db.session import get_db_session
from app.models.pharmacist_alert import PharmacistAlert
from app.schemas.pharmacist_alert import AlertRead, AlertResolveRequest

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

_ALERT_RESOLVED_TOPIC = "notification-requests"


@router.patch(
    "/{alert_id}/resolve",
    response_model=AlertRead,
    status_code=status.HTTP_200_OK,
    summary="Resolve a pharmacist alert",
    description=(
        "Marks a PHARMACIST_ALERT or HIGH_RISK_DRUG_CLASS alert as resolved. "
        "Restricted to PHARMACIST role only (403 for all other roles)."
    ),
)
async def resolve_alert(
    alert_id: uuid.UUID,
    payload: AlertResolveRequest,
    db: AsyncSession = Depends(get_db_session),
    current_user=Depends(require_role(["PHARMACIST"])),
) -> AlertRead:
    """Resolve a pharmacist alert.

    Args:
        alert_id: UUID of the alert to resolve.
        payload: Resolution type and optional note.
        db: Async DB session (injected).
        current_user: Authenticated user with PHARMACIST role (injected).

    Returns:
        Updated :class:`AlertRead` reflecting the resolved state.

    Raises:
        HTTPException(404): Alert not found.
        HTTPException(409): Alert already resolved.
        HTTPException(403): Raised by RBAC dependency for non-pharmacist callers.
    """
    alert: PharmacistAlert | None = await db.get(PharmacistAlert, alert_id)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found.",
        )

    if alert.status == "RESOLVED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alert {alert_id} is already resolved.",
        )

    now_utc = datetime.now(timezone.utc)
    alert.status = "RESOLVED"
    alert.resolution_type = payload.resolution_type
    alert.resolution_note = payload.resolution_note
    alert.resolved_by_user_id = current_user.id
    alert.resolved_at = now_utc

    db.add(alert)
    await db.flush()
    await db.refresh(alert)

    # Publish ALERT_RESOLVED event so the pharmacist dashboard queue updates
    await publish_message(
        topic=_ALERT_RESOLVED_TOPIC,
        data={
            "event_type": "ALERT_RESOLVED",
            "alert_id": str(alert.id),
            "alert_type": alert.alert_type,
            "encounter_id": str(alert.encounter_id),
            "resolved_by_user_id": str(current_user.id),
            "resolved_at": now_utc.isoformat(),
        },
        attributes={"priority": "STANDARD"},
    )

    return AlertRead.model_validate(alert)
```

### 2. Wire router into `backend/app/main.py`

```python
# Add to existing router registration block in main.py
from app.routers.alerts import router as alerts_router

app.include_router(alerts_router)
```

### 3. Implement `require_role` dependency (if not already present from US-057)

If the RBAC dependency `require_role` has not yet been implemented by the EP-011 US-057 tasks, add a minimal version:

```python
# backend/app/core/auth/dependencies.py (append if require_role not present)
from fastapi import Depends, HTTPException, status
from app.core.auth.jwt import get_current_user  # existing JWT validator


def require_role(allowed_roles: list[str]):
    """FastAPI dependency that enforces role-based access control.

    Args:
        allowed_roles: List of role strings permitted to access the endpoint.

    Returns:
        The authenticated user if their role is in `allowed_roles`.

    Raises:
        HTTPException(403): If the user's role is not in `allowed_roles`.
    """
    async def _check(current_user=Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{current_user.role}' is not authorised to perform this action. "
                    f"Required: {allowed_roles}."
                ),
            )
        return current_user
    return _check
```

---

## Validation

- [ ] `PATCH /api/v1/alerts/{id}/resolve` with valid pharmacist JWT and `resolution_type=REVIEWED_ACCEPTABLE` returns HTTP 200 with updated alert
- [ ] Response body contains `status=RESOLVED`, non-null `resolved_by_user_id`, non-null `resolved_at`
- [ ] Same endpoint called with a nurse JWT returns HTTP 403; alert status unchanged in DB
- [ ] Same endpoint called with an admin JWT returns HTTP 200 (admin has `resolve` permission per design.md §8.3)
- [ ] Calling `resolve` on an already-resolved alert returns HTTP 409
- [ ] Calling `resolve` with an unknown `alert_id` returns HTTP 404
- [ ] Pub/Sub `ALERT_RESOLVED` message published after successful resolution
- [ ] OpenAPI schema shows the endpoint under `/api/v1/alerts` tag

---

## Files Changed

| Action | Path |
|--------|------|
| Create | `backend/app/routers/alerts.py` |
| Modify | `backend/app/main.py` |
| Modify | `backend/app/core/auth/dependencies.py` (if `require_role` absent) |
