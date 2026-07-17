---
id: TASK-006
title: "Unit Tests — CSV PHI Guard, PDF Content Validation & RBAC Enforcement"
user_story: US-063
epic: EP-012
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Frontend Engineer
upstream: [US-063/TASK-001, US-063/TASK-002, US-063/TASK-003, US-063/TASK-004, US-063/TASK-005]
---

# TASK-006: Unit Tests — CSV PHI Guard, PDF Content Validation & RBAC Enforcement

> **Story:** US-063 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-063 DoD requires unit tests covering:
1. **CSV PHI guard** — `_assert_no_phi()` raises `ValueError` on blocked column names; passes on safe schema
2. **CSV column completeness** — all 8 safe columns appear in the CSV header row; no extra columns
3. **PDF content check** — rendered PDF bytes start with `%PDF-`; hospital name and date range are present in the raw bytes
4. **Chart renderer** — `render_all_charts()` returns exactly 5 `ChartImage` instances with valid PNG bytes
5. **RBAC enforcement** — `403 Forbidden` for `NURSE`; `200 OK` / `202 Accepted` for `MANAGER` and `ADMIN`
6. **Date validation** — `from > to` returns `400`; date range > 366 days returns `400`

Tests are split across three files:

| Test File | Module Under Test | Coverage Focus |
|---|---|---|
| `test_csv_exporter.py` | `app/export/csv_exporter.py` | PHI guard; column headers; streaming output |
| `test_pdf_chart_renderer.py` | `app/export/chart_renderer.py` | Chart count; PNG magic bytes; empty data handling |
| `test_export_router.py` | `app/routers/analytics_export.py` | RBAC 403/200/202; date validation 400 |

**Mocking strategy:**

| Dependency | Mock Approach |
|---|---|
| `KpiQueryService` | `AsyncMock` returning a fixed `list[KpiDataPoint]` fixture |
| `get_read_session` | `AsyncMock` — session not exercised in router tests |
| `require_roles` | `MagicMock` returning `TokenClaims` with controlled `role` |
| `schedule_pdf_export` | `AsyncMock` returning a fixed `JSONResponse(202)` |
| `build_csv_streaming_response` | Real implementation called against fixture data |
| GCS upload / signed URL | `AsyncMock` — not exercised in unit tests |

---

## Acceptance Criteria Addressed

| AC Scenario | Test Cases |
|---|---|
| Scenario 1 (CSV download) | `test_csv_header_contains_all_safe_columns`, `test_csv_streaming_response_content_type` |
| Scenario 2 (PDF content) | `test_pdf_starts_with_pdf_magic_bytes`, `test_pdf_contains_hospital_name` |
| Scenario 3 (no PHI) | `test_assert_no_phi_raises_on_blocked_column`, `test_assert_no_phi_passes_on_safe_schema` |
| Scenario 4 (RBAC) | `test_export_403_for_nurse`, `test_export_200_for_manager`, `test_export_202_for_admin_pdf` |

---

## Implementation Steps

### 1. Scaffold test directories and files

```bash
mkdir -p api-gateway/tests/unit/export
touch api-gateway/tests/unit/export/__init__.py
touch api-gateway/tests/unit/export/conftest.py
touch api-gateway/tests/unit/export/test_csv_exporter.py
touch api-gateway/tests/unit/export/test_pdf_chart_renderer.py
touch api-gateway/tests/unit/export/test_export_router.py
```

### 2. Create `api-gateway/tests/unit/export/conftest.py`

