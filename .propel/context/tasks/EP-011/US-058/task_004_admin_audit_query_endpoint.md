---
id: TASK-004
title: "Implement `GET /api/v1/admin/audit` — Paginated Audit Log Query Endpoint"
user_story: US-058
epic: EP-011
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-058/TASK-001, US-057/TASK-002, US-056/TASK-004]
---

# TASK-004: Implement `GET /api/v1/admin/audit` — Paginated Audit Log Query Endpoint

> **Story:** US-058 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-058 AC Scenario 4 requires a paginated audit log query API for compliance admins. The endpoint must:

1. Be restricted to the `ADMIN` role (and a separate `COMPLIANCE_OFFICER` role if defined; otherwise `ADMIN` only per design.md §8.3).
2. Accept filter params: `user_id`, `from` (ISO-8601 datetime), `to` (ISO-8601 datetime), `entity_type`, `action`.
3. Return paginated results with cursor-based or offset-based pagination.
4. Mask PHI fields in the response: non-compliance roles receive only `entity_type` and `entity_id`; the `ADMIN` / compliance role sees full records (entity details only — no PHI field values are stored in `audit_log`).

> **Design clarification:** The `audit_log` table never stores PHI field values (DR-003, design.md §8.4) — it stores only `entity_type`, `entity_id`, `user_id`, `action`, `ip_address`, `user_agent`, and `timestamp`. The "masking" requirement in AC Scenario 4 therefore applies to `ip_address` and `user_agent` for non-admin roles.

The endpoint uses the **read replica** (`compliance_reader` role) per ADR-006/TR-010 since it is a read-only query.

---

## Acceptance Criteria Addressed

| US-058 AC | Requirement |
|---|---|
| **Scenario 4** | `GET /api/v1/admin/audit?user_id={id}&from={date}&to={date}` returns paginated audit entries; non-compliance roles see only `entity_type` and `entity_id`; admin/compliance roles see full record |
| **DoD** | `GET /api/v1/admin/audit` paginated query endpoint — compliance admin role only |

---

## Implementation Steps

### 1. Create `backend/app/schemas/audit.py` — Pydantic response schemas

```python
"""Pydantic schemas for the audit log query API.

Two schemas are used:
  - AuditLogEntryRedacted: returned to ADMIN role (ip_address/user_agent visible)
  - AuditLogEntrySummary:  returned to other roles (only entity_type, entity_id, action, timestamp)

Note: PHI field values are NEVER stored in audit_log — these schemas are safe
to return as-is; masking only applies to ip_address and user_agent for non-admin.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.audit_log import AuditAction


class AuditLogEntrySummary(BaseModel):
    """Minimal audit log entry for non-admin roles."""
    id: uuid.UUID
    action: AuditAction
    entity_type: str
    entity_id: Optional[uuid.UUID]
    timestamp: datetime

    class Config:
        from_attributes = True


class AuditLogEntryFull(AuditLogEntrySummary):
    """Full audit log entry for ADMIN / compliance roles."""
    user_id: Optional[uuid.UUID]
    ip_address: Optional[str]
    user_agent: Optional[str]


class AuditLogPage(BaseModel):
    """Paginated response envelope for audit log queries."""
    items: list[AuditLogEntryFull | AuditLogEntrySummary]
    total: int = Field(description="Total matching records (for pagination UI)")
    page: int
    page_size: int
    pages: int
```

### 2. Create `backend/app/routers/admin/audit.py` — router

