"""Admin audit log query router (US-058/TASK-004).

Provides a paginated, filtered query endpoint for compliance admins.
Restricted to the ADMIN role via RBAC (audit_log:read permission).

Design refs:
    design.md §3.3 /admin/audit router
    DR-003, SEC-006, US-058 AC Scenario 4
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db
from app.models.audit_log import AuditLog
from app.schemas.audit import AuditLogEntryFull, AuditLogEntrySummary, AuditLogPage

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


@router.get(
    "",
    response_model=AuditLogPage,
    summary="Query paginated audit log entries (ADMIN only)",
    description=(
        "Returns paginated PHI access audit records. "
        "ADMIN role sees full records including ip_address and user_agent. "
        "No PHI field values are stored in audit_log — the data is safe to return. "
        "Read via the replica database (compliance_reader role)."
    ),
)
async def query_audit_log(
    current_user: Annotated[TokenClaims, Depends(require_permission("audit_log", "read"))],
    user_id: Optional[uuid.UUID] = Query(None, description="Filter by acting user UUID"),
    from_dt: Optional[datetime] = Query(None, alias="from", description="Start datetime (ISO-8601 UTC)"),
    to_dt: Optional[datetime] = Query(None, alias="to", description="End datetime (ISO-8601 UTC)"),
    entity_type: Optional[str] = Query(None, description="Filter by resource_type, e.g. patient"),
    action: Optional[str] = Query(None, description="Filter by action, e.g. read, approve"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_read_db),
) -> AuditLogPage:
    """Return paginated, filtered audit log entries.

    All filters are optional and combinable.  Results are ordered by
    ``created_at`` DESC (most recent first).

    Role-based response shaping:
        ADMIN — ``AuditLogEntryFull`` (includes ip_address, user_agent, user_id)
        Others — ``AuditLogEntrySummary`` (entity info + timestamp only)
    """
    stmt = select(AuditLog)

    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if from_dt:
        stmt = stmt.where(AuditLog.created_at >= from_dt)
    if to_dt:
        stmt = stmt.where(AuditLog.created_at <= to_dt)
    if entity_type:
        stmt = stmt.where(AuditLog.resource_type == entity_type.lower())
    if action:
        stmt = stmt.where(AuditLog.action == action.lower())

    # Total count for pagination metadata
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    # Apply ordering and offset/limit pagination
    offset = (page - 1) * page_size
    stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()

    # Role-based response shaping: ADMIN sees full record; all others see summary
    is_full_access = current_user.role == "ADMIN"
    schema_cls = AuditLogEntryFull if is_full_access else AuditLogEntrySummary
    items = [schema_cls.model_validate(row) for row in rows]

    pages = max(1, -(-total // page_size))  # ceiling division

    return AuditLogPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/{entry_id}",
    response_model=AuditLogEntryFull,
    summary="Get a single audit log entry by ID (ADMIN only)",
)
async def get_audit_entry(
    entry_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("audit_log", "read"))],
    db: AsyncSession = Depends(get_read_db),
) -> AuditLogEntryFull:
    """Retrieve a single audit log entry — requires audit_log:read (ADMIN only)."""
    from fastapi import HTTPException, status

    result = await db.execute(select(AuditLog).where(AuditLog.id == entry_id))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit entry not found")
    return AuditLogEntryFull.model_validate(row)
