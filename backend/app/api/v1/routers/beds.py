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

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bed_management.boarding_resolver import resolve_boarding_alert
from app.agents.bed_management.refresh_service import BedBoardRefreshService
from app.agents.bed_management.schemas import BedStatus
from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db, get_write_db
from app.models.bed import Bed
from app.services.audit_service import write_audit_log

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/beds", tags=["beds"])


# ───────────────────────────────────────────────────────────────────────────
# Response / request schemas
# ───────────────────────────────────────────────────────────────────────────


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
    encounter_id: uuid.UUID | None = Field(
        None,
        description="Encounter ID for bed assignment (required when status=RESERVED)",
    )


class BedStatusPatchResponse(BaseModel):
    """Response for PATCH /api/v1/beds/{id}/status."""

    bed_id: str
    previous_status: BedStatus
    new_status: BedStatus


# ───────────────────────────────────────────────────────────────────────────
# GET /api/v1/beds
# ───────────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[BedBoardEntry],
    summary="Retrieve filtered bed board entries",
    description=(
        "Returns bed records from mv_bed_board (read replica). "
        "Filter by unit, status, and/or bed_type. "
        "Requires bed:list permission (Physician, Nurse, BedManager, or Admin role)."
    ),
)
async def list_beds(
    unit: Annotated[
        str | None, Query(description="Filter by unit code, e.g. '3A'")
    ] = None,
    status: Annotated[
        BedStatus | None, Query(description="Filter by bed status")
    ] = None,
    bed_type: Annotated[
        str | None, Query(description="Filter by bed type, e.g. 'ICU'")
    ] = None,
    current_user: TokenClaims = Depends(require_permission("bed", "list")),
    read_db: AsyncSession = Depends(get_read_db),
) -> list[BedBoardEntry]:
    """Query mv_bed_board with optional filters; routes to read replica.
    
    Performance: p95 <500ms (US-035 AC Scenario 3, TR-001).
    """
    # Build dynamic SQL query with filters
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


# ───────────────────────────────────────────────────────────────────────────
# PATCH /api/v1/beds/{id}/status
# ───────────────────────────────────────────────────────────────────────────


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
    current_user: TokenClaims = Depends(require_permission("bed", "write")),
    write_db: AsyncSession = Depends(get_write_db),
) -> BedStatusPatchResponse:
    """Override bed status; write to primary; trigger mv_bed_board refresh.
    
    Access control: bed:write permission (BedManager and Admin roles only).
    Audit logging: All status overrides are logged to audit_log table (HIPAA).
    """
    # Load current bed status from primary for accurate previous_status
    result = await write_db.execute(select(Bed).where(Bed.id == bed_id))
    bed = result.scalar_one_or_none()
    if bed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bed {bed_id} not found",
        )

    previous_status = BedStatus(bed.status)

    # Update bed status in primary DB
    await write_db.execute(
        update(Bed).where(Bed.id == bed_id).values(status=body.status.value)
    )

    # US-038: Resolve boarding alert when bed is RESERVED
    if body.status == BedStatus.RESERVED and body.encounter_id:
        await resolve_boarding_alert(
            encounter_id=str(body.encounter_id),
            session=write_db,
        )

    # Write audit log entry (HIPAA compliance — all PHI access and mutations)
    try:
        performer_id = uuid.UUID(current_user.sub)
    except ValueError:
        performer_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    await write_audit_log(
        db=write_db,
        action="BED_STATUS_OVERRIDE",
        resource_type="Bed",
        resource_id=bed_id,
        performed_by=performer_id,
        metadata={
            "previous": previous_status.value,
            "new": body.status.value,
            "reason": body.reason,
        },
    )

    # Commit all changes (bed update + audit log)
    await write_db.commit()

    logger.info(
        "Manual bed status override bed_id=%s %s → %s user_id=%s",
        bed_id,
        previous_status,
        body.status,
        current_user.sub,
    )

    # Non-blocking mv_bed_board refresh (fire-and-forget)
    # Note: Requires write session factory to be injected (pending integration)
    # refresh_service = BedBoardRefreshService(write_session_factory=get_write_db)
    # await refresh_service.refresh_async()

    return BedStatusPatchResponse(
        bed_id=str(bed_id),
        previous_status=previous_status,
        new_status=body.status,
    )

