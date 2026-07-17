---
id: TASK-001
title: "Export Router — Endpoint Scaffold, Query Parameters & RBAC Enforcement"
user_story: US-063
epic: EP-012
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-063, US-061/TASK-002, US-057]
---

# TASK-001: Export Router — Endpoint Scaffold, Query Parameters & RBAC Enforcement

> **Story:** US-063 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-063 requires a `GET /api/v1/analytics/export` endpoint that generates KPI report downloads. Before the CSV streaming logic (TASK-002) and PDF rendering logic (TASK-003 / TASK-004) are built, this task establishes:

- The FastAPI router module `api-gateway/app/routers/analytics_export.py`
- Query parameter parsing: `format` (csv | pdf), `from` (ISO 8601 date), `to` (ISO 8601 date)
- RBAC enforcement: `MANAGER` and `ADMIN` roles only — `403 Forbidden` for all other roles (AC Scenario 4)
- Input validation: `format` must be `csv` or `pdf`; `from` must not be after `to`; max date range 366 days
- Router registration in `api-gateway/app/main.py`
- Pydantic `ExportQueryParams` schema for validated dependency injection

**Design references:**
- design.md §3.3 — FastAPI routers versioned `/api/v1/...`; RBAC enforcer at middleware layer 5
- design.md §3.3 — Middleware stack: JWT Validator → RBAC Enforcer → PHI Log Sanitiser
- US-063 AC Scenario 4 — `role=NURSE` → `403 Forbidden`
- US-063 Technical Notes — `StreamingResponse` for CSV; `BackgroundTasks` for PDF

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 4 | `role=NURSE` JWT → `403 Forbidden`; `role=MANAGER` or `role=ADMIN` JWT → request proceeds to export handler |
| Scenario 1 | `?format=csv&from=…&to=…` parsed and validated; downstream handlers receive typed `ExportQueryParams` |
| Scenario 2 | `?format=pdf&from=…&to=…` parsed and validated; downstream handler dispatched |

---

## Implementation Steps

### 1. Create router module file

```bash
touch api-gateway/app/routers/analytics_export.py
```

### 2. Implement `api-gateway/app/routers/analytics_export.py`

```python
"""FastAPI router for KPI analytics export — CSV and PDF download.

Endpoint:
    GET /api/v1/analytics/export

Query params:
    format  (str,  required) — "csv" or "pdf"
    from    (date, ISO 8601, required) — start of reporting window (inclusive)
    to      (date, ISO 8601, required) — end of reporting window (inclusive)

RBAC:
    Permitted roles: MANAGER, ADMIN
    Denied:          NURSE, PHYSICIAN, PHARMACIST, PATIENT → 403 Forbidden

De-identification guarantee:
    Export handlers (TASK-002, TASK-004) only receive aggregated KPI data sourced
    from KpiQueryService. Patient-level data never reaches this router.

Design refs:
    design.md §3.3 — FastAPI backend structure; RBAC enforcement
    design.md ADR-006 — read replica routing for all dashboard GET paths
    US-063 AC Scenario 4 — 403 for nurse role
    US-063 Technical Notes — StreamingResponse (CSV); BackgroundTasks (PDF)
"""
from __future__ import annotations

import datetime
from enum import Enum

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.query_service import KpiQueryService
from app.core.auth import TokenClaims, get_current_user
from app.core.rbac import require_roles
from app.db.session import get_read_session
from app.export.csv_exporter import build_csv_streaming_response
from app.export.pdf_exporter import schedule_pdf_export

router = APIRouter(prefix="/analytics", tags=["analytics-export"])

_ALLOWED_ROLES = {"MANAGER", "ADMIN"}
_MAX_DATE_RANGE_DAYS = 366


class ExportFormat(str, Enum):
    csv = "csv"
    pdf = "pdf"


@router.get(
    "/export",
    summary="Export KPI analytics report",
    responses={
        200: {"description": "CSV file download"},
        202: {"description": "PDF export accepted — poll download URL"},
        400: {"description": "Invalid query parameters"},
        403: {"description": "Insufficient role"},
    },
)
async def export_kpi_report(
    format: ExportFormat = Query(..., description="Export format: csv or pdf"),
    from_date: datetime.date = Query(..., alias="from", description="Start date (ISO 8601)"),
    to_date: datetime.date = Query(..., alias="to", description="End date (ISO 8601)"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: TokenClaims = Depends(require_roles(_ALLOWED_ROLES)),
    session: AsyncSession = Depends(get_read_session),
) -> StreamingResponse:
    """Return CSV stream immediately or schedule PDF generation.

    Raises:
        HTTPException 400: if from_date > to_date or date range exceeds 366 days.
        HTTPException 403: enforced by require_roles dependency.
    """
    _validate_date_range(from_date, to_date)

    query_service = KpiQueryService(session)

    if format == ExportFormat.csv:
        kpi_data = await query_service.get_kpi_data(
            from_date=from_date,
            to_date=to_date,
            units=current_user.units,
        )
        return build_csv_streaming_response(kpi_data, from_date, to_date)

    # PDF — schedule as background task; return 202 with polling URL
    return await schedule_pdf_export(
        background_tasks=background_tasks,
        query_service=query_service,
        from_date=from_date,
        to_date=to_date,
        units=current_user.units,
        hospital_name=current_user.hospital_name,
    )


def _validate_date_range(
    from_date: datetime.date,
    to_date: datetime.date,
) -> None:
    """Validate that the requested date range is logically sound.

    Raises:
        HTTPException 400: if from_date is after to_date.
        HTTPException 400: if date range exceeds _MAX_DATE_RANGE_DAYS.
    """
    if from_date > to_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'from' must not be after 'to'.",
        )
    if (to_date - from_date).days > _MAX_DATE_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Date range must not exceed {_MAX_DATE_RANGE_DAYS} days.",
        )
```

