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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.query_service import KpiQueryService
from app.analytics.schemas import KpiResponse
from app.core.auth.jwt import TokenClaims, get_current_user
from app.db.deps import get_read_db

router = APIRouter(prefix="/analytics", tags=["analytics"])

_PERMITTED_ROLES = {"MANAGER", "ADMIN"}
_DEFAULT_RANGE_DAYS = 30


def _require_roles(permitted_roles: set[str]) -> callable:
    """Factory: return a dependency that validates role membership."""

    async def _check(current_user: Annotated[TokenClaims, Depends(get_current_user)]) -> TokenClaims:
        if current_user.role.upper() not in permitted_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not authorised to access this resource. "
                       f"Required: {sorted(permitted_roles)}",
            )
        return current_user

    return _check


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
    from_date: Annotated[datetime.date | None, Query(
        default=None,
        alias="from",
        description="Inclusive start date (ISO 8601). Defaults to today minus 30 days.",
    )] = None,
    to_date: Annotated[datetime.date | None, Query(
        default=None,
        alias="to",
        description="Inclusive end date (ISO 8601). Defaults to today.",
    )] = None,
    unit: Annotated[str | None, Query(
        default=None,
        description="Filter results to a single unit. Omit to include all accessible units.",
        max_length=100,
    )] = None,
    current_user: Annotated[TokenClaims, Depends(_require_roles(_PERMITTED_ROLES))] = None,
    read_session: Annotated[AsyncSession, Depends(get_read_db)] = None,
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
