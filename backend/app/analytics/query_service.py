"""Query service for KPI analytics — reads exclusively from the read replica.

All methods in this service use the read-replica AsyncSession.
No write operations are permitted here.

Design refs:
    design.md ADR-006 — CQRS read/write session routing
    design.md TR-010 — 100% of dashboard GET requests routed to read replica
    US-061 Technical Notes — mv_kpi_daily columns
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.models import KpiDailyView
from app.analytics.schemas import KpiDataPoint, KpiResponse


class KpiQueryService:
    """Encapsulates all read-replica queries for the KPI analytics endpoint.

    Inject the read-replica AsyncSession — never the write session.
    """

    def __init__(self, read_session: AsyncSession) -> None:
        self._session = read_session

    async def get_kpis(
        self,
        from_date: datetime.date,
        to_date: datetime.date,
        unit: str | None,
        accessible_units: list[str],
    ) -> KpiResponse:
        """Return aggregated KPI data points filtered by date range and unit.

        Args:
            from_date: Inclusive start date for the query window.
            to_date: Inclusive end date for the query window.
            unit: Optional unit filter. If None, returns all accessible_units.
            accessible_units: Units the requesting manager is permitted to view
                              (derived from app_user.units — enforced upstream in RBAC).

        Returns:
            KpiResponse with de-identified aggregated data points.
        """
        stmt = (
            select(KpiDailyView)
            .where(KpiDailyView.date >= from_date)
            .where(KpiDailyView.date <= to_date)
            .where(KpiDailyView.unit.in_(accessible_units))
            .order_by(KpiDailyView.date.asc(), KpiDailyView.unit.asc())
        )

        if unit is not None:
            stmt = stmt.where(KpiDailyView.unit == unit)

        result = await self._session.execute(stmt)
        rows = result.scalars().all()

        data_points = [KpiDataPoint.model_validate(row) for row in rows]

        return KpiResponse(
            from_date=from_date,
            to_date=to_date,
            unit=unit,
            data=data_points,
            total_rows=len(data_points),
        )
