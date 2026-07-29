"""Unit tests verifying the KPI analytics Pydantic schemas contain no PHI.

US-061 AC Scenario 3:
    KpiResponse and KpiDataPoint must not expose patient names, MRNs, DOBs,
    encounter IDs, or any individually identifiable information.

These tests introspect the schema field names to enforce the PHI guardrail
at the schema definition level — preventing accidental field additions.
"""
from __future__ import annotations

import datetime

import pytest

from app.analytics.schemas import KpiDataPoint, KpiResponse

# Exhaustive list of PHI field name patterns that must never appear
_PHI_FIELD_PATTERNS: list[str] = [
    "patient",
    "mrn",
    "dob",
    "birth",
    "name",
    "first_name",
    "last_name",
    "encounter_id",
    "encounter",
    "phone",
    "email",
    "address",
    "ssn",
    "social_security",
]


class TestKpiDataPointSchema:
    def test_kpi_data_point_contains_no_phi_fields(self) -> None:
        """No field in KpiDataPoint may carry PHI — enforced by field name inspection."""
        field_names = [f.lower() for f in KpiDataPoint.model_fields]
        for phi_pattern in _PHI_FIELD_PATTERNS:
            matching = [f for f in field_names if phi_pattern in f]
            assert not matching, (
                f"PHI-related field detected in KpiDataPoint: {matching} "
                f"(pattern: '{phi_pattern}'). Remove or rename."
            )

    def test_kpi_data_point_expected_fields_present(self) -> None:
        """All five KPI metric fields plus date/unit must be present."""
        expected = {
            "date",
            "unit",
            "avg_discharge_doc_time_min",
            "readmission_rate_30d",
            "med_recon_completion_rate",
            "bed_utilisation_pct",
            "agent_task_success_rate",
        }
        assert expected.issubset(set(KpiDataPoint.model_fields.keys()))

    def test_kpi_data_point_accepts_null_metrics(self) -> None:
        """All metric fields are Optional — null values from the view must be accepted."""
        point = KpiDataPoint(date=datetime.date(2026, 7, 1), unit="ICU")
        assert point.avg_discharge_doc_time_min is None
        assert point.readmission_rate_30d is None
        assert point.med_recon_completion_rate is None
        assert point.bed_utilisation_pct is None
        assert point.agent_task_success_rate is None

    def test_readmission_rate_bounds_validation(self) -> None:
        """readmission_rate_30d must be in range 0.0–1.0."""
        with pytest.raises(Exception):
            KpiDataPoint(
                date=datetime.date(2026, 7, 1), unit="ICU", readmission_rate_30d=1.5
            )

    def test_bed_utilisation_pct_bounds_validation(self) -> None:
        """bed_utilisation_pct must be in range 0.0–100.0."""
        with pytest.raises(Exception):
            KpiDataPoint(date=datetime.date(2026, 7, 1), unit="ICU", bed_utilisation_pct=101.0)


class TestKpiResponseSchema:
    def test_kpi_response_contains_no_phi_fields(self) -> None:
        """No field in KpiResponse may carry PHI — enforced by field name inspection."""
        field_names = [f.lower() for f in KpiResponse.model_fields]
        for phi_pattern in _PHI_FIELD_PATTERNS:
            matching = [f for f in field_names if phi_pattern in f]
            assert not matching, (
                f"PHI-related field detected in KpiResponse: {matching} "
                f"(pattern: '{phi_pattern}')"
            )

    def test_kpi_response_echoes_filter_params(self) -> None:
        """from_date, to_date, unit must be present for client-side verification."""
        response = KpiResponse(
            from_date=datetime.date(2026, 6, 17),
            to_date=datetime.date(2026, 7, 17),
            data=[],
            total_rows=0,
        )
        assert response.from_date == datetime.date(2026, 6, 17)
        assert response.to_date == datetime.date(2026, 7, 17)
        assert response.unit is None
        assert response.total_rows == 0
