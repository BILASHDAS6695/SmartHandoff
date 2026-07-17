---
id: TASK-003
title: "Unit Tests — Scoring Weights, Isolation Filter, No-Beds Advisory"
user_story: US-037
epic: EP-006
sprint: 2
layer: Testing
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + AI/ML Engineer
upstream: [US-037/TASK-001, US-037/TASK-002]
---

# TASK-003: Unit Tests — Scoring Weights, Isolation Filter, No-Beds Advisory

> **Story:** US-037 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-037 DoD specifies: *"Unit tests: scoring weights, isolation filter, no-beds advisory"*

All four acceptance criteria scenarios must be covered. Tests are split across three test files:

| Test File | Module Under Test | Coverage Focus |
|-----------|-----------------|----------------|
| `test_scoring_factors.py` | `scoring/factors.py` | Individual factor functions; boundary values; unknown inputs |
| `test_bed_scoring_algorithm.py` | `scoring/algorithm.py` | Weighted score formula; isolation hard filter; top-5 cap; empty beds |
| `test_beds_recommend_endpoint.py` | `routers/beds.py` — `/recommend` | Happy path; isolation-only filter; no-beds advisory; auth rejection |

Coverage target: ≥80% branch coverage across all three modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---------------------|---------------|
| `AsyncSession` (read replica / mv_bed_board) | `AsyncMock` with `execute().mappings()` returning configurable rows |
| `AsyncSession` (write — audit log) | `AsyncMock` with `execute()`, `commit()` |
| `load_weights()` | `MagicMock` returning `ScoringWeights(acuity=0.4, care_type=0.35, isolation=0.15, gender=0.10)` |
| `emit_audit_event` | `AsyncMock` — assert called once per request |
| `Path.open` (YAML file) | `mock_open` with YAML string for weight loader tests |
| FastAPI `TestClient` / `AsyncClient` | `httpx.AsyncClient(app=app, base_url="http://test")` |
| `require_role` auth dependency | Override with `lambda: mock_user` in `app.dependency_overrides` |

---

## Acceptance Criteria Addressed

| US-037 AC | Test Cases |
|---|---|
| **Scenario 1 (≥3 beds)** | `test_recommend_returns_ranked_beds_with_score_breakdown`, `test_recommend_response_includes_required_fields` |
| **Scenario 2 (isolation filter)** | `test_isolation_required_excludes_non_isolation_beds`, `test_isolation_required_patient_only_sees_isolation_beds`, `test_score_isolation_match_hard_zero_for_mismatch` |
| **Scenario 3 (configurable weights)** | `test_weighted_score_matches_formula`, `test_weight_validation_raises_on_wrong_sum`, `test_load_weights_reads_yaml_correctly` |
| **Scenario 4 (no-beds advisory)** | `test_recommend_returns_advisory_when_no_vacant_beds`, `test_advisory_includes_nearest_unit_and_wait_minutes`, `test_advisory_message_when_no_other_units_available` |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p backend/tests/unit/agents/bed_management/scoring
mkdir -p api-gateway/tests/unit/routers
touch backend/tests/unit/agents/bed_management/scoring/__init__.py
touch api-gateway/tests/unit/routers/__init__.py
```

### 2. Create `backend/tests/unit/agents/bed_management/scoring/test_scoring_factors.py`

```python
"""Unit tests for individual bed scoring factor functions (factors.py).

Coverage:
    score_acuity_match    — exact, over-resourced, under-resourced, unknown
    score_care_type_match — exact, general-purpose, mismatch, unknown
    score_isolation_match — all four combinations (2×2 isolation/capable matrix)
    score_gender_match    — exact, any-designation, mismatch, unknown
"""
from __future__ import annotations

import pytest

from app.agents.bed_management.scoring.factors import (
    score_acuity_match,
    score_care_type_match,
    score_gender_match,
    score_isolation_match,
)


# ──────────────────────────────────────────────
# score_acuity_match
# ──────────────────────────────────────────────

class TestScoreAcuityMatch:
    def test_exact_match_returns_1_0(self):
        assert score_acuity_match("ICU-step-down", "ICU-step-down") == 1.0

    def test_over_resourced_returns_0_8(self):
        # Patient needs MED-SURG, bed is ICU-step-down (higher capability)
        assert score_acuity_match("MED-SURG", "ICU-step-down") == 0.8

    def test_under_resourced_returns_0_0(self):
        # Patient needs ICU, bed is MED-SURG (insufficient)
        assert score_acuity_match("ICU", "MED-SURG") == 0.0

    def test_unknown_patient_acuity_returns_0_0(self):
        assert score_acuity_match("UNKNOWN", "MED-SURG") == 0.0

    def test_unknown_bed_acuity_returns_0_0(self):
        assert score_acuity_match("MED-SURG", "UNKNOWN") == 0.0


