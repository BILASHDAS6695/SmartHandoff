# TASK-006: Unit Tests — 15+ Medication Fixtures Covering All Reconciliation Categories

> **Story:** US-030 | **Effort:** 4 hours | **Layer:** Backend — Testing  
> **Status:** Draft | **Date:** 2026-07-16

---

## Objective

Write a comprehensive unit test suite with 15+ parameterised medication fixtures that validates all reconciliation categories, flag detection logic, RxNorm normalisation cache, dose parsing, FHIR parsing, and the API endpoint responses.

---

## Context

The reconciliation logic in TASK-004 covers multiple categorisation paths and two flag types. Each path must be regression-tested with realistic drug fixture data. This task also verifies that the API endpoint (TASK-005) maps ORM records to response schemas correctly under all conditions.

**Upstream Dependencies:**
- TASK-001: Enums and Pydantic schemas
- TASK-003: `DoseParser`, `RxNormNormaliser`
- TASK-004: `MedicationReconciliationAgent` comparison and detection logic
- TASK-005: FastAPI endpoint

---

## Scope

### In Scope

1. **`test_medication_models.py`** — `backend/tests/unit/models/test_medication.py`:
   - Enum value validation
   - `MedicationReconciliationResult` schema serialisation

2. **`test_dose_parser.py`** — `backend/tests/unit/agents/medication_reconciliation/test_dose_parser.py`:
   - 5 parameterised cases covering common dose formats

3. **`test_rxnorm_normaliser.py`** — `backend/tests/unit/agents/medication_reconciliation/test_rxnorm_normaliser.py`:
   - Cache hit prevents second HTTP call
   - Unknown drug returns `None`
   - Timeout returns `None`

4. **`test_reconciliation_agent.py`** — `backend/tests/unit/agents/medication_reconciliation/test_reconciliation_agent.py`:
   - 15+ fixtures covering: CONTINUED, NEW, STOPPED, DOSE_CHANGED, DUPLICATE, STOPPED_WITHOUT_ORDER
   - `_compare` method parameterised tests
   - `_detect_duplicates` edge cases
   - `_detect_missing_chronic` with and without stop order

5. **`test_reconciliation_endpoint.py`** — `backend/tests/unit/api/test_reconciliation_endpoint.py`:
   - 200 with populated results
   - 202 for pending reconciliation
   - 404 for unknown encounter
   - 403 for patient role

### Out of Scope

- Integration tests against live FHIR server
- E2E test (covered by separate test plan)

---

## Acceptance Criteria

### AC1: 15+ Medication Fixtures
**Given** the test file for the reconciliation agent  
**When** tests are run  
**Then** at least 15 distinct medication fixture scenarios are exercised across all `ReconciliationCategory` values and both `ReconciliationFlag` types

### AC2: All Categories Covered
**Given** the test suite  
**When** all tests pass  
**Then** `CONTINUED`, `NEW`, `STOPPED`, `DOSE_CHANGED`, `DUPLICATE`, and `STOPPED_WITHOUT_ORDER` are each validated by at least one test

### AC3: Cache Test Passes
**Given** `RxNormNormaliser`  
**When** the same drug name is normalised twice with different cases  
**Then** the HTTP client is called exactly once

### AC4: API Endpoint Tests Pass
**Given** the FastAPI test client  
**When** 200, 202, 403, 404 scenarios are tested  
**Then** all assertions on status code, response body, and headers pass

---

## Implementation Details

### File: `backend/tests/unit/agents/medication_reconciliation/test_reconciliation_agent.py`

