---
id: TASK-002
title: "GET /api/v1/analytics/kpis — FastAPI Endpoint with RBAC & Unit Scoping"
user_story: US-061
epic: EP-012
sprint: 2
layer: Backend / API
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-061/TASK-001, US-057]
---

# TASK-002: GET /api/v1/analytics/kpis — FastAPI Endpoint with RBAC & Unit Scoping

> **Story:** US-061 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements the `GET /api/v1/analytics/kpis` FastAPI endpoint that:

1. Validates the JWT and enforces RBAC — only `MANAGER` and `ADMIN` roles are permitted (AC Scenario 4)
2. Parses `?from=`, `?to=`, and `?unit=` query parameters; defaults `from` to 30 days ago and `to` to today (AC Scenario 1)
3. Resolves the requesting manager's accessible units from `app_user.units` to scope the query (DoD unit filter)
4. Delegates data retrieval to `KpiQueryService` from TASK-001 using the read-replica session (TR-010)
5. Returns the de-identified `KpiResponse` schema within 3 seconds (AC Scenario 1 timing)

**Design references:**
- design.md §3.3 — FastAPI middleware stack; RBAC enforcer at middleware layer 5
- design.md §3.3 — Routers versioned `/api/v1/...`
- design.md ADR-006 — read API → read replica for all dashboard GET endpoints
- design.md §5.1 TR-001 — API response time p95 <500 ms; avoid N+1 queries
- US-061 AC Scenario 4 — `403 Forbidden` for `role=NURSE`; accessible to `MANAGER` and `ADMIN`
- US-061 DoD — Unit filter populated from `app_user.units`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Default 30-day window query returns within 3 s; response contains all 5 KPI metric columns |
| Scenario 2 | `?from=&to=` params update query window; response changes accordingly |
| Scenario 3 | Response body is `KpiResponse` — no PHI fields present at any code path |
| Scenario 4 | `role=NURSE` JWT → `403 Forbidden`; `role=MANAGER` JWT → `200 OK` |

---

## Implementation Steps

### 1. Create router module

```bash
touch api-gateway/app/routers/analytics.py
```

### 2. Implement `api-gateway/app/routers/analytics.py`

```python
"""FastAPI router for KPI analytics — manager/admin access only.

Endpoint:
    GET /api/v1/analytics/kpis

Query params:
    from  (date, ISO 8601, optional) — defaults to today - 30 days
    to    (date, ISO 8601, optional) — defaults to today
    unit  (str,  optional)           — single unit filter; omit for all accessible units

RBAC:
    Permitted roles: MANAGER, ADMIN (enforced by require_roles dependency)
    Denied:          NURSE, PHYSICIAN, PHARMACIST, PATIENT → 403 Forbidden

De-identification guarantee:
    This router never returns patient-level data.
    All responses use KpiResponse which contains only aggregated metrics.
    See US-061 AC Scenario 3 and design.md §8.3.

Design refs:
    design.md §3.3 — FastAPI backend structure
    design.md ADR-006 — read replica routing
    design.md TR-001 — <500 ms p95
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.query_service import KpiQueryService
from app.analytics.schemas import KpiResponse
from app.core.auth import TokenClaims, get_current_user
from app.core.rbac import require_roles
from app.db.session import get_read_session

router = APIRouter(prefix="/analytics", tags=["analytics"])

_PERMITTED_ROLES = {"MANAGER", "ADMIN"}
_DEFAULT_RANGE_DAYS = 30


@router.get(
    "/kpis",
    response_model=KpiResponse,
    summary="Retrieve aggregated KPI metrics for the analytics dashboard",
    description=(
        "Returns de-identified KPI aggregates from mv_kpi_daily filtered by date range "
        "and optional unit. Accessible to MANAGER and ADMIN roles only. "
        "No PHI is returned — response contains only counts, averages, and percentages."
    ),
    responses={
        200: {"description": "Aggregated KPI data"},
        400: {"description": "Invalid date range (from > to)"},
        403: {"description": "Insufficient role — MANAGER or ADMIN required"},
    },
)
async def get_kpis(
    from_date: datetime.date | None = Query(
        default=None,
        alias="from",
        description="Inclusive start date (ISO 8601). Defaults to today minus 30 days.",
    ),
    to_date: datetime.date | None = Query(
        default=None,
        alias="to",
        description="Inclusive end date (ISO 8601). Defaults to today.",
    ),
    unit: str | None = Query(
        default=None,
        description="Filter results to a single unit. Omit to include all accessible units.",
        max_length=100,
    ),
    current_user: TokenClaims = Depends(require_roles(_PERMITTED_ROLES)),
    read_session: AsyncSession = Depends(get_read_session),
) -> KpiResponse:
    """Return aggregated KPI metrics for the requesting manager's accessible units.

    Date range defaults to the last 30 days when not provided.
    Unit scoping is enforced using app_user.units from the token claims — managers
    cannot query units outside their access scope.
    """
    today = datetime.date.today()
    effective_from = from_date or (today - datetime.timedelta(days=_DEFAULT_RANGE_DAYS))
    effective_to = to_date or today

    if effective_from > effective_to:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"'from' date ({effective_from}) must not be after 'to' date ({effective_to})",
        )

    # Resolve accessible units from token claims (set by US-057 RBAC middleware)
    accessible_units: list[str] = current_user.units or []

    service = KpiQueryService(read_session=read_session)
    return await service.get_kpis(
        from_date=effective_from,
        to_date=effective_to,
        unit=unit,
        accessible_units=accessible_units,
    )
```