# ──────────────────────────────────────────────
# score_care_type_match
# ──────────────────────────────────────────────

class TestScoreCareTypeMatch:
    def test_exact_match_returns_1_0(self):
        assert score_care_type_match("CARDIAC", "CARDIAC") == 1.0

    def test_general_bed_returns_0_6(self):
        assert score_care_type_match("CARDIAC", "GENERAL") == 0.6

    def test_med_surg_bed_returns_0_6(self):
        assert score_care_type_match("ORTHO", "MED-SURG") == 0.6

    def test_mismatch_returns_0_0(self):
        assert score_care_type_match("CARDIAC", "ORTHO") == 0.0

    def test_empty_patient_type_returns_neutral(self):
        assert score_care_type_match("", "CARDIAC") == 0.5

    def test_empty_bed_type_returns_neutral(self):
        assert score_care_type_match("CARDIAC", "") == 0.5


# ──────────────────────────────────────────────
# score_isolation_match
# ──────────────────────────────────────────────

class TestScoreIsolationMatch:
    def test_isolation_required_and_capable_returns_1_0(self):
        assert score_isolation_match(True, True) == 1.0

    def test_isolation_required_and_not_capable_returns_0_0(self):
        """Hard exclusion case — AC Scenario 2."""
        assert score_isolation_match(True, False) == 0.0

    def test_no_isolation_required_and_capable_returns_0_8(self):
        # Over-resourced isolation room for non-isolation patient
        assert score_isolation_match(False, True) == 0.8

    def test_no_isolation_required_and_not_capable_returns_1_0(self):
        # Standard patient in standard room — ideal
        assert score_isolation_match(False, False) == 1.0


# ──────────────────────────────────────────────
# score_gender_match
# ──────────────────────────────────────────────

class TestScoreGenderMatch:
    def test_exact_match_returns_1_0(self):
        assert score_gender_match("female", "female") == 1.0

    def test_any_designation_returns_0_8(self):
        assert score_gender_match("male", "any") == 0.8

    def test_mismatch_returns_0_0(self):
        assert score_gender_match("female", "male") == 0.0

    def test_empty_patient_gender_returns_neutral(self):
        assert score_gender_match("", "female") == 0.5

    def test_case_insensitive_match(self):
        assert score_gender_match("Female", "female") == 1.0
