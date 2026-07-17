---
id: TASK-005
title: "Bed Board REST API — GET /api/v1/beds and PATCH /api/v1/beds/{id}/status"
user_story: US-035
epic: EP-006
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-009, US-035/TASK-001, US-035/TASK-002]
---

# TASK-005: Bed Board REST API — GET /api/v1/beds and PATCH /api/v1/beds/{id}/status

> **Story:** US-035 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-035 requires two FastAPI endpoints in the `api-gateway` service:

1. **`GET /api/v1/beds`** — Returns filtered bed board entries from `mv_bed_board` (read replica). Supports `unit`, `status`, and `bed_type` query parameters. p95 response time must be <500ms (TR-001, US-035 AC Scenario 3).
2. **`PATCH /api/v1/beds/{id}/status`** — Allows a bed manager to manually override a bed's status (e.g., mark MAINTENANCE or RESERVED). Writes to the primary DB, then triggers a `mv_bed_board` refresh.

Both endpoints enforce JWT authentication and RBAC. The PATCH endpoint is restricted to `BedManager` role only. All access is recorded in the audit log.

**Design references:**
- US-035 AC Scenario 3 — GET /api/v1/beds filtered; p95 <500ms
- US-035 DoD — PATCH /api/v1/beds/{id}/status for bed manager role
- design.md §3.3 — FastAPI API layer structure; `/api/v1/beds` router
- design.md §8.3 — RBAC: bed board access restricted to BedManager and Admin
- design.md §5.1 TR-001 — read replica for GET endpoints; p95 <500ms
- ADR-006 — CQRS: GET queries go to read replica; mutations go to primary

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 3 | GET /api/v1/beds?unit=3A&status=VACANT returns 2 beds; p95 <500ms |
| DoD (PATCH) | PATCH /api/v1/beds/{id}/status restricted to BedManager role |

---

## Implementation Steps

### 1. Create router and Pydantic schemas

Create `api-gateway/app/routers/beds.py`:

```python
"""Bed board REST API router.

Endpoints:
    GET  /api/v1/beds                — Filtered bed board (read replica, mv_bed_board)
    PATCH /api/v1/beds/{id}/status   — Manual bed status override (BedManager role)

Design refs:
    US-035 AC Scenario 3    — GET filter; p95 <500ms
    US-035 DoD              — PATCH requires BedManager role
    design.md §3.3          — FastAPI API layer structure
    design.md §8.3          — RBAC: BedManager and Admin only for bed board
    ADR-006                 — CQRS: reads to replica, writes to primary
"""
from __future__ import annotations

import uuid
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.audit import emit_audit_event
from app.core.dependencies import get_read_db, get_write_db
from app.agents.bed_management.schemas import BedStatus
from app.agents.bed_management.refresh_service import BedBoardRefreshService
from app.models.bed import Bed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/beds", tags=["beds"])


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------

class BedBoardEntry(BaseModel):
    """Single bed entry returned by GET /api/v1/beds.

    Sourced from mv_bed_board (read replica) — no PHI included.
    """

    bed_id: str
    unit: str
    room: str
    bed_number: str
    bed_type: str
    status: BedStatus
    isolation_required: bool
    gender_designation: str
    predicted_discharge_time: str | None = None  # populated by US-036


class BedStatusPatchRequest(BaseModel):
    """Request body for PATCH /api/v1/beds/{id}/status."""

    status: BedStatus = Field(..., description="Target bed status")
    reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Reason for manual override (audit log)",
    )


class BedStatusPatchResponse(BaseModel):
    bed_id: str
    previous_status: BedStatus
    new_status: BedStatus


# ---------------------------------------------------------------------------
# GET /api/v1/beds
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=list[BedBoardEntry],
    summary="Retrieve filtered bed board entries",
    description=(
        "Returns bed records from mv_bed_board (read replica). "
        "Filter by unit, status, and/or bed_type. "
        "Requires Physician, Nurse, BedManager, or Admin role."
    ),
)
async def list_beds(
    unit: Annotated[str | None, Query(description="Filter by unit code, e.g. '3A'")] = None,
    status: Annotated[BedStatus | None, Query(description="Filter by bed status")] = None,
    bed_type: Annotated[str | None, Query(description="Filter by bed type, e.g. 'ICU'")] = None,
    _user: dict = Depends(require_role(["Admin", "BedManager", "Physician", "Nurse"])),
    read_db: AsyncSession = Depends(get_read_db),
) -> list[BedBoardEntry]:
    """Query mv_bed_board with optional filters; routes to read replica."""
    query = "SELECT * FROM mv_bed_board WHERE 1=1"
    params: dict = {}

    if unit is not None:
        query += " AND unit = :unit"
        params["unit"] = unit
    if status is not None:
        query += " AND status = :status"
        params["status"] = status.value
    if bed_type is not None:
        query += " AND bed_type = :bed_type"
        params["bed_type"] = bed_type

    result = await read_db.execute(text(query), params)
    rows = result.mappings().all()

    return [
        BedBoardEntry(
            bed_id=str(row["bed_id"]),
            unit=row["unit"],
            room=row["room"],
            bed_number=row["bed_number"],
            bed_type=row["bed_type"],
            status=BedStatus(row["status"]),
            isolation_required=row["isolation_required"],
            gender_designation=row["gender_designation"],
            predicted_discharge_time=(
                row["predicted_discharge_time"].isoformat()
                if row.get("predicted_discharge_time")
                else None
            ),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# PATCH /api/v1/beds/{id}/status
# ---------------------------------------------------------------------------

@router.patch(
    "/{bed_id}/status",
    response_model=BedStatusPatchResponse,
    summary="Manual bed status override",
    description=(
        "Allows a BedManager to manually set a bed's status "
        "(e.g. MAINTENANCE, RESERVED). "
        "Restricted to BedManager and Admin roles. Triggers mv_bed_board refresh."
    ),
)
async def patch_bed_status(
    bed_id: uuid.UUID,
    body: BedStatusPatchRequest,
    user: dict = Depends(require_role(["Admin", "BedManager"])),
    write_db: AsyncSession = Depends(get_write_db),
    read_db: AsyncSession = Depends(get_read_db),
    refresh_service: BedBoardRefreshService = Depends(lambda: BedBoardRefreshService),
) -> BedStatusPatchResponse:
    """Override bed status; write to primary; trigger mv_bed_board refresh."""
    # Load current bed status from primary for accurate previous_status
    result = await write_db.execute(select(Bed).where(Bed.id == bed_id))
    bed = result.scalar_one_or_none()
    if bed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bed {bed_id} not found",
        )

    previous_status = BedStatus(bed.status)

    await write_db.execute(
        update(Bed)
        .where(Bed.id == bed_id)
        .values(status=body.status.value)
    )
    await write_db.commit()

    logger.info(
        "Manual bed status override bed_id=%s %s → %s user_id=%s",
        bed_id,
        previous_status,
        body.status,
        user.get("sub"),
    )

    # Emit audit event (HIPAA — all PHI access and data mutations audited)
    await emit_audit_event(
        action="BED_STATUS_OVERRIDE",
        resource_id=str(bed_id),
        user_id=user["sub"],
        detail={"previous": previous_status.value, "new": body.status.value, "reason": body.reason},
    )

    # Non-blocking mv refresh
    await refresh_service.refresh_async()

    return BedStatusPatchResponse(
        bed_id=str(bed_id),
        previous_status=previous_status,
        new_status=body.status,
    )
```