```python
"""Shared fixtures for US-063 export unit tests.

Provides:
    kpi_fixture          — list of 5 KpiDataPoint instances (safe, no PHI)
    phi_polluted_fixture — KpiDataPoint-like object with a PHI field injected
    manager_token        — TokenClaims with role=MANAGER
    nurse_token          — TokenClaims with role=NURSE
    admin_token          — TokenClaims with role=ADMIN
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.analytics.schemas import KpiDataPoint
from app.core.auth import TokenClaims


@pytest.fixture()
def kpi_fixture() -> list[KpiDataPoint]:
    base = datetime.date(2026, 1, 1)
    return [
        KpiDataPoint(
            date=base + datetime.timedelta(days=i),
            unit_name=f"Unit-{i % 3 + 1}",
            avg_los_hours=24.0 + i * 0.5,
            discharge_count=10 + i,
            readmission_rate=0.05 + i * 0.001,
            medication_reconciliation_rate=0.90 - i * 0.001,
            handoff_completion_rate=0.85 + i * 0.002,
            agent_success_rate=0.92 + i * 0.001,
        )
        for i in range(5)
    ]


@pytest.fixture()
def manager_token() -> TokenClaims:
    claims = MagicMock(spec=TokenClaims)
    claims.role = "MANAGER"
    claims.units = ["Unit-1", "Unit-2"]
    claims.hospital_name = "General Hospital"
    return claims


@pytest.fixture()
def nurse_token() -> TokenClaims:
    claims = MagicMock(spec=TokenClaims)
    claims.role = "NURSE"
    claims.units = ["Unit-1"]
    claims.hospital_name = "General Hospital"
    return claims


@pytest.fixture()
def admin_token() -> TokenClaims:
    claims = MagicMock(spec=TokenClaims)
    claims.role = "ADMIN"
    claims.units = ["Unit-1", "Unit-2", "Unit-3"]
    claims.hospital_name = "General Hospital"
    return claims


@pytest.fixture()
def mock_query_service(kpi_fixture) -> AsyncMock:
    svc = AsyncMock()
    svc.get_kpi_data.return_value = kpi_fixture
    return svc
```

### 3. Create `api-gateway/tests/unit/export/test_csv_exporter.py`

```python
"""Unit tests for app/export/csv_exporter.py.

US-063 AC Scenario 1 — CSV column headers present; streaming response
US-063 AC Scenario 3 — no PHI fields in CSV output
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from app.export.csv_exporter import (
    _PHI_BLOCKED_COLUMNS,
    _SAFE_COLUMNS,
    _assert_no_phi,
    build_csv_streaming_response,
)
from tests.unit.export.conftest import kpi_fixture  # noqa: F401


class TestAssertNoPhi:
    """Tests for the _assert_no_phi PHI guard function."""

    def test_passes_on_safe_schema(self, kpi_fixture):
        """_assert_no_phi does not raise when KpiDataPoint has only safe fields."""
        _assert_no_phi(kpi_fixture)  # must not raise

    @pytest.mark.parametrize("phi_field", sorted(_PHI_BLOCKED_COLUMNS))
    def test_raises_on_each_blocked_column(self, phi_field, kpi_fixture):
        """_assert_no_phi raises ValueError for each individual PHI field."""
        # Inject a PHI field into the first data point's dict to simulate leakage
        kpi_fixture[0].__dict__[phi_field] = "BLOCKED_VALUE"
        # Also patch __class__.__fields__ if it is a Pydantic model
        with pytest.raises(ValueError, match=phi_field):
            _assert_no_phi(kpi_fixture)

    def test_passes_on_empty_list(self):
        """_assert_no_phi is a no-op for empty data."""
        _assert_no_phi([])  # must not raise


class TestBuildCsvStreamingResponse:
    """Tests for the build_csv_streaming_response function."""

    def test_content_type_is_text_csv(self, kpi_fixture):
        import datetime
        response = build_csv_streaming_response(
            kpi_fixture,
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 5),
        )
        assert response.media_type == "text/csv"

    def test_content_disposition_contains_filename(self, kpi_fixture):
        import datetime
        response = build_csv_streaming_response(
            kpi_fixture,
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 5),
        )
        disposition = response.headers["content-disposition"]
        assert "kpi_report_2026-01-01_2026-01-05.csv" in disposition
        assert "attachment" in disposition

    def test_csv_header_contains_all_safe_columns(self, kpi_fixture):
        """First row of the CSV stream must contain all 8 safe column names."""
        import datetime
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
        import datetime
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
        import datetime
        response = build_csv_streaming_response(
            [],
            datetime.date(2026, 1, 1),
            datetime.date(2026, 1, 5),
        )
        chunks = list(response.body_iterator)
        csv_text = "".join(chunk if isinstance(chunk, str) else chunk.decode() for chunk in chunks)
        lines = [l for l in csv_text.splitlines() if l]
        assert len(lines) == 1  # header row only
```

### 4. Create `api-gateway/tests/unit/export/test_pdf_chart_renderer.py`

