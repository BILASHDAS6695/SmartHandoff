---
id: TASK-006
title: "Unit Tests — Inference Endpoint, Feature Vector Construction, Prediction Service"
user_story: US-036
epic: EP-006
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-036/TASK-001, US-036/TASK-002, US-036/TASK-003, US-036/TASK-004]
---

# TASK-006: Unit Tests — Inference Endpoint, Feature Vector Construction, Prediction Service

> **Story:** US-036 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-036 DoD specifies: *"Unit tests: inference endpoint, feature vector construction"*

All four acceptance criteria scenarios must be covered. Tests are split across three test files:

| Test File | Module Under Test | Coverage Focus |
|-----------|-----------------|----------------|
| `test_discharge_time_endpoint.py` | `ml_inference/app/routers/discharge_time.py` | Endpoint happy path; 500 ms response; auth rejection; 503 on model unavailable; confidence level mapping |
| `test_features.py` | `ml/discharge_time_model/features.py` | Feature vector construction; `los_so_far_hours` derivation; `compute_los_so_far_hours` edge cases |
| `test_prediction_service.py` | `backend/app/agents/bed_management/prediction_service.py` | Happy path DB write; ML Inference 503 retry/backoff; encounter not found; PHI not logged |

Coverage target: ≥ 80% branch coverage across all three modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---------------------|---------------|
| `joblib.load` (model) | `MagicMock` returning a pipeline that calls `pipeline.predict()` returning `[72.0]` |
| `google.cloud.storage.Client` | `MagicMock` — `blob.download_to_filename` no-ops; metadata returns version tag |
| `httpx.AsyncClient.post` (ML Inference) | `AsyncMock` returning configurable `httpx.Response` |
| `AsyncSession` (SQLAlchemy) | `AsyncMock` with `execute()`, `commit()`, `rollback()` |
| `BedBoardRefreshService.refresh_async` | `AsyncMock` |
| FastAPI `AsyncClient` | `httpx.AsyncClient(app=app, base_url="http://test")` |

---

## Acceptance Criteria Addressed