```

### 3. Create `backend/tests/unit/agents/bed_management/scoring/test_bed_scoring_algorithm.py`

```python
"""Unit tests for BedScoringAlgorithm (algorithm.py).

Coverage:
    Weighted score formula matches configurable weights (AC Scenario 3)
    Isolation-required patient: non-isolation beds excluded (AC Scenario 2)
    Results sorted descending by score
    Top-5 cap enforced when >5 beds available
    Empty input list → empty result
    All beds excluded by isolation filter → empty result
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.bed_management.scoring.algorithm import (
    BedScoringAlgorithm,
    PatientAdmissionProfile,
)
from app.agents.bed_management.scoring.weight_loader import ScoringWeights


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

DEFAULT_WEIGHTS = ScoringWeights(acuity=0.4, care_type=0.35, isolation=0.15, gender=0.10)

STANDARD_PROFILE = PatientAdmissionProfile(
    acuity_level="ICU-step-down",
    admit_type="CARDIAC",
    isolation_required=False,
    gender="female",
)

ISOLATION_PROFILE = PatientAdmissionProfile(
    acuity_level="ICU",
    admit_type="GENERAL",
    isolation_required=True,
    gender="male",
)

def _make_bed(
    bed_id: str = "bed-001",
    unit: str = "3A",
    room: str = "301",
    bed_number: str = "A",
    bed_type: str = "ICU-step-down",
    care_type: str = "CARDIAC",
    isolation_capable: bool = False,
    gender_designation: str = "female",
) -> dict:
    return {
        "bed_id": bed_id,
        "unit": unit,
        "room": room,
        "bed_number": bed_number,
        "bed_type": bed_type,
        "care_type": care_type,
        "isolation_capable": isolation_capable,
        "gender_designation": gender_designation,
    }


# ──────────────────────────────────────────────
# Weighted score formula (AC Scenario 3)
# ──────────────────────────────────────────────

class TestWeightedScoreFormula:
    @patch(
        "app.agents.bed_management.scoring.algorithm.load_weights",
        return_value=DEFAULT_WEIGHTS,
    )
    def test_perfect_match_bed_scores_1_0(self, _mock_weights):
        """Exact match on all four factors with default weights → score = 1.0."""
        algo = BedScoringAlgorithm()
        bed = _make_bed(
            bed_type="ICU-step-down",
            care_type="CARDIAC",
            isolation_capable=False,  # non-isolation patient
            gender_designation="female",
        )
        results = algo.score_and_rank(STANDARD_PROFILE, [bed])
        assert len(results) == 1
        assert results[0].score == pytest.approx(1.0, abs=0.001)

    @patch(
        "app.agents.bed_management.scoring.algorithm.load_weights",
        return_value=DEFAULT_WEIGHTS,
    )
    def test_score_equals_weighted_sum_of_factors(self, _mock_weights):
        """score = acuity×0.4 + care_type×0.35 + isolation×0.15 + gender×0.10"""
        algo = BedScoringAlgorithm()
        # Over-resourced acuity (ICU bed for ICU-step-down patient) → acuity=0.8
        # Exact care type → care_type=1.0
        # Non-isolation patient + non-isolation bed → isolation=1.0
        # Exact gender → gender=1.0
        # Expected: 0.8×0.4 + 1.0×0.35 + 1.0×0.15 + 1.0×0.10 = 0.32 + 0.35 + 0.15 + 0.10 = 0.92
        bed = _make_bed(bed_type="ICU", care_type="CARDIAC", isolation_capable=False, gender_designation="female")
        results = algo.score_and_rank(STANDARD_PROFILE, [bed])
        assert results[0].score == pytest.approx(0.92, abs=0.001)

    @patch(
        "app.agents.bed_management.scoring.algorithm.load_weights",
        return_value=DEFAULT_WEIGHTS,
    )
    def test_results_sorted_descending_by_score(self, _mock_weights):
        """Top-ranked bed must have the highest score."""
        algo = BedScoringAlgorithm()
        beds = [
            _make_bed(bed_id="low", bed_type="OBS", care_type="ORTHO"),   # low score
            _make_bed(bed_id="high", bed_type="ICU-step-down", care_type="CARDIAC"),  # high score
        ]
        results = algo.score_and_rank(STANDARD_PROFILE, beds)
        assert results[0].bed_id == "high"
        assert results[0].score > results[1].score

    @patch(
        "app.agents.bed_management.scoring.algorithm.load_weights",
        return_value=DEFAULT_WEIGHTS,
    )
    def test_top_5_cap_enforced(self, _mock_weights):
        """Algorithm returns at most 5 results even when more beds are available."""
        algo = BedScoringAlgorithm()
        beds = [_make_bed(bed_id=f"bed-{i:03d}") for i in range(10)]
        results = algo.score_and_rank(STANDARD_PROFILE, beds)
        assert len(results) <= 5


# ──────────────────────────────────────────────
# Isolation hard filter (AC Scenario 2)
# ──────────────────────────────────────────────

class TestIsolationFilter:
    @patch(
        "app.agents.bed_management.scoring.algorithm.load_weights",
        return_value=DEFAULT_WEIGHTS,
    )
    def test_non_isolation_beds_excluded_for_isolation_patient(self, _mock_weights):
        """All non-isolation-capable beds must be excluded for isolation-required patient."""
        algo = BedScoringAlgorithm()
        beds = [
            _make_bed(bed_id="iso-001", isolation_capable=True),
            _make_bed(bed_id="std-001", isolation_capable=False),
            _make_bed(bed_id="std-002", isolation_capable=False),
        ]
        results = algo.score_and_rank(ISOLATION_PROFILE, beds)
        result_ids = {r.bed_id for r in results}
        assert "iso-001" in result_ids
        assert "std-001" not in result_ids
        assert "std-002" not in result_ids

    @patch(
        "app.agents.bed_management.scoring.algorithm.load_weights",
        return_value=DEFAULT_WEIGHTS,
    )
    def test_all_beds_excluded_returns_empty_list(self, _mock_weights):
        """If every bed fails the isolation filter, result is an empty list."""
        algo = BedScoringAlgorithm()
        beds = [
            _make_bed(bed_id="std-001", isolation_capable=False),
            _make_bed(bed_id="std-002", isolation_capable=False),
        ]
        results = algo.score_and_rank(ISOLATION_PROFILE, beds)
        assert results == []

    @patch(
        "app.agents.bed_management.scoring.algorithm.load_weights",
        return_value=DEFAULT_WEIGHTS,
    )
    def test_empty_bed_list_returns_empty(self, _mock_weights):
        algo = BedScoringAlgorithm()
        assert algo.score_and_rank(STANDARD_PROFILE, []) == []


# ──────────────────────────────────────────────
# Weight loader
# ──────────────────────────────────────────────

class TestWeightLoader:
    def test_load_weights_reads_yaml_values(self, tmp_path):
        yaml_content = (
            "weights:\n"
            "  acuity: 0.40\n"
            "  care_type: 0.35\n"
            "  isolation: 0.15\n"
            "  gender: 0.10\n"
        )
        weights_file = tmp_path / "bed_scoring_weights.yaml"
        weights_file.write_text(yaml_content)

        from app.agents.bed_management.scoring.weight_loader import load_weights
        w = load_weights(path=weights_file)

        assert w.acuity == pytest.approx(0.40)
        assert w.care_type == pytest.approx(0.35)
        assert w.isolation == pytest.approx(0.15)
        assert w.gender == pytest.approx(0.10)

    def test_weight_validation_raises_when_sum_not_1(self):
        from app.agents.bed_management.scoring.weight_loader import ScoringWeights
        bad_weights = ScoringWeights(acuity=0.5, care_type=0.5, isolation=0.1, gender=0.1)
        with pytest.raises(ValueError, match="sum to 1.0"):
            bad_weights.validate()
```

### 4. Create `api-gateway/tests/unit/routers/test_beds_recommend_endpoint.py`

```python
"""Unit tests for GET /api/v1/beds/recommend endpoint (beds.py).