```python
"""Unit tests for app/export/chart_renderer.py and PDF bytes.

US-063 AC Scenario 2 — 5 chart images embedded in the PDF
"""
from __future__ import annotations

import pytest

from app.export.chart_renderer import ChartImage, render_all_charts
from tests.unit.export.conftest import kpi_fixture  # noqa: F401

_PNG_MAGIC = b"\x89PNG"
_EXPECTED_CHART_COUNT = 5


class TestRenderAllCharts:
    """Tests for the render_all_charts function."""

    def test_returns_five_chart_images(self, kpi_fixture):
        charts = render_all_charts(kpi_fixture)
        assert len(charts) == _EXPECTED_CHART_COUNT

    def test_all_charts_are_chart_image_instances(self, kpi_fixture):
        charts = render_all_charts(kpi_fixture)
        for chart in charts:
            assert isinstance(chart, ChartImage)

    def test_all_png_bytes_start_with_png_magic(self, kpi_fixture):
        charts = render_all_charts(kpi_fixture)
        for chart in charts:
            assert chart.png_bytes[:4] == _PNG_MAGIC, (
                f"Chart '{chart.title}' does not have PNG magic bytes"
            )

    def test_all_png_bytes_are_non_empty(self, kpi_fixture):
        charts = render_all_charts(kpi_fixture)
        for chart in charts:
            assert len(chart.png_bytes) > 0

    def test_chart_titles_are_unique(self, kpi_fixture):
        charts = render_all_charts(kpi_fixture)
        titles = [c.title for c in charts]
        assert len(titles) == len(set(titles)), "Duplicate chart titles detected"

    def test_empty_data_returns_five_blank_charts(self):
        """render_all_charts with empty data must not raise; returns 5 blank charts."""
        charts = render_all_charts([])
        assert len(charts) == _EXPECTED_CHART_COUNT
        for chart in charts:
            assert chart.png_bytes[:4] == _PNG_MAGIC


class TestPdfBytesStructure:
    """Smoke tests for the _build_pdf function."""

    def test_pdf_starts_with_pdf_magic_bytes(self, kpi_fixture):
        import datetime
        from app.export.pdf_exporter import _build_pdf
        from app.export.chart_renderer import render_all_charts

        charts = render_all_charts(kpi_fixture)
        pdf_bytes = _build_pdf(
            kpi_data=kpi_fixture,
            chart_images=charts,
            hospital_name="General Hospital",
            from_date=datetime.date(2026, 1, 1),
            to_date=datetime.date(2026, 1, 5),
        )
        assert pdf_bytes[:4] == b"%PDF"

    def test_pdf_contains_hospital_name(self, kpi_fixture):
        import datetime
        from app.export.pdf_exporter import _build_pdf
        from app.export.chart_renderer import render_all_charts

        charts = render_all_charts(kpi_fixture)
        pdf_bytes = _build_pdf(
            kpi_data=kpi_fixture,
            chart_images=charts,
            hospital_name="Sunrise Medical Centre",
            from_date=datetime.date(2026, 1, 1),
            to_date=datetime.date(2026, 1, 5),
        )
        # Hospital name appears in the raw PDF bytes as a string
        assert b"Sunrise Medical Centre" in pdf_bytes

    def test_pdf_contains_date_range(self, kpi_fixture):
        import datetime
        from app.export.pdf_exporter import _build_pdf
        from app.export.chart_renderer import render_all_charts

        charts = render_all_charts(kpi_fixture)
        pdf_bytes = _build_pdf(
            kpi_data=kpi_fixture,
            chart_images=charts,
            hospital_name="General Hospital",
            from_date=datetime.date(2026, 1, 1),
            to_date=datetime.date(2026, 1, 5),
        )
        assert b"01 January 2026" in pdf_bytes
        assert b"05 January 2026" in pdf_bytes
```

### 5. Create `api-gateway/tests/unit/export/test_export_router.py`