### 3. Update `api-gateway/app/core/rbac.py` — add `require_roles` helper if not present

```python
# In app/core/rbac.py — add if not already present from US-061/TASK-002

from fastapi import Depends, HTTPException, status
from app.core.auth import TokenClaims, get_current_user


def require_roles(allowed: set[str]):
    """FastAPI dependency factory enforcing role-based access.

    Args:
        allowed: Set of role name strings that may access the endpoint.

    Returns:
        A dependency callable that raises 403 for disallowed roles.
    """
    async def _checker(claims: TokenClaims = Depends(get_current_user)) -> TokenClaims:
        if claims.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this resource.",
            )
        return claims

    return _checker
```

> **Note:** If `require_roles` already exists from US-061/TASK-002, skip this step and import from the existing module.

### 4. Register the router in `api-gateway/app/main.py`

```python
# In api-gateway/app/main.py — add alongside existing analytics router

from app.routers.analytics_export import router as analytics_export_router

app.include_router(analytics_export_router, prefix="/api/v1")
```

### 5. Create export package init files

```bash
mkdir -p api-gateway/app/export
touch api-gateway/app/export/__init__.py
touch api-gateway/app/export/csv_exporter.py   # populated in TASK-002
touch api-gateway/app/export/pdf_exporter.py   # populated in TASK-004
touch api-gateway/app/export/chart_renderer.py # populated in TASK-003
```

---

## Validation Checklist

- [ ] `GET /api/v1/analytics/export?format=csv&from=2026-01-01&to=2026-01-31` with `MANAGER` JWT → `200 OK`
- [ ] `GET /api/v1/analytics/export?format=csv&from=2026-01-01&to=2026-01-31` with `NURSE` JWT → `403 Forbidden`
- [ ] `GET /api/v1/analytics/export?format=pdf&from=2026-01-01&to=2026-01-31` with `ADMIN` JWT → `202 Accepted`
- [ ] `?from=2026-02-01&to=2026-01-01` → `400 Bad Request` (from after to)
- [ ] `?format=xml` → `422 Unprocessable Entity` (invalid enum value)
- [ ] Date range of 367 days → `400 Bad Request`
- [ ] Router appears in OpenAPI spec at `/api/v1/analytics/export`
- [ ] `app/export/` package directory created with stub files for TASK-002, TASK-003, TASK-004
