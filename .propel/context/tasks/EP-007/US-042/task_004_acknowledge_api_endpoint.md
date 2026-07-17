---
id: TASK-004
title: "`PATCH /api/v1/care/escalations/{id}/acknowledge` — Staff RBAC Acknowledgement Endpoint"
user_story: US-042
epic: EP-007
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-042/TASK-001, US-024]
---

# TASK-004: `PATCH /api/v1/care/escalations/{id}/acknowledge` — Staff RBAC Acknowledgement Endpoint

> **Story:** US-042 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-042 AC Scenarios 2 and 4 require a `PATCH /api/v1/care/escalations/{id}/acknowledge` endpoint:

- **Scenario 2**: When a nurse acknowledges, `status=ACKNOWLEDGED` and `acknowledged_at` is recorded; no further escalation reminders are sent.
- **Scenario 4**: A patient JWT receives `403 Forbidden`; only staff JWT holders (nurse, physician, charge_nurse) may acknowledge.

**RBAC matrix (design.md §8.3):**

| Role | Acknowledge? |
|---|---|
| Admin | ✓ |
| Physician | ✓ |
| Nurse | ✓ |
| Charge Nurse | ✓ |
| Pharmacist | ✗ (403) |
| Bed Manager | ✗ (403) |
| Patient | ✗ (403) |

**Business rules:**
- `404 Not Found` if `escalation_id` does not exist or `deleted_at IS NOT NULL`
- `409 Conflict` if `status` is already `ACKNOWLEDGED` — idempotent acknowledgement is rejected to prevent double-counting
- `200 OK` with the updated escalation record on success
- The HIPAA audit middleware (design.md §3.3 middleware stack step 7) writes an `audit_log` entry for every PATCH to this endpoint automatically — no manual audit write required in the router

**Design references:**
- design.md §3.3 — FastAPI backend routers: `/api/v1/care/escalations`
- design.md §3.3 — Middleware stack: JWT Validator → RBAC Enforcer → PHI Log Sanitiser → HIPAA Audit Logger
- design.md §8.3 — RBAC permission matrix
- design.md §8.2 — Staff JWT flow; `roles` claim extracted from JWT
- US-042 AC Scenario 2 — `status=ACKNOWLEDGED`, `acknowledged_at` recorded; no further reminders
- US-042 AC Scenario 4 — patient JWT → 403 Forbidden
- ADR-006 — write commands go through FastAPI write API → PostgreSQL primary

---

## Acceptance Criteria Addressed

| US-042 AC Scenario | Coverage |
|---|---|
| **Scenario 2** | `status=ACKNOWLEDGED`, `acknowledged_at=<timestamp>`, `acknowledged_by=<user_id>` persisted; `200 OK` returned |
| **Scenario 4** | Patient JWT → `403 Forbidden`; pharmacist JWT → `403 Forbidden` |

---

## Implementation Steps

### 1. Define request/response schemas in `api-gateway/app/schemas/care_escalation.py`

```python
"""Pydantic schemas for the care escalation acknowledgement endpoint.

Design refs:
    US-042 AC Scenarios 2, 4
    design.md §3.3 — FastAPI routers
    design.md §8.3 — RBAC
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class CareEscalationStatusEnum(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED_TO_SUPERVISOR = "ESCALATED_TO_SUPERVISOR"


class CareEscalationAcknowledgeResponse(BaseModel):
    """Response body for PATCH /api/v1/care/escalations/{id}/acknowledge."""

    id: UUID
    encounter_id: UUID
    patient_id: UUID
    status: CareEscalationStatusEnum
    sent_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: UUID | None
    escalated_to_supervisor: bool
    escalated_at: datetime | None

    class Config:
        from_attributes = True
```

### 2. Implement `api-gateway/app/routers/care_escalations.py`

