"""Unit tests for app/export/csv_exporter.py.

US-063 AC Scenario 1 — CSV column headers present; streaming response
US-063 AC Scenario 3 — no PHI fields in CSV output
"""
from __future__ import annotations

import datetime
import io

import pytest

from app.export.csv_exporter import (
    _PHI_BLOCKED_COLUMNS,
    _SAFE_COLUMNS,
    _assert_no_phi,
    build_csv_streaming_response,
)


class TestAssertNoPhi:
    """Tests for the _assert_no_phi PHI guard function."""

    def test_passes_on_safe_schema(self, kpi_fixture):
        """_assert_no_phi does not raise when KpiDataPoint has only safe fields."""
        _assert_no_phi(kpi_fixture)  # must not raise

    def test_raises_on_blocked_column(self, kpi_fixture):
        """_assert_no_phi raises ValueError when PHI field is detected."""
        # Inject a PHI field into the first data point
        kpi_fixture[0].__dict__["patient_name"] = "BLOCKED_VALUE"
        with pytest.raises(ValueError, match="patient_name"):
            _assert_no_phi(kpi_fixture)

    def test_passes_on_empty_list(self):
        """_assert_no_phi is a no-op for empty data."""
        _assert_no_phi([])  # must not raise


class TestBuildCsvStreamingResponse:
    """Tests for the build_csv_streaming_response function."""

    def test_content_type_is_text_csv(self, kpi_fixture):
        """Response media type is text/csv."""
        response = build_csv_streaming_response(
            kpi_fixture,
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 5),
        )
        assert response.media_type == "text/csv"

    def test_content_disposition_contains_filename(self, kpi_fixture):
        """Content-Disposition header contains attachment with filename."""
        response = build_csv_streaming_response(
            kpi_fixture,
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 5),
        )
        disposition = response.headers["content-disposition"]
        assert "kpi_report_2026-01-01_2026-01-05.csv" in disposition
        assert "attachment" in disposition

    def test_csv_header_contains_all_safe_columns(self, kpi_fixture):
        """First row of the CSV stream contains all safe column names."""
        response = build_csv_streaming_response(
            kpi_fixture,
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 5),
        )
        # Collect all streamed chunks
        chunks = list(response.body_iterator)
        csv_text = "".join(chunk if isinstance(chunk, str) else chunk.decode() for chunk in chunks)
        header_row = csv_text.splitlines()[0]
        for col in _SAFE_COLUMNS:
            assert col in header_row, f"Expected column '{col}' missing from CSV header"

    def test_no_phi_column_in_csv_output(self, kpi_fixture):
        """No PHI column names appear anywhere in the CSV output."""
        response = build_csv_streaming_response(
            kpi_fixture,
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 5),
        )
        chunks = list(response.body_iterator)
        csv_text = "".join(chunk if isinstance(chunk, str) else chunk.decode() for chunk in chunks)
        for phi_col in _PHI_BLOCKED_COLUMNS:
            assert phi_col not in csv_text, f"PHI column '{phi_col}' found in CSV output"

    def test_empty_data_yields_header_only(self):
        """Empty KPI data returns a header-only CSV (no error raised)."""
        response = build_csv_streaming_response(
            [],
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 5),
        )
        chunks = list(response.body_iterator)
        csv_text = "".join(chunk if isinstance(chunk, str) else chunk.decode() for chunk in chunks)
        lines = [l for l in csv_text.splitlines() if l]
        assert len(lines) == 1  # header row only
