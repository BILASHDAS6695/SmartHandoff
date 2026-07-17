---
id: TASK-006
title: "Unit Tests — KPI API De-identification, RBAC Enforcement & Chart Data Mapping"
user_story: US-061
epic: EP-012
sprint: 2
layer: Testing
estimate: 3h
priority: Must Heat
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Frontend Engineer
upstream: [US-061/TASK-001, US-061/TASK-002, US-061/TASK-003, US-061/TASK-004, US-061/TASK-005]
---

# TASK-006: Unit Tests — KPI API De-identification, RBAC Enforcement & Chart Data Mapping

> **Story:** US-061 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-061 DoD requires unit tests covering:
1. **API de-identification** — the `KpiResponse` schema contains zero PHI fields at all code paths
2. **RBAC enforcement** — `403 Forbidden` for disallowed roles; `200 OK` for `MANAGER` and `ADMIN`
3. **Date range default logic** — missing `from`/`to` params yield correct 30-day default window
4. **Chart data mapping utilities** — `toSingleSeriesData`, `toDateLabels`, `toAgentSuccessDatasets` transform `KpiDataPoint[]` correctly

Tests are split across three files matching the production modules:

| Test File | Module Under Test | Coverage Focus |
|---|---|---|
| `test_analytics_schemas.py` | `app/analytics/schemas.py` | PHI field absence on all schema variants |
| `test_analytics_router.py` | `app/routers/analytics.py` | RBAC 403/200; default date range; `from > to` 400 |
| `chart.utils.spec.ts` | `analytics/charts/chart.utils.ts` | Data transformation correctness; null handling |

**Mocking strategy:**

| Dependency | Mock Approach |
|---|---|
| `KpiQueryService` (FastAPI tests) | `AsyncMock` returning a fixed `KpiResponse` fixture |
| `get_read_session` (FastAPI tests) | `AsyncMock` — session not exercised in router tests |
| `get_current_user` (FastAPI tests) | `MagicMock` returning `TokenClaims` with controlled `role` and `units` |
| `KpiDataPoint[]` (Angular tests) | Static fixture arrays defined inline in each `describe` block |

---

## Acceptance Criteria Addressed

| AC Scenario | Test Cases |
|---|---|
| Scenario 3 (no PHI) | `test_kpi_response_contains_no_phi_fields`, `test_kpi_data_point_contains_no_phi_fields` |
| Scenario 4 (RBAC) | `test_get_kpis_200_for_manager`, `test_get_kpis_200_for_admin`, `test_get_kpis_403_for_nurse`, `test_get_kpis_403_for_physician`, `test_get_kpis_403_for_pharmacist` |
| Scenario 1 (defaults) | `test_get_kpis_defaults_to_30_day_range` |
| Scenario 2 (filter) | `test_get_kpis_respects_from_to_params`, `test_get_kpis_400_when_from_after_to` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p api-gateway/tests/unit/analytics
touch api-gateway/tests/unit/analytics/__init__.py
touch api-gateway/tests/unit/analytics/test_analytics_schemas.py
touch api-gateway/tests/unit/analytics/test_analytics_router.py
mkdir -p smarthandoff-angular/src/app/features/analytics/charts
touch smarthandoff-angular/src/app/features/analytics/charts/chart.utils.spec.ts
```

### 2. Create `api-gateway/tests/unit/analytics/test_analytics_schemas.py`

```python
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
    "patient", "mrn", "dob", "birth", "name", "first_name", "last_name",
    "encounter_id", "encounter", "phone", "email", "address", "ssn",
    "social_security",
]