### 3. Define `require_roles` dependency in `api-gateway/app/core/rbac.py`

If `require_roles` does not yet exist (US-057 RBAC task may have created it), add the following — otherwise confirm the existing implementation satisfies the 403 contract:

```python
"""RBAC dependency factory for FastAPI route protection.

Usage:
    @router.get("/protected", dependencies=[Depends(require_roles({"MANAGER", "ADMIN"}))])
    # or as a parameter dependency to access the user object:
    current_user: TokenClaims = Depends(require_roles({"MANAGER", "ADMIN"}))

Design refs:
    design.md §3.3 — RBAC enforcer at middleware layer 5
    US-057 — role definitions and JWT claims structure
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.core.auth import TokenClaims, get_current_user


def require_roles(permitted_roles: set[str]) -> Callable[..., TokenClaims]:
    """Return a FastAPI dependency that validates the caller's role is in permitted_roles.

    Raises HTTP 403 if the role claim is absent or not in the permitted set.
    Raises HTTP 401 (via get_current_user) if the JWT is missing or invalid.
    """

    async def _check(current_user: TokenClaims = Depends(get_current_user)) -> TokenClaims:
        if current_user.role not in permitted_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not authorised to access this resource. "
                       f"Required: {sorted(permitted_roles)}",
            )
        return current_user

    return _check
```

### 4. Extend `TokenClaims` with `units` field

In `api-gateway/app/core/auth.py`, ensure `TokenClaims` carries the manager's accessible units from the JWT payload:

```python
class TokenClaims(BaseModel):
    sub: str          # user UUID
    role: str         # MANAGER | ADMIN | NURSE | PHYSICIAN | PHARMACIST | PATIENT
    units: list[str] = Field(default_factory=list)  # add if not already present
    exp: int
    iat: int
```

### 5. Register router in `api-gateway/app/main.py`

```python
from app.routers import analytics  # add to existing imports

# In the router registration block:
app.include_router(analytics.router, prefix="/api/v1")
```

### 6. Verify read-replica session dependency `get_read_session`

Confirm `api-gateway/app/db/session.py` exposes a `get_read_session` async generator that yields a read-replica `AsyncSession`. If not yet present (may be implemented in US-009), add:

```python
async def get_read_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession bound to the PostgreSQL read replica.

    Used exclusively for SELECT queries (CQRS read path).
    Design refs: design.md ADR-006, TR-010.
    """
    async with read_async_session_factory() as session:
        yield session
```

---

## Validation Checklist

- [ ] `GET /api/v1/analytics/kpis` returns `200 OK` with `KpiResponse` body for `role=MANAGER`
- [ ] `GET /api/v1/analytics/kpis` returns `200 OK` with `KpiResponse` body for `role=ADMIN`
- [ ] `GET /api/v1/analytics/kpis` returns `403 Forbidden` for `role=NURSE`
- [ ] `GET /api/v1/analytics/kpis` returns `403 Forbidden` for `role=PHYSICIAN`
- [ ] `GET /api/v1/analytics/kpis` returns `403 Forbidden` for `role=PHARMACIST`
- [ ] Missing `from`/`to` params → defaults applied (from = today - 30 days, to = today)
- [ ] `from > to` → `400 Bad Request` with descriptive error message
- [ ] `unit` param present → forwarded to `KpiQueryService`; scoped by `accessible_units`
- [ ] Read-replica `AsyncSession` used — write session never injected into this router
- [ ] Response body contains zero PHI fields at all code paths
- [ ] OpenAPI schema generated correctly — `from`, `to`, `unit` params visible in Swagger UI

---

## Files Created / Modified

| File | Action |
|------|--------|
| `api-gateway/app/routers/analytics.py` | Create |
| `api-gateway/app/core/rbac.py` | Create or extend `require_roles` |
| `api-gateway/app/core/auth.py` | Modify — add `units: list[str]` to `TokenClaims` if absent |
| `api-gateway/app/main.py` | Modify — register analytics router |
| `api-gateway/app/db/session.py` | Modify — add `get_read_session` if not present |