```python
"""FastAPI router for care escalation acknowledgement.

Endpoint:
    PATCH /api/v1/care/escalations/{escalation_id}/acknowledge

RBAC:
    Admin        : ✓
    Physician    : ✓
    Nurse        : ✓
    Charge Nurse : ✓
    Pharmacist   : ✗ (403)
    Bed Manager  : ✗ (403)
    Patient      : ✗ (403)

Business rules:
    200 OK        : Acknowledged successfully; status=ACKNOWLEDGED, acknowledged_at set.
    403 Forbidden : Role not permitted (patient, pharmacist, bed_manager).
    404 Not Found : escalation_id not found or soft-deleted.
    409 Conflict  : Escalation already acknowledged (status=ACKNOWLEDGED).

Design refs:
    design.md §3.3 — FastAPI routers
    design.md §8.3 — RBAC permission matrix
    US-042 AC Scenarios 2, 4
    ADR-006 — write path uses primary DB session
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_any_role
from app.core.dependencies import get_write_db
from app.models.care_escalation import CareEscalation
from app.models.enums import CareEscalationStatus
from app.schemas.care_escalation import CareEscalationAcknowledgeResponse

router = APIRouter(prefix="/api/v1/care", tags=["care-escalations"])
logger = logging.getLogger(__name__)

_ALLOWED_ROLES = {"admin", "physician", "nurse", "charge_nurse"}


@router.patch(
    "/escalations/{escalation_id}/acknowledge",
    response_model=CareEscalationAcknowledgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge an urgent patient escalation alert",
)
async def acknowledge_escalation(
    escalation_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_write_db),
    _: None = Depends(require_any_role(_ALLOWED_ROLES)),
) -> CareEscalationAcknowledgeResponse:
    """Mark a care escalation as acknowledged by a staff member.

    Sets status=ACKNOWLEDGED, recorded_at=now(), acknowledged_by=current_user.id.
    Returns 409 Conflict if already acknowledged (prevents double-counting).
    The HIPAA audit middleware logs this access automatically — no manual audit write needed.

    Args:
        escalation_id: UUID of the care escalation to acknowledge.
        current_user:  Validated JWT payload (injected by auth middleware).
        session:       Async write DB session (primary PostgreSQL).

    Returns:
        CareEscalationAcknowledgeResponse with updated fields.

    Raises:
        HTTPException(403): Role not permitted.
        HTTPException(404): Escalation not found or soft-deleted.
        HTTPException(409): Escalation already acknowledged.
    """
    # Fetch from write replica to avoid replication lag on the acknowledged_at check
    result = await session.execute(
        select(CareEscalation).where(
            CareEscalation.id == escalation_id,
            CareEscalation.deleted_at.is_(None),
        )
    )
    escalation: CareEscalation | None = result.scalar_one_or_none()

    if escalation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Care escalation {escalation_id} not found.",
        )

    if escalation.status == CareEscalationStatus.ACKNOWLEDGED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Escalation has already been acknowledged.",
        )

    now = datetime.now(tz=timezone.utc)
    escalation.status = CareEscalationStatus.ACKNOWLEDGED
    escalation.acknowledged_at = now
    escalation.acknowledged_by = uuid.UUID(current_user["sub"])

    session.add(escalation)
    await session.commit()
    await session.refresh(escalation)

    logger.info(
        "care_escalation.acknowledged",
        extra={
            "escalation_id": str(escalation.id),
            "encounter_id": str(escalation.encounter_id),
            "acknowledged_by": current_user["sub"],
        },
    )

    return CareEscalationAcknowledgeResponse.model_validate(escalation)
```

### 3. Register the router in `api-gateway/app/main.py`

```python
# In api-gateway/app/main.py, add after existing router inclusions:

from app.routers.care_escalations import router as care_escalations_router

app.include_router(care_escalations_router)
```

### 4. Manual smoke test

```bash
# 1. Acknowledge with a valid nurse JWT
curl -X PATCH https://api.smarthandoff.dev/api/v1/care/escalations/{id}/acknowledge \
  -H "Authorization: Bearer {nurse_jwt}"
# Expected: 200 OK — {"status": "ACKNOWLEDGED", "acknowledged_at": "...", ...}

# 2. Attempt to acknowledge again (idempotency rejection)
curl -X PATCH https://api.smarthandoff.dev/api/v1/care/escalations/{id}/acknowledge \
  -H "Authorization: Bearer {nurse_jwt}"
# Expected: 409 Conflict — {"detail": "Escalation has already been acknowledged."}

# 3. Patient JWT attempt
curl -X PATCH https://api.smarthandoff.dev/api/v1/care/escalations/{id}/acknowledge \
  -H "Authorization: Bearer {patient_jwt}"
# Expected: 403 Forbidden

# 4. Unknown escalation_id
curl -X PATCH https://api.smarthandoff.dev/api/v1/care/escalations/00000000-0000-0000-0000-000000000000/acknowledge \
  -H "Authorization: Bearer {nurse_jwt}"
# Expected: 404 Not Found
```

---

## Definition of Done Checklist

- [ ] `api-gateway/app/schemas/care_escalation.py` created with `CareEscalationAcknowledgeResponse`
- [ ] `api-gateway/app/routers/care_escalations.py` created with `PATCH /api/v1/care/escalations/{id}/acknowledge`
- [ ] RBAC enforced via `require_any_role({"admin", "physician", "nurse", "charge_nurse"})` dependency
- [ ] `403 Forbidden` returned for patient and pharmacist roles
- [ ] `404 Not Found` returned for unknown or soft-deleted escalation
- [ ] `409 Conflict` returned for already-acknowledged escalation
- [ ] `acknowledged_by` set to `current_user["sub"]` (UUID from JWT `sub` claim)
- [ ] Router registered in `api-gateway/app/main.py`
- [ ] No PHI (patient name, MRN, phone, email) in response body or log lines

---

## Notes

- **HIPAA Audit**: The HIPAA Audit Logger middleware (design.md §3.3, step 7) writes an `audit_log` entry for every PATCH to this endpoint automatically. The router does not need to write audit records explicitly.
- **`ESCALATED_TO_SUPERVISOR` acknowledgement**: The endpoint allows acknowledging an escalation that is already in `ESCALATED_TO_SUPERVISOR` status — this is a valid state (supervisor was notified, nurse then acknowledges). The `409` is only returned for `ACKNOWLEDGED → ACKNOWLEDGED` transitions.
- **Write session**: Uses `get_write_db` (primary PostgreSQL) to avoid read-replica lag when checking `acknowledged_at` — consistent with ADR-006 write path.