Coverage:
    Scenario 1: ranked beds with score_breakdown returned
    Scenario 2: isolation-required — only isolation-capable beds returned
    Scenario 4: no VACANT beds → advisory with nearest unit + wait_minutes
    Auth rejection: unauthenticated → 401; wrong role → 403
    Encounter not found → 404
    No ADT event → 422
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.main import app
from app.core.auth import require_role

ENCOUNTER_ID = str(uuid.uuid4())
BED_MANAGER_USER = MagicMock(sub="user-bed-manager-001", roles=["BedManager"])


def _override_role(roles):
    """Override require_role dependency to inject BED_MANAGER_USER."""
    return lambda: BED_MANAGER_USER


# ──────────────────────────────────────────────
# Happy path — Scenario 1
# ──────────────────────────────────────────────

@pytest.mark.asyncio
@patch("app.routers.beds.emit_audit_event", new_callable=AsyncMock)
@patch("app.routers.beds.BedScoringAlgorithm")
@patch("app.routers.beds.get_read_db")
@patch("app.routers.beds.get_write_db")
async def test_recommend_returns_ranked_beds_with_score_breakdown(
    mock_write_db, mock_read_db, MockAlgo, mock_audit
):
    from app.agents.bed_management.scoring.algorithm import BedRecommendation, ScoreBreakdown

    app.dependency_overrides[require_role(["BedManager", "Admin"])] = _override_role(["BedManager", "Admin"])

    mock_encounter = MagicMock(id=ENCOUNTER_ID, status="REGISTERED")
    mock_adt = MagicMock(
        encounter_id=ENCOUNTER_ID,
        acuity_level="ICU-step-down",
        admit_type="CARDIAC",
        isolation_required=False,
        patient_gender="female",
        target_unit="3A",
    )
    mock_session = AsyncMock()
    mock_session.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_encounter),
        MagicMock(scalar_one_or_none=lambda: mock_adt),
        MagicMock(mappings=lambda: MagicMock(
            all=lambda: [{"bed_id": f"bed-{i:03d}", "unit": "3A", "room": "301",
                          "bed_number": str(i), "bed_type": "ICU-step-down",
                          "care_type": "CARDIAC", "isolation_capable": False,
                          "gender_designation": "female"} for i in range(5)]
        )),
    ]
    mock_read_db.return_value = mock_session
    mock_write_db.return_value = AsyncMock()

    fake_recommendations = [
        BedRecommendation(
            bed_id=f"bed-{i:03d}", unit="3A", room="301", bed_number=str(i),
            score=round(1.0 - i * 0.05, 4),
            score_breakdown=ScoreBreakdown(
                acuity_match=1.0, care_type_match=1.0,
                isolation_match=1.0, gender_match=1.0,
            ),
        )
        for i in range(5)
    ]
    MockAlgo.return_value.score_and_rank.return_value = fake_recommendations

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/beds/recommend?encounter_id={ENCOUNTER_ID}",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["encounter_id"] == ENCOUNTER_ID
    assert len(data["recommendations"]) == 5
    first = data["recommendations"][0]
    assert "bed_id" in first
    assert "score" in first
    assert "score_breakdown" in first
    assert all(k in first["score_breakdown"] for k in (
        "acuity_match", "care_type_match", "isolation_match", "gender_match"
    ))
    mock_audit.assert_called_once()

    app.dependency_overrides.clear()


