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
    """Base for analytics read-only models."""

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