| US-036 AC | Test Cases |
|---|---|
| **Scenario 1 (500 ms)** | `test_predict_returns_200_with_valid_payload`, `test_predict_response_time_under_500ms` |
| **Scenario 2 (±2 h accuracy)** | `test_evaluate_passes_quality_gate`, `test_evaluate_fails_quality_gate_raises_system_exit` |
| **Scenario 3 (update on change)** | `test_prediction_service_writes_to_encounter`, `test_prediction_service_retries_on_503`, `test_prediction_service_skips_on_encounter_not_found` |
| **Scenario 4 (confidence indicator)** | `test_confidence_level_high_when_interval_below_1h`, `test_confidence_level_medium_when_interval_1_to_2h`, `test_confidence_level_low_when_interval_above_2h` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p ml_inference/tests
mkdir -p ml/discharge_time_model/tests
mkdir -p backend/tests/unit/agents/bed_management
touch ml_inference/tests/__init__.py
touch ml/discharge_time_model/tests/__init__.py
```

### 2. Create `ml_inference/tests/test_discharge_time_endpoint.py`

```python
"""Unit tests for POST /ml-inference/predict/discharge-time endpoint.

Coverage:
    Scenario 1: returns 200 with predicted_discharge_time and confidence_interval
    Scenario 4: confidence_level correctly mapped from confidence_interval_hours
    Auth: unauthenticated → 401; invalid JWT → 401
    503 when model not loaded
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import httpx
from fastapi.testclient import TestClient

from app.main import app

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

VALID_PAYLOAD = {
    "encounter_id": "550e8400-e29b-41d4-a716-446655440001",
    "admit_time": "2026-07-17T08:00:00Z",
    "patient_dob": "1960-03-15T00:00:00Z",
    "admit_diagnosis_group": "CARDIAC",
    "unit": "3A",
    "pending_procedures_count": 1,
}


def _mock_pipeline(predicted_hours: float = 6.0):
    """Return a MagicMock pipeline whose predict() returns [predicted_hours]."""
    pipeline = MagicMock()
    pipeline.predict.return_value = np.array([predicted_hours])
    return pipeline


# ──────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────

@patch("app.routers.discharge_time.load_model", return_value=_mock_pipeline(6.0))
@patch("app.routers.discharge_time.get_model_version", return_value="v20260717")
@patch("app.auth.verify_service_account_jwt", return_value=None)
def test_predict_returns_200_with_valid_payload(mock_auth, mock_version, mock_model):
    with TestClient(app) as client:
        resp = client.post(
            "/ml-inference/predict/discharge-time",
            json=VALID_PAYLOAD,
            headers={"Authorization": "Bearer mock-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "predicted_discharge_time" in data
    assert "confidence_interval_hours" in data
    assert data["confidence_level"] in ("high", "medium", "low")
    assert data["encounter_id"] == VALID_PAYLOAD["encounter_id"]
    assert data["model_version"] == "v20260717"


@patch("app.routers.discharge_time.load_model", return_value=_mock_pipeline(6.0))
@patch("app.routers.discharge_time.get_model_version", return_value="v1")
@patch("app.auth.verify_service_account_jwt", return_value=None)
def test_predict_response_time_under_500ms(mock_auth, mock_version, mock_model):
    """Inference latency must be < 500 ms (TR-007) after model is pre-loaded."""
    with TestClient(app) as client:
        start = time.perf_counter()
        resp = client.post(
            "/ml-inference/predict/discharge-time",
            json=VALID_PAYLOAD,
            headers={"Authorization": "Bearer mock-token"},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
    assert resp.status_code == 200
    assert elapsed_ms < 500, f"Response took {elapsed_ms:.1f} ms — exceeds 500 ms threshold"


# ──────────────────────────────────────────────
# Confidence level mapping (AC Scenario 4)
# ──────────────────────────────────────────────

@pytest.mark.parametrize("hours,expected_level", [
    (2.0, "high"),    # 15% of 2 h = 0.3 h < 1 h → high
    (8.0, "medium"),  # 15% of 8 h = 1.2 h  → medium (1-2 h)
    (16.0, "low"),    # 15% of 16 h = 2.4 h → low (>2 h)
])
@patch("app.auth.verify_service_account_jwt", return_value=None)
def test_confidence_level_mapping(mock_auth, hours, expected_level):
    with patch("app.routers.discharge_time.load_model", return_value=_mock_pipeline(hours)), \
         patch("app.routers.discharge_time.get_model_version", return_value="v1"):
        with TestClient(app) as client:
            resp = client.post(
                "/ml-inference/predict/discharge-time",
                json=VALID_PAYLOAD,
                headers={"Authorization": "Bearer mock-token"},
            )
    assert resp.status_code == 200
    assert resp.json()["confidence_level"] == expected_level


# ──────────────────────────────────────────────
# Auth rejection
# ──────────────────────────────────────────────

def test_predict_rejects_unauthenticated_request():
    with TestClient(app) as client:
        resp = client.post("/ml-inference/predict/discharge-time", json=VALID_PAYLOAD)
    assert resp.status_code in (401, 403)


# ──────────────────────────────────────────────
# Model unavailable
# ──────────────────────────────────────────────

@patch("app.routers.discharge_time.load_model", side_effect=RuntimeError("GCS unavailable"))
@patch("app.auth.verify_service_account_jwt", return_value=None)
def test_predict_returns_503_when_model_unavailable(mock_auth, mock_model):
    with TestClient(app) as client:
        resp = client.post(
            "/ml-inference/predict/discharge-time",
            json=VALID_PAYLOAD,
            headers={"Authorization": "Bearer mock-token"},
        )
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"].lower()
```

### 3. Create `ml/discharge_time_model/tests/test_features.py`

```python
"""Unit tests for discharge time feature engineering (features.py).

Coverage:
    compute_los_so_far_hours: positive, zero, negative (clipped), timezone-naive input
    build_feature_dataframe: correct column names, age derivation, LOS computation
    build_single_feature_vector: returns dict matching ALL_FEATURES
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from features import (
    ALL_FEATURES,
    compute_los_so_far_hours,
    build_feature_dataframe,
    build_single_feature_vector,
)


# ──────────────────────────────────────────────
# compute_los_so_far_hours
# ──────────────────────────────────────────────

def test_los_so_far_hours_positive():
    admit = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    ref = datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)  # 6 hours later
    assert compute_los_so_far_hours(admit, ref) == pytest.approx(6.0, abs=0.01)


def test_los_so_far_hours_clips_to_zero_for_future_admit():
    """If admit_time is in the future (data quality issue), return 0.0 not negative."""
    admit = datetime(2026, 7, 17, 14, 0, tzinfo=timezone.utc)
    ref = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    assert compute_los_so_far_hours(admit, ref) == 0.0