```python
"""Unit tests for MedicationReconciliationAgent comparison logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.medication_reconciliation.agent import MedicationReconciliationAgent
from app.agents.medication_reconciliation.models import RawMedicationEntry
from app.models.medication import (
    MedicationListSource,
    ReconciliationCategory,
    ReconciliationFlag,
    Medication,
)

PRE_ADMIT = MedicationListSource.PRE_ADMIT
INPATIENT = MedicationListSource.INPATIENT
DISCHARGE = MedicationListSource.DISCHARGE


def make_agent() -> MedicationReconciliationAgent:
    return MedicationReconciliationAgent(
        fhir_fetcher=AsyncMock(),
        normaliser=AsyncMock(),
        session=AsyncMock(),
    )


def make_entry(
    source: MedicationListSource,
    name: str,
    dose_string: str | None = None,
    route: str | None = "oral",
    cui: str | None = None,
) -> RawMedicationEntry:
    entry = RawMedicationEntry(
        source=source,
        fhir_id=f"{source.value}-{name[:4]}",
        name=name,
        dose_string=dose_string,
        route=route,
    )
    entry.rxnorm_cui = cui
    from app.agents.medication_reconciliation.dose_parser import parse_dose
    entry.dose_value, entry.dose_unit = parse_dose(dose_string)
    return entry


# ── Fixture definitions ────────────────────────────────────────────────────────

FIXTURES = [
    # id, description, pre_admit, discharge, expected_category
    pytest.param(
        [make_entry(PRE_ADMIT, "Metformin 500mg", "500 mg", "oral", "860975")],
        [make_entry(DISCHARGE, "Metformin 500mg", "500 mg", "oral", "860975")],
        ReconciliationCategory.CONTINUED,
        id="fixture-01-continued-same-dose",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Lisinopril 5mg", "5 mg", "oral", "203644")],
        [make_entry(DISCHARGE, "Lisinopril 5mg", "5 mg", "oral", "203644")],
        ReconciliationCategory.CONTINUED,
        id="fixture-02-continued-lisinopril",
    ),
    pytest.param(
        [],
        [make_entry(DISCHARGE, "Apixaban 5mg", "5 mg", "oral", "1364430")],
        ReconciliationCategory.NEW,
        id="fixture-03-new-apixaban",
    ),
    pytest.param(
        [],
        [make_entry(DISCHARGE, "Pantoprazole 40mg", "40 mg", "oral", "40790")],
        ReconciliationCategory.NEW,
        id="fixture-04-new-pantoprazole",
    ),
    pytest.param(
        [],
        [make_entry(DISCHARGE, "Enoxaparin 40mg", "40 mg", "subcutaneous", "67108")],
        ReconciliationCategory.NEW,
        id="fixture-05-new-enoxaparin-subcutaneous",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Atorvastatin 40mg", "40 mg", "oral", "617310")],
        [],
        ReconciliationCategory.STOPPED,
        id="fixture-06-stopped-atorvastatin",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Warfarin 5mg", "5 mg", "oral", "855332")],
        [],
        ReconciliationCategory.STOPPED,
        id="fixture-07-stopped-warfarin",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Metoprolol 25mg", "25 mg", "oral", "866514")],
        [make_entry(DISCHARGE, "Metoprolol 50mg", "50 mg", "oral", "866514")],
        ReconciliationCategory.DOSE_CHANGED,
        id="fixture-08-dose-changed-metoprolol",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Amlodipine 5mg", "5 mg", "oral", "329526")],
        [make_entry(DISCHARGE, "Amlodipine 10mg", "10 mg", "oral", "329526")],
        ReconciliationCategory.DOSE_CHANGED,
        id="fixture-09-dose-changed-amlodipine",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Furosemide 20mg", "20 mg", "oral", "310429")],
        [make_entry(DISCHARGE, "Furosemide 40mg", "40 mg", "oral", "310429")],
        ReconciliationCategory.DOSE_CHANGED,
        id="fixture-10-dose-changed-furosemide",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Omeprazole 20mg", "20 mg", "oral", "40790")],
        [make_entry(DISCHARGE, "Omeprazole 20mg", "20 mg", "oral", "40790")],
        ReconciliationCategory.CONTINUED,
        id="fixture-11-continued-omeprazole",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Aspirin 81mg", "81 mg", "oral", "243670")],
        [make_entry(DISCHARGE, "Aspirin 81mg", "81 mg", "oral", "243670")],
        ReconciliationCategory.CONTINUED,
        id="fixture-12-continued-aspirin",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Sertraline 50mg", "50 mg", "oral", "36437")],
        [],
        ReconciliationCategory.STOPPED,
        id="fixture-13-stopped-sertraline",
    ),
    pytest.param(
        [],
        [make_entry(DISCHARGE, "Dalteparin 5000 units", "5000 units", "subcutaneous", "67108")],
        ReconciliationCategory.NEW,
        id="fixture-14-new-dalteparin",
    ),
    pytest.param(
        [make_entry(PRE_ADMIT, "Levothyroxine 50mcg", "50 mcg", "oral", "10582")],
        [make_entry(DISCHARGE, "Levothyroxine 100mcg", "100 mcg", "oral", "10582")],
        ReconciliationCategory.DOSE_CHANGED,
        id="fixture-15-dose-changed-levothyroxine",
    ),
]


@pytest.mark.parametrize("pre,dis,expected_category", FIXTURES)
def test_compare_categories(pre, dis, expected_category):
    agent = make_agent()
    raw = {PRE_ADMIT: pre, INPATIENT: [], DISCHARGE: dis}
    meds = agent._compare(raw)
    assert len(meds) > 0
    assert any(m.reconciliation_category == expected_category for m in meds), (
        f"Expected {expected_category} but got {[m.reconciliation_category for m in meds]}"
    )


def test_duplicate_detection_same_cui_same_route():
    agent = make_agent()
    med1 = Medication(
        name="Metformin 500mg oral", rxnorm_cui="860975", route="oral",
        sources=[DISCHARGE], flags=[]
    )
    med2 = Medication(
        name="Metformin XR 500mg oral", rxnorm_cui="860975", route="oral",
        sources=[DISCHARGE], flags=[]
    )
    agent._detect_duplicates([med1, med2])
    assert ReconciliationFlag.DUPLICATE in med1.flags
    assert ReconciliationFlag.DUPLICATE in med2.flags


def test_duplicate_detection_different_route_not_flagged():
    agent = make_agent()
    med1 = Medication(
        name="Metformin 500mg oral", rxnorm_cui="860975", route="oral",
        sources=[DISCHARGE], flags=[]
    )
    med2 = Medication(
        name="Metformin 500mg IV", rxnorm_cui="860975", route="intravenous",
        sources=[DISCHARGE], flags=[]
    )
    agent._detect_duplicates([med1, med2])
    assert ReconciliationFlag.DUPLICATE not in med1.flags
    assert ReconciliationFlag.DUPLICATE not in med2.flags


def test_single_discharge_med_not_flagged_as_duplicate():
    agent = make_agent()
    med = Medication(
        name="Lisinopril 10mg", rxnorm_cui="203644", route="oral",
        sources=[DISCHARGE], flags=[]
    )
    agent._detect_duplicates([med])
    assert ReconciliationFlag.DUPLICATE not in med.flags


@pytest.mark.asyncio
async def test_detect_missing_chronic_no_stop_order():
    agent = make_agent()
    agent._check_stop_order = AsyncMock(return_value=False)
    stopped_med = Medication(
        name="Atorvastatin 40mg",
        reconciliation_category=ReconciliationCategory.STOPPED,
        flags=[],
        sources=[PRE_ADMIT],
    )
    await agent._detect_missing_chronic([stopped_med], "enc-123")
    assert ReconciliationFlag.STOPPED_WITHOUT_ORDER in stopped_med.flags


@pytest.mark.asyncio
async def test_detect_missing_chronic_with_stop_order():
    agent = make_agent()
    agent._check_stop_order = AsyncMock(return_value=True)
    stopped_med = Medication(
        name="Warfarin 5mg",
        reconciliation_category=ReconciliationCategory.STOPPED,
        flags=[],
        sources=[PRE_ADMIT],
    )
    await agent._detect_missing_chronic([stopped_med], "enc-456")
    assert ReconciliationFlag.STOPPED_WITHOUT_ORDER not in stopped_med.flags
```