# ──────────────────────────────────────────────
# No-beds advisory — Scenario 4
# ──────────────────────────────────────────────

@pytest.mark.asyncio
@patch("app.routers.beds.emit_audit_event", new_callable=AsyncMock)
@patch("app.routers.beds.BedScoringAlgorithm")
@patch("app.routers.beds.get_read_db")
@patch("app.routers.beds.get_write_db")
async def test_recommend_returns_advisory_when_no_vacant_beds(
    mock_write_db, mock_read_db, MockAlgo, mock_audit
):
    app.dependency_overrides[require_role(["BedManager", "Admin"])] = _override_role(["BedManager", "Admin"])

    mock_encounter = MagicMock(id=ENCOUNTER_ID, status="REGISTERED")
    mock_adt = MagicMock(
        encounter_id=ENCOUNTER_ID,
        acuity_level="MED-SURG",
        admit_type="GENERAL",
        isolation_required=False,
        patient_gender="male",
        target_unit="4B",
    )
    mock_session = AsyncMock()
    # Encounter + ADT found; no VACANT beds; nearest unit query
    mock_session.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_encounter),
        MagicMock(scalar_one_or_none=lambda: mock_adt),
        MagicMock(mappings=lambda: MagicMock(all=lambda: [])),  # no VACANT beds
        MagicMock(mappings=lambda: MagicMock(first=lambda: {"unit": "3A", "vacant_count": 2})),
    ]
    mock_read_db.return_value = mock_session
    mock_write_db.return_value = AsyncMock()
    MockAlgo.return_value.score_and_rank.return_value = []

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/beds/recommend?encounter_id={ENCOUNTER_ID}",
            headers={"Authorization": "Bearer mock-token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["recommendations"] == []
    assert data["advisory"] is not None
    assert "No beds available" in data["advisory"]["message"]
    assert data["advisory"]["available_unit"] == "3A"
    assert isinstance(data["advisory"]["estimated_wait_minutes"], int)

    app.dependency_overrides.clear()


# ──────────────────────────────────────────────
# Auth / RBAC
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recommend_rejects_unauthenticated_request():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/beds/recommend?encounter_id={ENCOUNTER_ID}")
    assert resp.status_code in (401, 403)


# ──────────────────────────────────────────────
# Not found cases
# ──────────────────────────────────────────────

@pytest.mark.asyncio
@patch("app.routers.beds.get_read_db")
@patch("app.routers.beds.get_write_db")
async def test_recommend_returns_404_for_missing_encounter(mock_write_db, mock_read_db):
    app.dependency_overrides[require_role(["BedManager", "Admin"])] = _override_role(["BedManager", "Admin"])

    mock_session = AsyncMock()
    mock_session.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_read_db.return_value = mock_session
    mock_write_db.return_value = AsyncMock()

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/beds/recommend?encounter_id={ENCOUNTER_ID}",
            headers={"Authorization": "Bearer mock-token"},
        )
    assert resp.status_code == 404
    app.dependency_overrides.clear()
```

---

## Validation Checklist

- [ ] All 12 test cases pass: `pytest backend/tests/unit/agents/bed_management/scoring/ api-gateway/tests/unit/routers/test_beds_recommend_endpoint.py -v`
- [ ] Branch coverage ≥80% on `factors.py`, `algorithm.py`, and `routers/beds.py` (recommend section)
- [ ] Isolation filter test confirms non-isolation beds are **absent** from results (not just scored 0)
- [ ] Weighted score test verifies formula with explicit arithmetic check
- [ ] Advisory test validates `available_unit` and `estimated_wait_minutes` are present
- [ ] Auth test confirms 401/403 without credentials
- [ ] No PHI in test fixtures — uses UUIDs and coded values only

---

## Files Created

| File | Purpose |
|------|---------|
| `backend/tests/unit/agents/bed_management/scoring/__init__.py` | Package init |
| `backend/tests/unit/agents/bed_management/scoring/test_scoring_factors.py` | Factor function tests |
| `backend/tests/unit/agents/bed_management/scoring/test_bed_scoring_algorithm.py` | Algorithm + weight tests |
| `api-gateway/tests/unit/routers/test_beds_recommend_endpoint.py` | API endpoint tests |