```python
"""Audit log query endpoint.

Restricted to ADMIN role (compliance_reader DB role via read replica).
Supports filtering by user_id, from_dt, to_dt, entity_type, action.
Returns paginated results; ip_address/user_agent masked for non-ADMIN callers.

Design refs:
    design.md §3.3 /admin/audit router
    DR-003, SEC-006, US-058 AC Scenario 4
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.rbac import require_permission
from app.core.auth.jwt import TokenClaims
from app.db.session import get_read_db_session
from app.models.audit_log import AuditAction, AuditLog
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
        "Requires compliance_reader DB access via read replica."
    ),
)
async def query_audit_log(
    current_user: TokenClaims = Depends(require_permission("audit_log", "read")),
    user_id: Optional[uuid.UUID] = Query(None, description="Filter by acting user UUID"),
    from_dt: Optional[datetime] = Query(None, alias="from", description="Start datetime (ISO-8601 UTC)"),
    to_dt: Optional[datetime] = Query(None, alias="to", description="End datetime (ISO-8601 UTC)"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type, e.g. PATIENT"),
    action: Optional[AuditAction] = Query(None, description="Filter by action type"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_read_db_session),
) -> AuditLogPage:
    """Return paginated, filtered audit log entries.

    Filters are all optional and may be combined. Results are ordered by
    timestamp DESC (most recent first).
    """
    stmt = select(AuditLog)

    # Apply filters
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if from_dt:
        stmt = stmt.where(AuditLog.timestamp >= from_dt)
    if to_dt:
        stmt = stmt.where(AuditLog.timestamp <= to_dt)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type.upper())
    if action:
        stmt = stmt.where(AuditLog.action == action)

    # Count total matching rows
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    # Apply ordering and pagination
    offset = (page - 1) * page_size
    stmt = stmt.order_by(AuditLog.timestamp.desc()).offset(offset).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()

    # Role-based response shaping
    is_full_access = current_user.role == "ADMIN"
    schema_cls = AuditLogEntryFull if is_full_access else AuditLogEntrySummary
    items = [schema_cls.model_validate(row) for row in rows]

    pages = max(1, -(-total // page_size))  # ceiling division

    return AuditLogPage(items=items, total=total, page=page, page_size=page_size, pages=pages)
```

### 3. Register router in `backend/app/routers/__init__.py` (or `main.py`)

```python
from app.routers.admin.audit import router as audit_router
app.include_router(audit_router, prefix="/api/v1")
```

> Verify this is consistent with the existing router registration pattern in the project.

### 4. Add `compliance_reader` DB role connection to `backend/app/db/session.py`

The audit query endpoint must use the read replica + `compliance_reader` role:

```python
_READ_DB_URL = os.environ["READ_DATABASE_URL"]
_read_engine = create_async_engine(_READ_DB_URL, pool_size=10, max_overflow=5)
_ReadSessionLocal = async_sessionmaker(_read_engine, expire_on_commit=False)

@asynccontextmanager
async def get_read_db_session() -> AsyncSession:
    async with _ReadSessionLocal() as session:
        yield session
```

The `READ_DATABASE_URL` must point to the Cloud SQL read replica with `compliance_reader` credentials, provisioned via GCP Secret Manager.

---

## Validation

```bash
# Against a running dev server with test DB:
# 1. Obtain ADMIN JWT (from /api/v1/auth/token)
# 2. Call the endpoint with various filters

curl -H "Authorization: Bearer $ADMIN_JWT" \
  "http://localhost:8000/api/v1/admin/audit?entity_type=PATIENT&page=1&page_size=10"
# Expected: JSON with items array, total, page, pages fields

# Confirm non-ADMIN role cannot access
curl -H "Authorization: Bearer $NURSE_JWT" \
  "http://localhost:8000/api/v1/admin/audit"
# Expected: 403 Forbidden

# Confirm ADMIN response includes ip_address, user_agent
# Confirm non-ADMIN (if role allowed) response omits ip_address, user_agent
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/schemas/audit.py` | Create — `AuditLogEntrySummary`, `AuditLogEntryFull`, `AuditLogPage` |
| `backend/app/routers/admin/audit.py` | Create — `GET /admin/audit` paginated endpoint |
| `backend/app/routers/__init__.py` (or `main.py`) | Update — register `audit_router` |
| `backend/app/db/session.py` | Update — add `get_read_db_session()` if not already present |

---

## Definition of Done Checklist

- [ ] `GET /api/v1/admin/audit` returns 200 with paginated `AuditLogPage` for ADMIN role
- [ ] Non-ADMIN role receives 403 (enforced by `require_permission("audit_log", "read")`)
- [ ] Filters: `user_id`, `from`, `to`, `entity_type`, `action` all functional
- [ ] Pagination: `page`, `page_size`, `total`, `pages` correct in all responses
- [ ] ADMIN role response includes `ip_address` and `user_agent`; non-ADMIN response excludes them
- [ ] Endpoint uses read replica session (`get_read_db_session`)
- [ ] OpenAPI schema auto-generated and accessible at `/docs`
