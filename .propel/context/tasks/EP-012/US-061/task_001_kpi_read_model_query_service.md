---
id: TASK-001
title: "KPI Read Model — Pydantic Schemas & SQLAlchemy Read-Replica Query Service"
user_story: US-061
epic: EP-012
sprint: 2
layer: Backend / Data
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-061, US-009, DR-007, TR-010]
---

# TASK-001: KPI Read Model — Pydantic Schemas & SQLAlchemy Read-Replica Query Service

> **Story:** US-061 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-061 requires a `GET /api/v1/analytics/kpis` endpoint that queries the `mv_kpi_daily` materialised view on the read replica and returns only de-identified aggregated metrics (no PHI). Before the router is built (TASK-002), this task establishes:

- The SQLAlchemy ORM/Core mapped class for `mv_kpi_daily` (read-only, no migrations needed — view provisioned by US-009)
- The Pydantic response schemas (no PHI fields)
- The `KpiQueryService` that encapsulates all read-replica query logic, date-range filtering, and unit scoping

**Design references:**
- design.md §3.3 — FastAPI backend structure; read API routes to read replica
- design.md §4.1 — SQLAlchemy 2.x async; read/write session routing (TR-010)
- design.md §6.1 ADR-006 — CQRS: dashboard queries use read replica + materialised views
- design.md §8.3 — PHI containment: API response contains only aggregated metrics
- US-061 Technical Notes — `mv_kpi_daily` columns: `date`, `unit`, `avg_discharge_doc_time_min`, `readmission_rate_30d`, `med_recon_completion_rate`, `bed_utilisation_pct`, `agent_task_success_rate`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Query service fetches correct aggregated values from `mv_kpi_daily` for a 30-day window |
| Scenario 3 | Pydantic response schema exposes zero PHI fields — no encounter IDs, MRNs, names, or DOBs |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p api-gateway/app/analytics
touch api-gateway/app/analytics/__init__.py
touch api-gateway/app/analytics/models.py
touch api-gateway/app/analytics/schemas.py
touch api-gateway/app/analytics/query_service.py
```

### 2. Define SQLAlchemy mapped class in `api-gateway/app/analytics/models.py`

```python
"""SQLAlchemy mapped class for the mv_kpi_daily materialised view.

This is a read-only mapping — no migrations are generated from this class.
The view is provisioned by US-009/TASK-XXX.

Design refs:
    design.md §4.1 — SQLAlchemy 2.x async
    design.md ADR-006 — read replica for dashboard queries
    US-061 Technical Notes — mv_kpi_daily column definitions
"""
from __future__ import annotations

import datetime

from sqlalchemy import Date, Float, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AnalyticsBase(DeclarativeBase):
    pass


class KpiDailyView(AnalyticsBase):
    """Read-only ORM mapping for the mv_kpi_daily materialised view.

    Never instantiated for writes — used exclusively for SELECT queries
    routed to the read replica session.
    """

    __tablename__ = "mv_kpi_daily"
    __table_args__ = {"info": {"read_only": True}}

    # Composite primary key: date + unit uniquely identify each row in the view
    date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    unit: Mapped[str] = mapped_column(String(100), primary_key=True)

    # Aggregated KPI metrics — no PHI columns present in this view
    avg_discharge_doc_time_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    readmission_rate_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    med_recon_completion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    bed_utilisation_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    agent_task_success_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
```

### 3. Define Pydantic response schemas in `api-gateway/app/analytics/schemas.py`

```python
"""Pydantic schemas for the KPI analytics API.

IMPORTANT — PHI guardrail:
    These schemas intentionally contain ONLY aggregated metrics.
    No encounter IDs, patient names, MRNs, DOBs, or any individually
    identifiable information may be added here.
    See US-061 AC Scenario 3 and design.md §8.3.

Design refs:
    US-061 AC Scenario 3 — de-identified aggregated response
    design.md §3.3 — FastAPI backend structure
"""
from __future__ import annotations

import datetime

from pydantic import BaseModel, Field


class KpiDataPoint(BaseModel):
    """A single aggregated KPI data point for one date/unit combination.

    All fields are aggregated metrics only — no PHI is present.
    """

    date: datetime.date
    unit: str
    avg_discharge_doc_time_min: float | None = Field(
        None,
        description="Average time (minutes) from encounter creation to discharge documentation completion",
        ge=0,
    )
    readmission_rate_30d: float | None = Field(
        None,
        description="30-day readmission rate as a proportion (0.0–1.0)",
        ge=0.0,
        le=1.0,
    )
    med_recon_completion_rate: float | None = Field(
        None,
        description="Medication reconciliation completion rate as a proportion (0.0–1.0)",
        ge=0.0,
        le=1.0,
    )
    bed_utilisation_pct: float | None = Field(
        None,
        description="Bed utilisation percentage (0.0–100.0)",
        ge=0.0,
        le=100.0,
    )
    agent_task_success_rate: float | None = Field(
        None,
        description="AI agent task success rate as a proportion (0.0–1.0)",
        ge=0.0,
        le=1.0,
    )

    model_config = {"from_attributes": True}


class KpiResponse(BaseModel):
    """Top-level response envelope for GET /api/v1/analytics/kpis.

    Contains only aggregated, de-identified metrics.
    from_date and to_date echo the filter applied so clients can
    verify the effective range.
    """

    from_date: datetime.date
    to_date: datetime.date
    unit: str | None = Field(None, description="Unit filter applied; null means all accessible units")
    data: list[KpiDataPoint] = Field(default_factory=list)
    total_rows: int = Field(0, description="Total data points returned")
```

### 4. Implement `KpiQueryService` in `api-gateway/app/analytics/query_service.py`

```python
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
```

### 5. Register `AnalyticsBase` metadata with Alembic env

No migration is needed — `mv_kpi_daily` is a materialised view provisioned by US-009. However, to prevent Alembic from detecting the mapped class as an unmanaged table, add the `__table_args__` skip annotation:

In `api-gateway/alembic/env.py`, ensure the `AnalyticsBase` metadata is excluded from the autogenerate target metadata list:

```python
# In env.py — only include writable model metadata in autogenerate
from app.models import Base as WriteBase
# Do NOT include AnalyticsBase from app.analytics.models — read-only view
target_metadata = WriteBase.metadata
```

---

## Validation Checklist

- [ ] `KpiDailyView` maps all 7 columns of `mv_kpi_daily` with correct Python types
- [ ] `KpiDataPoint` contains no PHI fields; fields validated with `ge`/`le` bounds
- [ ] `KpiResponse` echoes `from_date`, `to_date`, `unit` for client-side verification
- [ ] `KpiQueryService.get_kpis()` filters by `accessible_units` in all code paths (no bypass)
- [ ] `KpiQueryService` accepts only read-replica `AsyncSession` (enforced by dependency injection in TASK-002)
- [ ] `AnalyticsBase` excluded from Alembic autogenerate target metadata
- [ ] All files pass `mypy --strict` with no errors

---

## Files Created / Modified

| File | Action |
|------|--------|
| `api-gateway/app/analytics/__init__.py` | Create |
| `api-gateway/app/analytics/models.py` | Create |
| `api-gateway/app/analytics/schemas.py` | Create |
| `api-gateway/app/analytics/query_service.py` | Create |
| `api-gateway/alembic/env.py` | Modify — exclude `AnalyticsBase` from autogenerate |
