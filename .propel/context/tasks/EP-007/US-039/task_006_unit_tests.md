---
id: TASK-006
title: "Unit Tests — Risk Tier Logic, Feature Extraction, Inference Endpoint, Agent Processing, Risk API RBAC"
user_story: US-039
epic: EP-007
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-039/TASK-001, US-039/TASK-002, US-039/TASK-003, US-039/TASK-004, US-039/TASK-005]
---

# TASK-006: Unit Tests — Risk Tier Logic, Feature Extraction, Inference Endpoint, Agent Processing, Risk API RBAC

> **Story:** US-039 | **Epic:** EP-007 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-039 DoD specifies unit tests covering all four acceptance criteria scenarios. Tests are split across five test files matching the five production modules implemented in TASK-001 through TASK-005.

| Test File | Module Under Test | Coverage Focus |
|-----------|-----------------|----------------|
| `test_risk_schemas.py` | `app/schemas.py` (ml-inference) | `assign_risk_tier()` boundary values; all three tiers |
| `test_model_inference.py` | `app/predictor.py` (ml-inference) | Full prediction flow with mock model + scaler; SHAP output; label mapping |
| `test_feature_extractor.py` | `feature_extractor.py` (followup_care) | Age calc; LOS calc; prior admissions query; FHIR failure graceful degradation |
| `test_followup_care_agent.py` | `agent.py` (followup_care) | A03 processing; DB update; AgentTask write; skip non-A03 events; retry on DB failure |
| `test_encounters_risk_router.py` | `routers/encounters_risk.py` (api-gateway) | HTTP 200 with valid JWT + data; 403 for Pharmacist; 404 for unknown encounter; 400 for invalid UUID |

Coverage target: ≥80% branch coverage across all five modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---------------------|---------------|
| `LogisticRegression` (joblib) | `MagicMock` with `.predict_proba()` returning `np.array([[0.28, 0.72]])` |
| `StandardScaler` | `MagicMock` with `.transform()` returning the input unchanged |
| `shap.LinearExplainer` | `MagicMock` with `.shap_values()` returning fixed `np.array` |
| `AsyncSession` (write) | `AsyncMock` with `execute()`, `commit()`, `rollback()` |
| `AsyncSession` (read) | `AsyncMock` returning mock Encounter + Patient records |
| `FHIRClient.get_conditions()` | `AsyncMock` returning list of mock `ConditionModel` objects |
| `httpx.AsyncClient.post()` | `AsyncMock` returning `MagicMock(json=lambda: {...}, raise_for_status=lambda: None)` |
| FastAPI `TestClient` | `httpx.AsyncClient` with app transport |

---

## Acceptance Criteria Addressed

| US-039 AC | Test Cases |
|---|---|
| **Scenario 1** (60 s persistence) | `test_a03_updates_encounter_risk_score`, `test_a03_creates_agent_task_record` |
| **Scenario 2** (tier assignment) | `test_assign_risk_tier_low`, `test_assign_risk_tier_medium`, `test_assign_risk_tier_high`, `test_assign_risk_tier_boundary_low_medium`, `test_assign_risk_tier_boundary_medium_high` |
| **Scenario 3** (AUC ≥ 0.80) | Validated in TASK-001 CI pipeline (quality gate in `train_readmission_risk.py`); not repeated here |
| **Scenario 4** (API response) | `test_get_risk_returns_all_fields_for_physician`, `test_get_risk_403_for_pharmacist`, `test_get_risk_404_unknown_encounter` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p ml-inference/tests/unit
mkdir -p backend/tests/unit/agents/followup_care
mkdir -p api-gateway/tests/unit/routers
touch ml-inference/tests/__init__.py
touch ml-inference/tests/unit/__init__.py
touch backend/tests/unit/agents/followup_care/__init__.py
touch api-gateway/tests/unit/routers/__init__.py
```

### 2. Create `ml-inference/tests/unit/test_risk_schemas.py`

```python
"""Unit tests for assign_risk_tier() boundary conditions.

US-039 AC Scenario 2:
    probability=0.25 → LOW
    probability=0.55 → MEDIUM
    probability=0.72 → HIGH
    Boundary LOW/MEDIUM: 0.30
    Boundary MEDIUM/HIGH: 0.70
"""
import pytest