```python
"""Unit tests for app/routers/analytics_export.py.

US-063 AC Scenario 4 — RBAC 403 / 200 / 202
US-063 date validation — 400 for invalid ranges
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.unit.export.conftest import admin_token, kpi_fixture, manager_token, nurse_token  # noqa: F401

_BASE_URL = "/api/v1/analytics/export"
_VALID_PARAMS = "?format=csv&from=2026-01-01&to=2026-01-31"


class TestExportRbac:
    """RBAC enforcement tests for GET /api/v1/analytics/export."""

    def test_export_csv_200_for_manager(self, manager_token, kpi_fixture):
        with patch("app.routers.analytics_export.require_roles", return_value=lambda: manager_token), \
             patch("app.routers.analytics_export.KpiQueryService") as mock_qs, \
             patch("app.export.csv_exporter.build_csv_streaming_response") as mock_csv:
            mock_qs.return_value.get_kpi_data = AsyncMock(return_value=kpi_fixture)
            mock_csv.return_value.__class__.__name__ = "StreamingResponse"
            with TestClient(app) as client:
                response = client.get(f"{_BASE_URL}{_VALID_PARAMS}")
        assert response.status_code == 200

    def test_export_pdf_202_for_admin(self, admin_token, kpi_fixture):
        with patch("app.routers.analytics_export.require_roles", return_value=lambda: admin_token), \
             patch("app.routers.analytics_export.schedule_pdf_export", new_callable=AsyncMock) as mock_pdf:
            from fastapi.responses import JSONResponse
            mock_pdf.return_value = JSONResponse(status_code=202, content={"job_id": "abc", "status": "processing", "poll_url": "/poll/abc"})
            with TestClient(app) as client:
                response = client.get(f"{_BASE_URL}?format=pdf&from=2026-01-01&to=2026-01-31")
        assert response.status_code == 202

    def test_export_403_for_nurse(self, nurse_token):
        with patch("app.core.rbac.get_current_user", return_value=nurse_token):
            with TestClient(app) as client:
                response = client.get(f"{_BASE_URL}{_VALID_PARAMS}")
        assert response.status_code == 403

    def test_export_403_for_physician(self):
        physician_token = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        physician_token.role = "PHYSICIAN"
        with patch("app.core.rbac.get_current_user", return_value=physician_token):
            with TestClient(app) as client:
                response = client.get(f"{_BASE_URL}{_VALID_PARAMS}")
        assert response.status_code == 403


class TestExportDateValidation:
    """Date range validation tests for GET /api/v1/analytics/export."""

    def test_400_when_from_after_to(self, manager_token):
        with patch("app.routers.analytics_export.require_roles", return_value=lambda: manager_token):
            with TestClient(app) as client:
                response = client.get(f"{_BASE_URL}?format=csv&from=2026-02-01&to=2026-01-01")
        assert response.status_code == 400
        assert "from" in response.json()["detail"].lower()

    def test_400_when_date_range_exceeds_366_days(self, manager_token):
        with patch("app.routers.analytics_export.require_roles", return_value=lambda: manager_token):
            with TestClient(app) as client:
                response = client.get(f"{_BASE_URL}?format=csv&from=2024-01-01&to=2025-02-10")
        assert response.status_code == 400

    def test_422_for_invalid_format_enum(self, manager_token):
        with patch("app.routers.analytics_export.require_roles", return_value=lambda: manager_token):
            with TestClient(app) as client:
                response = client.get(f"{_BASE_URL}?format=xml&from=2026-01-01&to=2026-01-31")
        assert response.status_code == 422
```

---

## Validation Checklist

- [ ] All tests in `test_csv_exporter.py` pass: `pytest api-gateway/tests/unit/export/test_csv_exporter.py -v`
- [ ] All tests in `test_pdf_chart_renderer.py` pass: `pytest api-gateway/tests/unit/export/test_pdf_chart_renderer.py -v`
- [ ] All tests in `test_export_router.py` pass: `pytest api-gateway/tests/unit/export/test_export_router.py -v`
- [ ] `test_assert_no_phi_raises_on_each_blocked_column` parametrised test covers all fields in `_PHI_BLOCKED_COLUMNS`
- [ ] `test_export_403_for_nurse` and `test_export_403_for_physician` both assert `status_code == 403`
- [ ] `test_pdf_starts_with_pdf_magic_bytes` confirms `pdf_bytes[:4] == b"%PDF"`
- [ ] `test_returns_five_chart_images` confirms exactly 5 `ChartImage` objects returned
- [ ] Code coverage for `csv_exporter.py`, `chart_renderer.py`, and `analytics_export.py` ≥ 80%