### File: `backend/tests/unit/agents/medication_reconciliation/test_dose_parser.py`

```python
"""Unit tests for DoseParser utility."""

import pytest
from app.agents.medication_reconciliation.dose_parser import parse_dose


@pytest.mark.parametrize("dose_string, expected_value, expected_unit", [
    ("500 mg", 500.0, "mg"),
    ("2.5mg", 2.5, "mg"),
    ("1000 MG", 1000.0, "mg"),
    ("5000 units", 5000.0, "units"),
    ("50 mcg", 50.0, "mcg"),
])
def test_parse_dose_valid(dose_string, expected_value, expected_unit):
    value, unit = parse_dose(dose_string)
    assert value == expected_value
    assert unit == expected_unit


@pytest.mark.parametrize("dose_string", [
    "as directed",
    "one tablet",
    "",
    None,
])
def test_parse_dose_invalid_returns_none(dose_string):
    value, unit = parse_dose(dose_string)
    assert value is None
    assert unit is None
```

### File: `backend/tests/unit/agents/medication_reconciliation/test_rxnorm_normaliser.py`

```python
"""Unit tests for RxNormNormaliser."""

import pytest
from unittest.mock import AsyncMock, patch
from app.agents.medication_reconciliation.rxnorm import RxNormNormaliser


@pytest.mark.asyncio
async def test_cache_prevents_duplicate_http_call():
    normaliser = RxNormNormaliser()
    with patch.object(normaliser, "_fetch_cui", new_callable=AsyncMock, return_value="12345") as mock:
        await normaliser.normalise("Metformin")
        await normaliser.normalise("metformin")  # same key after lowercasing
        assert mock.call_count == 1, "Cache did not prevent duplicate HTTP call"


@pytest.mark.asyncio
async def test_unknown_drug_returns_none():
    normaliser = RxNormNormaliser()
    with patch.object(normaliser, "_fetch_cui", new_callable=AsyncMock, return_value=None):
        result = await normaliser.normalise("Fictionomycin 200mg")
        assert result is None


@pytest.mark.asyncio
async def test_timeout_returns_none():
    import httpx
    normaliser = RxNormNormaliser()
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value = mock_client
        result = await normaliser._fetch_cui("Atorvastatin")
        assert result is None
```