from app.schemas import RiskTier, assign_risk_tier


class TestAssignRiskTier:
    def test_low_tier_below_threshold(self):
        assert assign_risk_tier(0.25) == RiskTier.LOW

    def test_low_tier_at_zero(self):
        assert assign_risk_tier(0.0) == RiskTier.LOW

    def test_low_tier_just_below_medium_boundary(self):
        assert assign_risk_tier(0.2999) == RiskTier.LOW

    def test_medium_tier_at_low_boundary(self):
        """0.30 is inclusive of MEDIUM."""
        assert assign_risk_tier(0.30) == RiskTier.MEDIUM

    def test_medium_tier_midpoint(self):
        assert assign_risk_tier(0.55) == RiskTier.MEDIUM

    def test_medium_tier_just_below_high_boundary(self):
        assert assign_risk_tier(0.6999) == RiskTier.MEDIUM

    def test_high_tier_at_medium_high_boundary(self):
        """0.70 is inclusive of HIGH."""
        assert assign_risk_tier(0.70) == RiskTier.HIGH

    def test_high_tier_above_boundary(self):
        assert assign_risk_tier(0.72) == RiskTier.HIGH

    def test_high_tier_at_one(self):
        assert assign_risk_tier(1.0) == RiskTier.HIGH
```

### 3. Create `ml-inference/tests/unit/test_model_inference.py`

```python
"""Unit tests for the inference predictor (predictor.py).

Verifies: feature vector assembly, SHAP computation, label mapping, response schema.
"""
from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from app.schemas import ReadmissionFeatures, RiskTier


SAMPLE_FEATURES = ReadmissionFeatures(
    age=72.0,
    los_days=6.0,
    num_comorbidities=4.0,
    num_prior_admissions_12mo=2.0,
    medication_count=8.0,
    discharge_disposition=1.0,
    primary_diagnosis_group=0.0,
)

SAMPLE_LABELS = {
    "age": "Patient Age (Years)",
    "los_days": "Length of Stay (Days)",
    "num_comorbidities": "Number of Active Comorbidities",
    "num_prior_admissions_12mo": "Prior Hospital Admissions (12 Months)",
    "medication_count": "Active Medication Count at Discharge",
    "discharge_disposition": "Discharge Destination",
    "primary_diagnosis_group": "Primary Diagnosis Category",
}


@pytest.fixture
def mock_model():
    model = MagicMock()
    # Return probability 0.72 → HIGH tier
    model.predict_proba.return_value = np.array([[0.28, 0.72]])
    return model


@pytest.fixture
def mock_scaler():
    scaler = MagicMock()
    # Return input unchanged (identity transform for testing)
    scaler.transform.side_effect = lambda x: x
    return scaler


@pytest.fixture
def mock_shap_explainer():
    explainer = MagicMock()
    # Simulate SHAP values with 7 features; prior admissions has highest absolute value
    shap_vals = np.array([[0.05, 0.10, 0.15, 0.35, 0.08, 0.12, -0.03]])
    explainer.shap_values.return_value = shap_vals
    return explainer


def test_predict_returns_high_tier_for_probability_072(mock_model, mock_scaler, mock_shap_explainer):
    with (
        patch("app.predictor.get_model", return_value=mock_model),
        patch("app.predictor.get_scaler", return_value=mock_scaler),
        patch("app.predictor.get_model_version", return_value="1.0.0"),
        patch("app.predictor._get_shap_explainer", return_value=mock_shap_explainer),
    ):
        from app.predictor import predict
        result = predict(SAMPLE_FEATURES, SAMPLE_LABELS)

    assert result.risk_score == pytest.approx(0.72, abs=0.01)
    assert result.risk_tier == RiskTier.HIGH
    assert result.model_version == "1.0.0"


def test_predict_returns_five_contributing_factors(mock_model, mock_scaler, mock_shap_explainer):
    with (
        patch("app.predictor.get_model", return_value=mock_model),
        patch("app.predictor.get_scaler", return_value=mock_scaler),
        patch("app.predictor.get_model_version", return_value="1.0.0"),
        patch("app.predictor._get_shap_explainer", return_value=mock_shap_explainer),
    ):
        from app.predictor import predict
        result = predict(SAMPLE_FEATURES, SAMPLE_LABELS)

    assert len(result.contributing_factors) == 5


