---
id: TASK-005
title: "Implement `PATCH /api/v1/portal/preferences` — Patient Opt-Out Preference Endpoint"
user_story: US-067
epic: EP-013
sprint: 2
layer: Backend / API
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001]
---

# TASK-005: Implement `PATCH /api/v1/portal/preferences` — Patient Opt-Out Preference Endpoint

> **Story:** US-067 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-067 DoD specifies:

> *"`PATCH /api/v1/portal/preferences` endpoint: patient JWT required; updates `notification_opt_out`"*

This task creates the FastAPI endpoint that allows a patient (authenticated via portal JWT) to set or clear their notification opt-out preference. The endpoint persists `patient.notification_opt_out` on the `patient` table and returns `200 OK` on success.

Key design constraints:

1. **Patient JWT only** — only the patient can modify their own opt-out preference; staff JWTs are rejected
2. **Write to primary DB** — preference update goes to the PostgreSQL primary (not read replica)
3. **`urgency_override` is NOT settable by this endpoint** — only authorised agents set this flag on Pub/Sub messages; the portal preferences endpoint must never expose or accept `urgency_override`
4. **Idempotent PATCH** — calling `PATCH` with the same value multiple times is safe (no side effects beyond the first write)

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `PATCH` (not `PUT`) | Partial update of a single preference field; consistent with REST partial-update semantics |
| Body: `{"notification_opt_out": bool}` only | Minimal surface area; `urgency_override` is explicitly excluded from this schema |
| Patient identified from JWT claims (`sub`) | Avoids patient_id in URL path (PHI concern); JWT `sub` claim carries the patient UUID |
| Returns `200 OK` with updated preference | AC Scenario 4 requires `200 OK`; response body confirms the persisted state |
| Write to primary DB session (`get_db`) | Opt-out is a safety-critical preference; must be immediately consistent after write |
| Audit log entry on preference change | BR-012: patient consent/preference changes must be auditable |

Design refs: US-006 (`patient` model), TASK-001 (`notification_opt_out` column), design.md §3.3, SEC-006.

---

## Acceptance Criteria Addressed

| US-067 AC | Requirement |
|---|---|
| **Scenario 4** | `PATCH /api/v1/portal/preferences` with `{"notification_opt_out": true}` → `patient.notification_opt_out=True` persisted; `200 OK` returned |
| **DoD** | Endpoint exists; patient JWT required; updates `notification_opt_out` |

---

## Implementation Steps

### 1. Create request/response schemas

Add to `backend/app/schemas/portal.py` (create if not exists):

```python
"""Request and response schemas for the patient portal preferences API.

Security:
    ``urgency_override`` is intentionally excluded from this schema.
    That field is set exclusively by sending agents, never by patients.

Design refs:
    US-067 AC Scenario 4, US-067 Technical Notes.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PortalPreferencesUpdateRequest(BaseModel):
    """Request body for PATCH /api/v1/portal/preferences."""

    notification_opt_out: bool = Field(
        ...,
        description="True to opt out of non-urgent notifications; False to opt back in",
    )


class PortalPreferencesResponse(BaseModel):
    """Response body for PATCH /api/v1/portal/preferences."""

    notification_opt_out: bool = Field(
        description="Current opt-out preference as persisted",
    )
    message: str = Field(
        default="Preferences updated successfully",
        description="Human-readable confirmation",
    )
```

### 2. Create the portal preferences router

Create `backend/app/routers/portal_preferences.py`:

```python
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

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_patient_user
from app.db.session import get_db
from app.models.patient import Patient
from app.schemas.portal import PortalPreferencesResponse, PortalPreferencesUpdateRequest

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
    db: AsyncSession = Depends(get_db),
    current_patient=Depends(get_current_patient_user),
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
        resource_id=patient_id,
        patient_id=patient_id,
        metadata={"notification_opt_out": body.notification_opt_out},
    )
    db.add(audit_entry)
    await db.commit()

    return PortalPreferencesResponse(
        notification_opt_out=body.notification_opt_out,
    )
```

### 3. Register the router in `backend/app/main.py`

```python
from app.routers.portal_preferences import router as portal_preferences_router

# Add alongside existing routers:
app.include_router(portal_preferences_router, prefix="/api/v1")
```

---

## Validation

```bash
cd backend

# Syntax check
python -c "
import ast, pathlib
for f in ['app/schemas/portal.py', 'app/routers/portal_preferences.py']:
    ast.parse(pathlib.Path(f).read_text())
    print(f'Syntax check {f}: PASSED')
"

# Schema check — urgency_override must NOT be in request schema
python -c "
from app.schemas.portal import PortalPreferencesUpdateRequest
fields = PortalPreferencesUpdateRequest.model_fields
assert 'urgency_override' not in fields, 'SECURITY: urgency_override must not be in patient request schema'
assert 'notification_opt_out' in fields
print('Schema security check: PASSED')
print('notification_opt_out field present: PASSED')
"

# Manual API test (requires running server + patient JWT)
# curl -X PATCH http://localhost:8000/api/v1/portal/preferences \
#   -H 'Authorization: Bearer <patient_jwt>' \
#   -H 'Content-Type: application/json' \
#   -d '{"notification_opt_out": true}'
# Expected: 200 OK {"notification_opt_out": true, "message": "Preferences updated successfully"}
```

---

## Files Involved

| File | Action | Notes |
|------|--------|-------|
| `backend/app/schemas/portal.py` | Create | `PortalPreferencesUpdateRequest` and `PortalPreferencesResponse` schemas |
| `backend/app/routers/portal_preferences.py` | Create | `PATCH /api/v1/portal/preferences` endpoint with patient JWT guard |
| `backend/app/main.py` | Modify | Register `portal_preferences_router` under `/api/v1` |

---

## Definition of Done (Task-Level)

- [ ] `PATCH /api/v1/portal/preferences` endpoint implemented
- [ ] Patient JWT enforced via `get_current_patient_user` dependency
- [ ] Staff JWTs rejected (403 Forbidden)
- [ ] `notification_opt_out` persisted to `patient` table on primary DB
- [ ] `urgency_override` absent from request schema (security constraint)
- [ ] `200 OK` returned with current preference in response body
- [ ] Audit log entry created on preference change (BR-012)
- [ ] Syntax checks pass
- [ ] Router registered in `main.py`