### 2. Register the router in the API gateway

In `api-gateway/app/main.py`:

```python
from app.routers.beds import router as beds_router

app.include_router(beds_router, prefix="/api/v1")
```

### 3. Ensure `mv_bed_board` view includes required columns

Verify with the US-009 migration author that `mv_bed_board` exposes:
`bed_id`, `unit`, `room`, `bed_number`, `bed_type`, `status`, `isolation_required`, `gender_designation`, `predicted_discharge_time` (nullable, added by US-036).

If `predicted_discharge_time` is not yet in the view (US-036 not yet complete), make it optional in `BedBoardEntry` (already done above with `| None`).

---

## File Checklist

| File | Action |
|------|--------|
| `api-gateway/app/routers/beds.py` | Create |
| `api-gateway/app/main.py` | Update — register `beds_router` |

---

## Validation

- [ ] `GET /api/v1/beds` returns HTTP 200 with correct JSON when `mv_bed_board` is populated
- [ ] `GET /api/v1/beds?unit=3A&status=VACANT` returns only beds matching both filters
- [ ] `GET /api/v1/beds` with no filters returns all beds (no server error)
- [ ] `PATCH /api/v1/beds/{id}/status` with BedManager JWT returns HTTP 200 and updates DB
- [ ] `PATCH /api/v1/beds/{id}/status` with Physician JWT returns HTTP 403 Forbidden
- [ ] `PATCH /api/v1/beds/nonexistent-id/status` returns HTTP 404 Not Found
- [ ] Audit event emitted after successful PATCH (check audit_log table)
- [ ] `mv_bed_board` refresh triggered after PATCH (non-blocking)
- [ ] No PHI in response bodies — only bed coordinates and status
- [ ] GET endpoint response p95 <500ms under load (manual smoke test via `ab` or `locust`)

---

## Definition of Done

- [ ] `GET /api/v1/beds` endpoint implemented with unit/status/bed_type filters
- [ ] `PATCH /api/v1/beds/{id}/status` endpoint restricted to BedManager/Admin role
- [ ] Audit event emitted for every PATCH
- [ ] mv_bed_board refresh triggered post-PATCH
- [ ] Router registered in API gateway
- [ ] Code peer-reviewed before merge