def test_predict_contributing_factors_use_human_readable_labels(mock_model, mock_scaler, mock_shap_explainer):
    with (
        patch("app.predictor.get_model", return_value=mock_model),
        patch("app.predictor.get_scaler", return_value=mock_scaler),
        patch("app.predictor.get_model_version", return_value="1.0.0"),
        patch("app.predictor._get_shap_explainer", return_value=mock_shap_explainer),
    ):
        from app.predictor import predict
        result = predict(SAMPLE_FEATURES, SAMPLE_LABELS)

    feature_labels_in_response = {cf.feature for cf in result.contributing_factors}
    # All labels must come from SAMPLE_LABELS values, not raw feature names
    assert feature_labels_in_response.issubset(set(SAMPLE_LABELS.values()))


def test_predict_direction_increases_for_positive_shap(mock_model, mock_scaler, mock_shap_explainer):
    with (
        patch("app.predictor.get_model", return_value=mock_model),
        patch("app.predictor.get_scaler", return_value=mock_scaler),
        patch("app.predictor.get_model_version", return_value="1.0.0"),
        patch("app.predictor._get_shap_explainer", return_value=mock_shap_explainer),
    ):
        from app.predictor import predict
        result = predict(SAMPLE_FEATURES, SAMPLE_LABELS)

    positive_shap_factors = [cf for cf in result.contributing_factors if cf.shap_value > 0]
    for factor in positive_shap_factors:
        assert factor.direction == "increases_risk"
```

### 4. Create `backend/tests/unit/agents/followup_care/test_feature_extractor.py`

```python
"""Unit tests for FollowUpCareAgent feature extraction (feature_extractor.py)."""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.followup_care.feature_extractor import extract_features, ICD10_GROUP_DEFAULT


def make_encounter(
    admit_date=None,
    discharge_date=None,
    discharge_disposition="home",
    admitting_diagnosis="I25.10",
):
    enc = MagicMock()
    enc.id = "enc-uuid-001"
    enc.patient_id = "pat-uuid-001"
    enc.admit_date = admit_date or datetime.datetime(2026, 3, 1, 9, 0)
    enc.discharge_date = discharge_date or datetime.datetime(2026, 3, 6, 14, 0)
    enc.discharge_disposition = discharge_disposition
    enc.admitting_diagnosis = admitting_diagnosis
    return enc


def make_patient(dob=datetime.date(1954, 1, 15)):
    pat = MagicMock()
    pat.id = "pat-uuid-001"
    pat.dob = dob
    return pat


@pytest.fixture
def mock_session(make_enc=None, make_pat=None):
    session = AsyncMock()
    enc = make_encounter()
    pat = make_patient()

    def side_effect(stmt):
        result = AsyncMock()
        # Determine which model is being queried by inspecting the statement class name
        class_name = stmt.column_descriptions[0]["entity"].__name__ if hasattr(stmt, "column_descriptions") else ""
        if "Encounter" in str(stmt):
            result.scalar_one_or_none.return_value = enc
            result.scalar_one.return_value = 1  # prior admissions count
        elif "Patient" in str(stmt):
            result.scalar_one_or_none.return_value = pat
        elif "Medication" in str(stmt):
            result.scalar_one.return_value = 5  # medication count
        return result

    session.execute = AsyncMock(side_effect=side_effect)
    return session


@pytest.mark.asyncio
async def test_age_calculated_correctly():
    session = AsyncMock()
    enc = make_encounter(admit_date=datetime.datetime(2026, 3, 1))
    pat = make_patient(dob=datetime.date(1954, 1, 15))

    def execute_side_effect(stmt):
        result = MagicMock()
        if "Patient" in str(stmt):
            result.scalar_one_or_none.return_value = pat
        elif "Encounter" in str(stmt) and "count" not in str(stmt).lower():
            result.scalar_one_or_none.return_value = enc
        else:
            result.scalar_one.return_value = 0
        return result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    fhir_client = AsyncMock()
    fhir_client.get_conditions.return_value = []

    features = await extract_features(session, fhir_client, "enc-uuid-001")
    # age ≈ 72.1 (born 1954-01-15, admit 2026-03-01)
    assert 71.0 < features["age"] < 73.0