def test_los_so_far_hours_handles_timezone_naive_admit():
    """Timezone-naive admit_time is assumed UTC (no crash)."""
    admit = datetime(2026, 7, 17, 8, 0)  # no tzinfo
    ref = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)
    result = compute_los_so_far_hours(admit, ref)
    assert result == pytest.approx(2.0, abs=0.01)


def test_los_so_far_hours_zero_when_admit_equals_reference():
    t = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    assert compute_los_so_far_hours(t, t) == 0.0


# ──────────────────────────────────────────────
# build_feature_dataframe
# ──────────────────────────────────────────────

def _make_encounter(**overrides):
    base = {
        "admit_time": datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc),
        "patient_dob": datetime(1960, 3, 15, tzinfo=timezone.utc),
        "admit_diagnosis_group": "CARDIAC",
        "unit": "3A",
        "pending_procedures_count": 2,
    }
    return {**base, **overrides}


def test_build_feature_dataframe_returns_correct_columns():
    df = build_feature_dataframe([_make_encounter()])
    assert list(df.columns) == ALL_FEATURES


def test_build_feature_dataframe_computes_age_correctly():
    enc = _make_encounter(
        admit_time=datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc),
        patient_dob=datetime(1960, 7, 17, tzinfo=timezone.utc),
    )
    df = build_feature_dataframe([enc])
    # Exact birthday → 66 years old
    assert df.iloc[0]["patient_age"] == 66


def test_build_feature_dataframe_pending_procedures_defaults_to_zero():
    enc = _make_encounter()
    enc.pop("pending_procedures_count", None)
    df = build_feature_dataframe([enc])
    assert df.iloc[0]["pending_procedures"] == 0


def test_build_feature_dataframe_day_of_week_range():
    """day_of_week must be 0-6."""
    df = build_feature_dataframe([_make_encounter()])
    assert 0 <= df.iloc[0]["day_of_week"] <= 6


# ──────────────────────────────────────────────
# build_single_feature_vector
# ──────────────────────────────────────────────

def test_build_single_feature_vector_returns_dict_with_all_features():
    result = build_single_feature_vector(_make_encounter())
    for feature in ALL_FEATURES:
        assert feature in result, f"Missing feature: {feature}"
