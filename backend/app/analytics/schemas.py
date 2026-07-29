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