### File: `backend/tests/unit/api/test_reconciliation_endpoint.py`

```python
"""Unit tests for GET /api/v1/encounters/{id}/medications/reconciliation."""

import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app

client = TestClient(app)

PHARMACIST_JWT = "Bearer test-pharmacist-jwt"
PATIENT_JWT = "Bearer test-patient-jwt"


def test_endpoint_returns_200_with_results(mock_auth_pharmacist, mock_reconciliation_results):
    response = client.get(
        f"/api/v1/encounters/{uuid4()}/medications/reconciliation",
        headers={"Authorization": PHARMACIST_JWT},
    )
    assert response.status_code == 200
    data = response.json()
    assert "medications" in data
    assert "total_medications" in data


def test_endpoint_returns_404_for_unknown_encounter(mock_auth_pharmacist):
    with patch(
        "app.repositories.encounter_repository.get_encounter_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = client.get(
            f"/api/v1/encounters/{uuid4()}/medications/reconciliation",
            headers={"Authorization": PHARMACIST_JWT},
        )
    assert response.status_code == 404


def test_endpoint_returns_202_for_pending_reconciliation(mock_auth_pharmacist, mock_encounter):
    with patch(
        "app.repositories.medication_repository.get_reconciliation_results",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.repositories.medication_repository.get_reconciliation_completed_at",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = client.get(
            f"/api/v1/encounters/{uuid4()}/medications/reconciliation",
            headers={"Authorization": PHARMACIST_JWT},
        )
    assert response.status_code == 202


def test_endpoint_returns_403_for_patient_role(mock_auth_patient):
    response = client.get(
        f"/api/v1/encounters/{uuid4()}/medications/reconciliation",
        headers={"Authorization": PATIENT_JWT},
    )
    assert response.status_code == 403
```

---

## Validation Steps

### Step 1: Run Full Test Suite
```bash
cd backend
pytest tests/unit/agents/medication_reconciliation/ tests/unit/api/test_reconciliation_endpoint.py \
  -v --tb=short
```

Expected: All tests pass with no warnings.

### Step 2: Coverage Check
```bash
cd backend
pytest tests/unit/agents/medication_reconciliation/ \
  --cov=app/agents/medication_reconciliation \
  --cov-report=term-missing
```

Expected: ≥80% line coverage on `agent.py`, `dose_parser.py`, `rxnorm.py`.

### Step 3: Fixture Count Verification
```bash
cd backend
pytest tests/unit/agents/medication_reconciliation/test_reconciliation_agent.py \
  --collect-only -q | grep "fixture-"
# Expected: 15+ fixture lines
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| PostgreSQL ARRAY types fail in SQLite-based tests | High | Medium | Mock repository layer; test agent logic independently of DB |
| `asyncio` event loop conflicts in pytest | Medium | Medium | Use `pytest-asyncio` with `asyncio_mode = "auto"` in `pytest.ini` |
| Fixture data uses retired CUIs | Low | Low | Test fixtures use mock CUIs; mark real CUI tests as `@pytest.mark.integration` |

---

## Definition of Done

- [ ] 15+ parameterised medication fixtures covering all `ReconciliationCategory` values
- [ ] `DUPLICATE` and `STOPPED_WITHOUT_ORDER` flags each covered by dedicated tests
- [ ] `DoseParser` tests: 5 valid + 4 invalid cases
- [ ] `RxNormNormaliser` cache, unknown-drug, and timeout tests pass
- [ ] API endpoint: 200, 202, 403, 404 scenarios tested
- [ ] `pytest` runs with 0 failures
- [ ] ≥80% coverage on agent module
- [ ] Code reviewed and approved

---

## Related Tasks

- **TASK-003:** `DoseParser` and `RxNormNormaliser` validated here
- **TASK-004:** `MedicationReconciliationAgent` comparison and detection logic validated here
- **TASK-005:** API endpoint behaviour validated here

---

## Notes for Implementer

1. **`pytest-asyncio`** — Add `asyncio_mode = "auto"` to `pytest.ini` or use `@pytest.mark.asyncio` decorator on each async test.
2. **Test isolation** — Use `AsyncMock` for all async collaborators; avoid hitting real DB or FHIR server in unit tests.
3. **Conftest fixtures** — Add `mock_auth_pharmacist`, `mock_auth_patient`, `mock_encounter`, `mock_reconciliation_results` to `conftest.py` for reuse across API tests.
4. **CUI values** — Fixture CUIs are illustrative; use any consistent string (e.g. `"CUI-001"`) in unit tests since RxNav is mocked.

---

*Task created on 2026-07-16 for US-030 by plan-development-tasks workflow.*