```

### 4. Create `backend/tests/unit/agents/bed_management/test_prediction_service.py`

```python
"""Unit tests for DischargePredictionService.

Coverage:
    Happy path: encounter found, ML Inference returns 200, DB updated, refresh triggered
    503 on first attempt: retries twice, succeeds on third
    503 all 3 attempts: returns False, no DB write, no crash
    Encounter not found: returns False immediately
    PHI guard: patient_dob does NOT appear in log output
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

from app.agents.bed_management.prediction_service import DischargePredictionService


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def _make_encounter():
    enc = MagicMock()
    enc.id = "550e8400-e29b-41d4-a716-446655440001"
    enc.admit_time = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    enc.admit_diagnosis_group = "CARDIAC"
    enc.unit = "3A"
    enc.pending_procedures_count = 1
    enc.patient.dob = datetime(1960, 3, 15, tzinfo=timezone.utc)
    enc.deleted_at = None
    return enc


def _make_inference_response(hours_from_admit: float = 6.0) -> dict:
    from datetime import timedelta
    predicted = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc) + timedelta(hours=hours_from_admit)
    return {
        "encounter_id": "550e8400-e29b-41d4-a716-446655440001",
        "predicted_discharge_time": predicted.isoformat(),
        "confidence_interval_hours": 0.9,
        "confidence_level": "high",
        "model_version": "v20260717",
    }


# ──────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prediction_service_writes_to_encounter_on_success():
    session = AsyncMock()
    encounter = _make_encounter()
    session.execute.return_value.scalar_one_or_none.return_value = encounter

    http_response = httpx.Response(200, json=_make_inference_response())
    http_client = AsyncMock(spec=httpx.AsyncClient)
    http_client.post.return_value = http_response

    refresh_service = AsyncMock()
    svc = DischargePredictionService(http_client=http_client)

    result = await svc.update_prediction(
        session=session,
        encounter_id=str(encounter.id),
        refresh_service=refresh_service,
    )

    assert result is True
    session.execute.assert_called()   # DB update was issued
    session.commit.assert_awaited_once()
    refresh_service.refresh_async.assert_awaited_once()


# ──────────────────────────────────────────────
# Retry on 503
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prediction_service_retries_on_503_and_succeeds():
    session = AsyncMock()
    encounter = _make_encounter()
    session.execute.return_value.scalar_one_or_none.return_value = encounter

    # First two calls → 503; third → 200
    http_client = AsyncMock(spec=httpx.AsyncClient)
    http_client.post.side_effect = [
        httpx.HTTPStatusError("503", request=MagicMock(), response=httpx.Response(503)),
        httpx.HTTPStatusError("503", request=MagicMock(), response=httpx.Response(503)),
        httpx.Response(200, json=_make_inference_response()),
    ]

    refresh_service = AsyncMock()
    svc = DischargePredictionService(http_client=http_client)

    with patch("asyncio.sleep", new_callable=AsyncMock):  # Skip actual sleep in tests
        result = await svc.update_prediction(
            session=session,
            encounter_id=str(encounter.id),
            refresh_service=refresh_service,
        )

    assert result is True
    assert http_client.post.call_count == 3


@pytest.mark.asyncio
async def test_prediction_service_returns_false_after_exhausting_retries():
    session = AsyncMock()
    encounter = _make_encounter()
    session.execute.return_value.scalar_one_or_none.return_value = encounter

    http_client = AsyncMock(spec=httpx.AsyncClient)
    http_client.post.side_effect = httpx.RequestError("Connection refused")

    refresh_service = AsyncMock()
    svc = DischargePredictionService(http_client=http_client)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await svc.update_prediction(
            session=session,
            encounter_id=str(encounter.id),
            refresh_service=refresh_service,
        )

    assert result is False
    session.commit.assert_not_awaited()   # No DB write on full failure
    refresh_service.refresh_async.assert_not_awaited()


# ──────────────────────────────────────────────
# Encounter not found
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prediction_service_returns_false_when_encounter_not_found():
    session = AsyncMock()
    session.execute.return_value.scalar_one_or_none.return_value = None

    http_client = AsyncMock(spec=httpx.AsyncClient)
    refresh_service = AsyncMock()
    svc = DischargePredictionService(http_client=http_client)

    result = await svc.update_prediction(
        session=session,
        encounter_id="non-existent-uuid",
        refresh_service=refresh_service,
    )

    assert result is False
    http_client.post.assert_not_called()


# ──────────────────────────────────────────────
# PHI guard — patient_dob must NOT appear in logs
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_phi_not_logged_during_prediction(caplog):
    session = AsyncMock()
    encounter = _make_encounter()
    session.execute.return_value.scalar_one_or_none.return_value = encounter

    http_client = AsyncMock(spec=httpx.AsyncClient)
    http_client.post.return_value = httpx.Response(200, json=_make_inference_response())

    refresh_service = AsyncMock()
    svc = DischargePredictionService(http_client=http_client)

    with caplog.at_level(logging.INFO, logger="app.agents.bed_management.prediction_service"):
        await svc.update_prediction(
            session=session,
            encounter_id=str(encounter.id),
            refresh_service=refresh_service,
        )

    # Patient DOB should not appear anywhere in logged output
    dob_str = "1960-03-15"
    for record in caplog.records:
        assert dob_str not in record.getMessage(), (
            f"PHI (patient_dob) found in log: {record.getMessage()}"
        )
```

---

## Validation Checklist

- [ ] All tests pass: `pytest ml_inference/tests/ ml/discharge_time_model/tests/ backend/tests/unit/agents/bed_management/test_prediction_service.py -v`
- [ ] Coverage ≥ 80% on the three test modules: `pytest --cov=app --cov=features --cov-report=term-missing`
- [ ] `test_predict_response_time_under_500ms` passes (model mocked in-memory, not GCS)
- [ ] `test_prediction_service_retries_on_503_and_succeeds` verifies `call_count == 3`
- [ ] `test_phi_not_logged_during_prediction` passes — patient DOB absent from all log records
- [ ] `test_evaluate_passes_quality_gate` runs end-to-end with a synthetic dataset of 100 samples

---

## Definition of Done Checklist (US-036)

| Item | Status |
|------|--------|
| ✅ Unit tests: inference endpoint, feature vector construction | This task |
| ✅ Unit tests: prediction service DB write, retry, PHI guard | This task |