@pytest.mark.asyncio
async def test_los_days_calculated_from_admit_and_discharge():
    session = AsyncMock()
    admit = datetime.datetime(2026, 3, 1, 9, 0)
    discharge = datetime.datetime(2026, 3, 6, 14, 0)  # 5.208 days
    enc = make_encounter(admit_date=admit, discharge_date=discharge)
    pat = make_patient()

    def execute_side_effect(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = pat if "Patient" in str(stmt) else enc
        result.scalar_one.return_value = 0
        return result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    fhir_client = AsyncMock()
    fhir_client.get_conditions.return_value = []

    features = await extract_features(session, fhir_client, "enc-uuid-001")
    assert 5.0 < features["los_days"] < 6.0


@pytest.mark.asyncio
async def test_fhir_failure_defaults_num_comorbidities_to_zero():
    """FHIR unavailability must not crash the agent — degrade gracefully."""
    session = AsyncMock()
    enc = make_encounter()
    pat = make_patient()

    def execute_side_effect(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = pat if "Patient" in str(stmt) else enc
        result.scalar_one.return_value = 0
        return result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    fhir_client = AsyncMock()
    fhir_client.get_conditions.side_effect = ConnectionError("FHIR unreachable")

    features = await extract_features(session, fhir_client, "enc-uuid-001")
    assert features["num_comorbidities"] == 0.0


@pytest.mark.asyncio
async def test_unknown_icd10_prefix_maps_to_default_group():
    session = AsyncMock()
    enc = make_encounter(admitting_diagnosis="X99.0")  # "X" not in ICD10_GROUP_MAP
    pat = make_patient()

    def execute_side_effect(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = pat if "Patient" in str(stmt) else enc
        result.scalar_one.return_value = 0
        return result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    fhir_client = AsyncMock()
    fhir_client.get_conditions.return_value = []

    features = await extract_features(session, fhir_client, "enc-uuid-001")
    assert features["primary_diagnosis_group"] == float(ICD10_GROUP_DEFAULT)
```

### 5. Create `backend/tests/unit/agents/followup_care/test_followup_care_agent.py`

```python
"""Unit tests for FollowUpCareAgent A03 processing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.followup_care.agent import FollowUpCareAgent
from app.agents.followup_care.schemas import RiskTier
from app.agents.base_agent import RetryableError


SAMPLE_INFERENCE_RESPONSE = {
    "risk_score": 0.72,
    "risk_tier": "HIGH",
    "model_version": "1.0.0",
    "contributing_factors": [
        {"feature": "Prior Hospital Admissions (12 Months)", "shap_value": 0.35,
         "feature_value": 2.0, "direction": "increases_risk"},
    ],
}


@pytest.fixture
def agent():
    return FollowUpCareAgent(
        db_session_factory=AsyncMock(),
        read_session_factory=AsyncMock(),
        fhir_client=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_agent_returns_none_for_non_a03_events(agent):
    message = {"event_type": "A01", "encounter_id": "enc-uuid-001"}
    result = await agent.process(message)
    assert result is None


@pytest.mark.asyncio
async def test_agent_returns_none_for_a02_events(agent):
    message = {"event_type": "A02", "encounter_id": "enc-uuid-001", "bed_id": "bed-001", "previous_bed_id": "bed-002"}
    result = await agent.process(message)
    assert result is None


@pytest.mark.asyncio
async def test_a03_updates_encounter_risk_score(agent):
    message = {"event_type": "A03", "encounter_id": "enc-uuid-001"}

    with (
        patch(
            "app.agents.followup_care.agent.extract_features",
            new=AsyncMock(return_value={"age": 72.0, "los_days": 6.0, "num_comorbidities": 4.0,
                                        "num_prior_admissions_12mo": 2.0, "medication_count": 8.0,
                                        "discharge_disposition": 1.0, "primary_diagnosis_group": 0.0}),
        ),
        patch(
            "app.agents.followup_care.agent.call_readmission_inference",
            new=AsyncMock(return_value=SAMPLE_INFERENCE_RESPONSE),
        ),
    ):
        result = await agent.process(message)

    assert result is not None
    assert result.risk_score == pytest.approx(0.72)
    assert result.risk_tier == RiskTier.HIGH
    assert result.db_updated is True


@pytest.mark.asyncio
async def test_a03_creates_agent_task_record(agent):
    message = {"event_type": "A03", "encounter_id": "enc-uuid-001"}

    with (
        patch(
            "app.agents.followup_care.agent.extract_features",
            new=AsyncMock(return_value={"age": 65.0, "los_days": 3.0, "num_comorbidities": 1.0,
                                        "num_prior_admissions_12mo": 0.0, "medication_count": 3.0,
                                        "discharge_disposition": 0.0, "primary_diagnosis_group": 1.0}),
        ),
        patch(
            "app.agents.followup_care.agent.call_readmission_inference",
            new=AsyncMock(return_value=SAMPLE_INFERENCE_RESPONSE),
        ),
    ):
        result = await agent.process(message)

    assert result.agent_task_id is not None


@pytest.mark.asyncio
async def test_db_failure_raises_retryable_error(agent):
    message = {"event_type": "A03", "encounter_id": "enc-uuid-001"}

    # Make the write session raise an exception to simulate DB failure
    failing_session = AsyncMock()
    failing_session.__aenter__ = AsyncMock(return_value=failing_session)
    failing_session.__aexit__ = AsyncMock(return_value=None)
    failing_session.execute = AsyncMock(side_effect=Exception("DB connection refused"))
    agent._db_session_factory = MagicMock(return_value=failing_session)

    with (
        patch(
            "app.agents.followup_care.agent.extract_features",
            new=AsyncMock(return_value={"age": 72.0, "los_days": 6.0, "num_comorbidities": 4.0,
                                        "num_prior_admissions_12mo": 2.0, "medication_count": 8.0,
                                        "discharge_disposition": 1.0, "primary_diagnosis_group": 0.0}),
        ),
        patch(
            "app.agents.followup_care.agent.call_readmission_inference",
            new=AsyncMock(return_value=SAMPLE_INFERENCE_RESPONSE),
        ),
    ):
        with pytest.raises(RetryableError, match="DB write failed"):
            await agent.process(message)
```

### 6. Create `api-gateway/tests/unit/routers/test_encounters_risk_router.py`

```python
"""Unit tests for GET /api/v1/encounters/{id}/risk endpoint."""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Inline minimal app for test isolation
from fastapi import FastAPI
from app.routers.encounters_risk import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def make_encounter(risk_score=0.72, risk_tier="HIGH", unit="ICU"):
    enc = MagicMock()
    enc.id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    enc.risk_score = risk_score
    enc.risk_tier = risk_tier
    enc.unit = unit
    enc.attending_physician_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    enc.deleted_at = None
    return enc


def make_agent_task(risk_tier="HIGH", model_version="1.0.0"):
    task = MagicMock()
    task.output_summary = json.dumps({
        "risk_tier": risk_tier,
        "model_version": model_version,
        "contributing_factors": [
            {"feature": "Prior Hospital Admissions (12 Months)", "shap_value": 0.35,
             "feature_value": 2.0, "direction": "increases_risk"},
        ],
    })
    task.completed_at = None
    return task


PHYSICIAN_USER = {"sub": "22222222-2222-2222-2222-222222222222", "role": "physician", "units": ["ICU"]}
PHARMACIST_USER = {"sub": "33333333-3333-3333-3333-333333333333", "role": "pharmacist", "units": []}
ADMIN_USER = {"sub": "44444444-4444-4444-4444-444444444444", "role": "admin", "units": []}


@pytest.fixture
def mock_db_with_encounter():
    session = AsyncMock()
    enc = make_encounter()
    task = make_agent_task()

    def execute_side_effect(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = enc if "Encounter" in str(stmt) else task
        return result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    return session


def test_get_risk_returns_200_with_all_fields_for_physician(mock_db_with_encounter):
    with (
        patch("app.routers.encounters_risk.get_current_user", return_value=PHYSICIAN_USER),
        patch("app.routers.encounters_risk.require_any_role", return_value=lambda: None),
        patch("app.routers.encounters_risk.get_read_db", return_value=mock_db_with_encounter),
    ):
        response = client.get("/api/v1/encounters/11111111-1111-1111-1111-111111111111/risk")

    assert response.status_code == 200
    data = response.json()
    assert data["risk_score"] == pytest.approx(0.72)
    assert data["risk_tier"] == "HIGH"
    assert "contributing_factors" in data
    assert "model_version" in data


def test_get_risk_400_for_invalid_uuid():
    with (
        patch("app.routers.encounters_risk.get_current_user", return_value=ADMIN_USER),
        patch("app.routers.encounters_risk.require_any_role", return_value=lambda: None),
    ):
        response = client.get("/api/v1/encounters/not-a-uuid/risk")

    assert response.status_code == 400


def test_get_risk_404_for_unknown_encounter():
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    with (
        patch("app.routers.encounters_risk.get_current_user", return_value=ADMIN_USER),
        patch("app.routers.encounters_risk.require_any_role", return_value=lambda: None),
        patch("app.routers.encounters_risk.get_read_db", return_value=session),
    ):
        response = client.get("/api/v1/encounters/99999999-9999-9999-9999-999999999999/risk")

    assert response.status_code == 404


def test_get_risk_unknown_tier_when_risk_score_is_none():
    session = AsyncMock()
    enc = make_encounter(risk_score=None, risk_tier="UNKNOWN")
    task_result = MagicMock()
    task_result.scalar_one_or_none.side_effect = [enc, None]
    session.execute = AsyncMock(return_value=task_result)

    with (
        patch("app.routers.encounters_risk.get_current_user", return_value=ADMIN_USER),
        patch("app.routers.encounters_risk.require_any_role", return_value=lambda: None),
        patch("app.routers.encounters_risk.get_read_db", return_value=session),
    ):
        response = client.get("/api/v1/encounters/11111111-1111-1111-1111-111111111111/risk")

    assert response.status_code == 200
    assert response.json()["risk_tier"] == "UNKNOWN"
    assert response.json()["contributing_factors"] == []
```

---

## File Checklist

| File | Action |
|------|--------|
| `ml-inference/tests/__init__.py` | Create (empty) |
| `ml-inference/tests/unit/__init__.py` | Create (empty) |
| `ml-inference/tests/unit/test_risk_schemas.py` | Create |
| `ml-inference/tests/unit/test_model_inference.py` | Create |
| `backend/tests/unit/agents/followup_care/__init__.py` | Create (empty) |
| `backend/tests/unit/agents/followup_care/test_feature_extractor.py` | Create |
| `backend/tests/unit/agents/followup_care/test_followup_care_agent.py` | Create |
| `api-gateway/tests/unit/routers/__init__.py` | Create (empty) |
| `api-gateway/tests/unit/routers/test_encounters_risk_router.py` | Create |

---

## Validation

- [ ] All 9 `test_assign_risk_tier_*` tests pass — boundary values `0.30` and `0.70` correctly classified
- [ ] `test_predict_returns_high_tier_for_probability_072` passes with mock model
- [ ] `test_predict_returns_five_contributing_factors` passes — exactly 5 SHAP factors
- [ ] `test_predict_contributing_factors_use_human_readable_labels` passes — no raw feature names in response
- [ ] `test_fhir_failure_defaults_num_comorbidities_to_zero` passes — graceful FHIR degradation
- [ ] `test_agent_returns_none_for_non_a03_events` passes — A01, A02 skipped silently
- [ ] `test_db_failure_raises_retryable_error` passes — `RetryableError` raised on DB exception
- [ ] `test_get_risk_returns_200_with_all_fields_for_physician` passes — all response fields present
- [ ] `test_get_risk_400_for_invalid_uuid` passes
- [ ] `test_get_risk_404_for_unknown_encounter` passes
- [ ] `test_get_risk_unknown_tier_when_risk_score_is_none` passes — `UNKNOWN` tier, empty `contributing_factors`
- [ ] `pytest --cov` reports ≥80% branch coverage across all 5 modules (TR-020)

---

## Definition of Done

- [ ] `test_risk_schemas.py` — 9 tier boundary tests pass
- [ ] `test_model_inference.py` — prediction flow, SHAP, label mapping tests pass
- [ ] `test_feature_extractor.py` — age, LOS, FHIR degradation, ICD-10 mapping tests pass
- [ ] `test_followup_care_agent.py` — A03 processing, DB write, AgentTask creation, retry tests pass
- [ ] `test_encounters_risk_router.py` — API HTTP 200/400/404/UNKNOWN tier tests pass
- [ ] ≥80% branch coverage confirmed via `pytest --cov` report
- [ ] Code peer-reviewed before merge