class TestKpiDataPointSchema:
    def test_kpi_data_point_contains_no_phi_fields(self):
        """No field in KpiDataPoint may carry PHI — enforced by field name inspection."""
        field_names = [f.lower() for f in KpiDataPoint.model_fields]
        for phi_pattern in _PHI_FIELD_PATTERNS:
            matching = [f for f in field_names if phi_pattern in f]
            assert not matching, (
                f"PHI-related field detected in KpiDataPoint: {matching} "
                f"(pattern: '{phi_pattern}'). Remove or rename."
            )

    def test_kpi_data_point_expected_fields_present(self):
        """All five KPI metric fields plus date/unit must be present."""
        expected = {
            "date", "unit",
            "avg_discharge_doc_time_min",
            "readmission_rate_30d",
            "med_recon_completion_rate",
            "bed_utilisation_pct",
            "agent_task_success_rate",
        }
        assert expected.issubset(set(KpiDataPoint.model_fields.keys()))

    def test_kpi_data_point_accepts_null_metrics(self):
        """All metric fields are Optional — null values from the view must be accepted."""
        point = KpiDataPoint(date=datetime.date(2026, 7, 1), unit="ICU")
        assert point.avg_discharge_doc_time_min is None
        assert point.readmission_rate_30d is None
        assert point.med_recon_completion_rate is None
        assert point.bed_utilisation_pct is None
        assert point.agent_task_success_rate is None

    def test_readmission_rate_bounds_validation(self):
        """readmission_rate_30d must be in range 0.0–1.0."""
        with pytest.raises(Exception):
            KpiDataPoint(date=datetime.date(2026, 7, 1), unit="ICU", readmission_rate_30d=1.5)

    def test_bed_utilisation_pct_bounds_validation(self):
        """bed_utilisation_pct must be in range 0.0–100.0."""
        with pytest.raises(Exception):
            KpiDataPoint(date=datetime.date(2026, 7, 1), unit="ICU", bed_utilisation_pct=101.0)


class TestKpiResponseSchema:
    def test_kpi_response_contains_no_phi_fields(self):
        """No field in KpiResponse may carry PHI — enforced by field name inspection."""
        field_names = [f.lower() for f in KpiResponse.model_fields]
        for phi_pattern in _PHI_FIELD_PATTERNS:
            matching = [f for f in field_names if phi_pattern in f]
            assert not matching, (
                f"PHI-related field detected in KpiResponse: {matching} "
                f"(pattern: '{phi_pattern}')"
            )

    def test_kpi_response_echoes_filter_params(self):
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
```

### 3. Create `api-gateway/tests/unit/analytics/test_analytics_router.py`

```python
"""Unit tests for GET /api/v1/analytics/kpis RBAC and date range defaults.

US-061 AC Scenario 4 — 403 for NURSE; 200 for MANAGER and ADMIN
US-061 AC Scenario 1 — 30-day default date range applied when params absent
US-061 AC Scenario 2 — explicit from/to params respected; from > to → 400
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

# Fixture: a valid KpiResponse returned by KpiQueryService in all happy-path tests
_KPI_RESPONSE_FIXTURE = {
    "from_date": "2026-06-17",
    "to_date": "2026-07-17",
    "unit": None,
    "data": [],
    "total_rows": 0,
}


def _make_claims(role: str, units: list[str] | None = None):
    claims = MagicMock()
    claims.role = role
    claims.units = units or ["ICU", "WARD-A"]
    return claims


@pytest.fixture
def client():
    return TestClient(app)


class TestKpiRbac:
    def test_get_kpis_200_for_manager(self, client):
        with (
            patch("app.routers.analytics.get_current_user", return_value=_make_claims("MANAGER")),
            patch(
                "app.routers.analytics.KpiQueryService.get_kpis",
                new=AsyncMock(return_value=_KPI_RESPONSE_FIXTURE),
            ),
            patch("app.routers.analytics.get_read_session", new=AsyncMock()),
        ):
            response = client.get("/api/v1/analytics/kpis")
        assert response.status_code == 200

    def test_get_kpis_200_for_admin(self, client):
        with (
            patch("app.routers.analytics.get_current_user", return_value=_make_claims("ADMIN")),
            patch(
                "app.routers.analytics.KpiQueryService.get_kpis",
                new=AsyncMock(return_value=_KPI_RESPONSE_FIXTURE),
            ),
            patch("app.routers.analytics.get_read_session", new=AsyncMock()),
        ):
            response = client.get("/api/v1/analytics/kpis")
        assert response.status_code == 200

    @pytest.mark.parametrize("role", ["NURSE", "PHYSICIAN", "PHARMACIST", "PATIENT"])
    def test_get_kpis_403_for_disallowed_roles(self, client, role):
        with patch("app.routers.analytics.get_current_user", return_value=_make_claims(role)):
            response = client.get("/api/v1/analytics/kpis")
        assert response.status_code == 403


class TestKpiDateRangeDefaults:
    def test_get_kpis_defaults_to_30_day_range(self, client):
        """When no from/to params provided, effective_from = today - 30 days."""
        captured_from: list[datetime.date] = []

        async def _capture_get_kpis(self_inner, from_date, to_date, unit, accessible_units):
            captured_from.append(from_date)
            return _KPI_RESPONSE_FIXTURE

        with (
            patch("app.routers.analytics.get_current_user", return_value=_make_claims("MANAGER")),
            patch("app.routers.analytics.KpiQueryService.get_kpis", new=_capture_get_kpis),
            patch("app.routers.analytics.get_read_session", new=AsyncMock()),
        ):
            response = client.get("/api/v1/analytics/kpis")

        assert response.status_code == 200
        assert len(captured_from) == 1
        today = datetime.date.today()
        expected_from = today - datetime.timedelta(days=30)
        assert captured_from[0] == expected_from

    def test_get_kpis_respects_explicit_from_to(self, client):
        """Explicit from/to params are forwarded to KpiQueryService unchanged."""
        captured: dict = {}

        async def _capture(self_inner, from_date, to_date, unit, accessible_units):
            captured["from"] = from_date
            captured["to"] = to_date
            return _KPI_RESPONSE_FIXTURE

        with (
            patch("app.routers.analytics.get_current_user", return_value=_make_claims("MANAGER")),
            patch("app.routers.analytics.KpiQueryService.get_kpis", new=_capture),
            patch("app.routers.analytics.get_read_session", new=AsyncMock()),
        ):
            response = client.get("/api/v1/analytics/kpis?from=2026-07-01&to=2026-07-07")

        assert response.status_code == 200
        assert captured["from"] == datetime.date(2026, 7, 1)
        assert captured["to"] == datetime.date(2026, 7, 7)

    def test_get_kpis_400_when_from_after_to(self, client):
        """from > to must return 400 Bad Request."""
        with patch("app.routers.analytics.get_current_user", return_value=_make_claims("MANAGER")):
            response = client.get("/api/v1/analytics/kpis?from=2026-07-15&to=2026-07-01")
        assert response.status_code == 400
        assert "from" in response.json()["detail"].lower()
```

### 4. Create `smarthandoff-angular/src/app/features/analytics/charts/chart.utils.spec.ts`

```typescript
/**
 * Unit tests for chart.utils.ts — data transformation functions.
 *
 * Covers:
 *   - toDateLabels: correct "MMM D" format; empty array; null values skipped
 *   - toSingleSeriesData: numeric values extracted; null preserved (not coerced to 0)
 *   - toAgentSuccessDatasets: success + failure percentages sum to 100; null handled
 */
import { toAgentSuccessDatasets, toDateLabels, toSingleSeriesData } from './chart.utils';
import type { KpiDataPoint } from '../analytics.models';

const makePoint = (overrides: Partial<KpiDataPoint> = {}): KpiDataPoint => ({
  date: '2026-07-01',
  unit: 'ICU',
  avg_discharge_doc_time_min: null,
  readmission_rate_30d: null,
  med_recon_completion_rate: null,
  bed_utilisation_pct: null,
  agent_task_success_rate: null,
  ...overrides,
});

describe('toDateLabels', () => {
  it('returns empty array for empty input', () => {
    expect(toDateLabels([])).toEqual([]);
  });

  it('formats each date as "MMM D" locale string', () => {
    const data = [makePoint({ date: '2026-07-01' }), makePoint({ date: '2026-07-15' })];
    const labels = toDateLabels(data);
    // Confirm the labels are non-empty strings and contain numeric day portion
    expect(labels).toHaveLength(2);
    expect(labels[0]).toMatch(/\w{3}\s\d{1,2}/);
    expect(labels[1]).toMatch(/\w{3}\s\d{1,2}/);
  });
});

describe('toSingleSeriesData', () => {
  it('extracts numeric values for the given field', () => {
    const data = [
      makePoint({ avg_discharge_doc_time_min: 45.5 }),
      makePoint({ avg_discharge_doc_time_min: 32.0 }),
    ];
    expect(toSingleSeriesData(data, 'avg_discharge_doc_time_min')).toEqual([45.5, 32.0]);
  });

  it('preserves null values — does not coerce to 0', () => {
    const data = [
      makePoint({ avg_discharge_doc_time_min: 45.5 }),
      makePoint({ avg_discharge_doc_time_min: null }),
    ];
    const result = toSingleSeriesData(data, 'avg_discharge_doc_time_min');
    expect(result[1]).toBeNull();
  });

  it('returns all nulls for an empty metric field', () => {
    const data = [makePoint(), makePoint()];
    expect(toSingleSeriesData(data, 'readmission_rate_30d')).toEqual([null, null]);
  });
});

describe('toAgentSuccessDatasets', () => {
  it('produces two datasets: Success and Failure', () => {
    const data = [makePoint({ agent_task_success_rate: 0.85 })];
    const datasets = toAgentSuccessDatasets(data);
    expect(datasets).toHaveLength(2);
    expect(datasets[0].label).toBe('Success');
    expect(datasets[1].label).toBe('Failure');
  });

  it('success + failure sums to 100 for each data point', () => {
    const data = [
      makePoint({ agent_task_success_rate: 0.85 }),
      makePoint({ agent_task_success_rate: 0.60 }),
    ];
    const datasets = toAgentSuccessDatasets(data);
    const success = datasets[0].data as number[];
    const failure = datasets[1].data as number[];
    success.forEach((s, i) => {
      expect(s + (failure[i] as number)).toBe(100);
    });
  });

  it('handles null agent_task_success_rate — both segments null', () => {
    const data = [makePoint({ agent_task_success_rate: null })];
    const datasets = toAgentSuccessDatasets(data);
    expect(datasets[0].data[0]).toBeNull();
    expect(datasets[1].data[0]).toBeNull();
  });
});
```

---

## Validation Checklist

- [ ] `test_analytics_schemas.py` — all PHI pattern assertions pass (no PHI field names detected)
- [ ] `test_analytics_schemas.py` — all 7 expected columns present in `KpiDataPoint.model_fields`
- [ ] `test_analytics_schemas.py` — null metric values accepted; out-of-bounds values rejected with `ValidationError`
- [ ] `test_analytics_router.py` — `200 OK` for `MANAGER` and `ADMIN`; `403` for `NURSE`, `PHYSICIAN`, `PHARMACIST`, `PATIENT`
- [ ] `test_analytics_router.py` — missing params → 30-day default applied
- [ ] `test_analytics_router.py` — `from > to` → `400 Bad Request` containing `"from"` in detail message
- [ ] `chart.utils.spec.ts` — `toSingleSeriesData` preserves `null` (not coerced to `0`)
- [ ] `chart.utils.spec.ts` — `toAgentSuccessDatasets` success + failure sums to 100 for non-null values
- [ ] All backend tests pass: `pytest api-gateway/tests/unit/analytics/ -v`
- [ ] All frontend tests pass: `ng test --include='**/chart.utils.spec.ts'`
- [ ] Branch coverage ≥ 80% across `app/analytics/schemas.py`, `app/routers/analytics.py`, `chart.utils.ts`

---

## Files Created / Modified

| File | Action |
|------|--------|
| `api-gateway/tests/unit/analytics/__init__.py` | Create |
| `api-gateway/tests/unit/analytics/test_analytics_schemas.py` | Create |
| `api-gateway/tests/unit/analytics/test_analytics_router.py` | Create |
| `smarthandoff-angular/src/app/features/analytics/charts/chart.utils.spec.ts` | Create |
