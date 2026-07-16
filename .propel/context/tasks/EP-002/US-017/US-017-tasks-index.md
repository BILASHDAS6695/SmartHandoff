# US-017 Implementation Tasks — Fetch & Validate FHIR R4 Resources with Typed Pydantic Models

> **Epic:** EP-002 — EHR / FHIR Integration | **Sprint:** 1 | **Story Points:** 5  
> **Status:** Draft | **Date:** 2026-07-16

---

## Task Breakdown Summary

| Task ID | Title | Layer | Effort | Dependencies |
|---------|-------|-------|--------|--------------|
| TASK-001 | Create Pydantic Wrapper Models for 7 FHIR R4 Resource Types | Backend | 10 h | US-016 |
| TASK-002 | Implement FHIRClient with Async Resource Fetch Methods and Rate Limiting | Backend | 12 h | TASK-001, US-016 |
| TASK-003 | Implement Patient Resolution Logic with MRN Fallback to Name+DOB | Backend | 8 h | TASK-002 |
| TASK-004 | Write Comprehensive Unit Tests for FHIR Resource Fetching and Non-Persistence | Backend Testing | 10 h | TASK-001, TASK-002, TASK-003 |

**Total:** 40 hours = 5 story points ✓

---

## Task Descriptions

### TASK-001: Create Pydantic Wrapper Models for 7 FHIR R4 Resource Types
**Effort:** 10 h | **File:** [task_001_pydantic_fhir_models.md](task_001_pydantic_fhir_models.md)

**Scope:**
- Create `backend/app/core/fhir/models.py` module
- Implement Pydantic wrapper models for: `PatientModel`, `EncounterModel`, `MedicationStatementModel`, `MedicationAdministrationModel`, `MedicationRequestModel`, `AllergyIntoleranceModel`, `ConditionModel`
- Each model wraps `fhir.resources` base classes with custom validation
- Add `partial_match` and `resolution_method` fields to `PatientModel`
- Implement `FHIRValidationError` custom exception
- All models validated against FHIR R4 schemas

**Acceptance Criteria Addressed:**
- AC Scenario 1 (PatientModel with validated fields)
- AC Scenario 4 (FHIRValidationError on invalid resource)

**Files Created:**
- `backend/app/core/fhir/models.py`

**Files Modified:**
- `backend/app/core/fhir/__init__.py` (exports)
- `backend/requirements.txt` (fhir.resources if needed)

---

### TASK-002: Implement FHIRClient with Async Resource Fetch Methods and Rate Limiting
**Effort:** 12 h | **File:** [task_002_fhir_client_fetch_methods.md](task_002_fhir_client_fetch_methods.md)

**Scope:**
- Create `backend/app/core/fhir/client.py` module
- Implement `FHIRClient` class with `httpx.AsyncClient` and `FHIRAuthClient` integration
- Implement fetch methods: `get_encounter_by_id()`, `get_medication_statements()`, `get_medication_administrations()`, `get_medication_requests()`, `get_allergy_intolerances()`, `get_conditions()`
- Implement exponential backoff retry (3 attempts: 1s/2s/4s) with circuit breaker
- Implement token bucket rate limiter (100 req/min per instance) as decorator
- Parse FHIR Bundle responses and extract `entry[].resource`
- Return validated Pydantic models for all resources

**Acceptance Criteria Addressed:**
- AC Scenario 1 (fetch methods return typed models)
- AIR-011 (retry + circuit breaker)
- AIR-013 (rate limiting)

**Files Created:**
- `backend/app/core/fhir/client.py`
- `backend/app/core/fhir/rate_limiter.py`
- `backend/app/core/fhir/circuit_breaker.py`

**Files Modified:**
- `backend/app/core/fhir/__init__.py` (exports)

---

### TASK-003: Implement Patient Resolution Logic with MRN Fallback to Name+DOB
**Effort:** 8 h | **File:** [task_003_patient_resolution_mrn_fallback.md](task_003_patient_resolution_mrn_fallback.md)

**Scope:**
- Implement `get_patient_by_mrn()` in `FHIRClient`
- FHIR search: `Patient?identifier={system}|{mrn}` for MRN lookup
- On MRN not found: fallback to `Patient?family={name}&birthdate={dob}`
- Return `PatientModel` with `resolution_method` field (MRN / NAME_DOB / UNRESOLVED)
- Set `partial_match=True` for NAME_DOB resolution
- Log `PatientNotFoundWarning` if both resolution methods fail
- Return `None` if unresolvable

**Acceptance Criteria Addressed:**
- AC Scenario 1 (MRN returns PatientModel)
- AC Scenario 2 (MRN fallback to name+DOB)
- AIR-014 (patient resolution logic)

**Files Modified:**
- `backend/app/core/fhir/client.py` (add get_patient_by_mrn method)

---

### TASK-004: Write Comprehensive Unit Tests for FHIR Resource Fetching and Non-Persistence
**Effort:** 10 h | **File:** [task_004_unit_tests_fhir_client.md](task_004_unit_tests_fhir_client.md)

**Scope:**
- Create test suite for all 7 Pydantic models with FHIR R4 JSON fixtures (14 tests: valid + invalid per type)
- Create test suite for `FHIRClient` resource fetch methods (21 tests: 3 per resource type)
- Create test suite for patient resolution with MRN fallback (8 tests)
- Test rate limiter enforcement (4 tests)
- Test circuit breaker open/close behavior (4 tests)
- Test non-persistence: mock SQLAlchemy session and assert no `session.add()` calls (3 tests)
- Mock HTTP requests with `respx` (no real FHIR server calls)
- Achieve ≥90% code coverage for `app.core.fhir` module

**Acceptance Criteria Addressed:**
- AC Scenario 1 (test PatientModel validation)
- AC Scenario 2 (test MRN fallback)
- AC Scenario 3 (test non-persistence)
- AC Scenario 4 (test FHIRValidationError)

**Files Created:**
- `backend/tests/unit/core/fhir/test_models.py`
- `backend/tests/unit/core/fhir/test_client.py`
- `backend/tests/unit/core/fhir/test_patient_resolution.py`
- `backend/tests/fixtures/fhir_r4/` (JSON fixtures for all 7 resource types)

**Files Modified:**
- `backend/requirements-dev.txt` (test dependencies if needed)

---

## Acceptance Criteria Coverage Matrix

| AC Scenario | TASK-001 | TASK-002 | TASK-003 | TASK-004 |
|-------------|----------|----------|----------|----------|
| AC Scenario 1: Patient fetched by MRN returns typed PatientModel | ✓ (model) | | ✓ | ✓ (test) |
| AC Scenario 2: MRN not found falls back to name+DOB search | | | ✓ | ✓ (test) |
| AC Scenario 3: FHIR data not persisted to SmartHandoff DB | | | | ✓ (test) |
| AC Scenario 4: Invalid FHIR resource raises validation error | ✓ (exception) | | | ✓ (test) |

---

## Definition of Done Checklist

### US-017 Overall DoD

- [ ] `FHIRClient` fetch methods: `get_patient_by_mrn()`, `get_encounter_by_id()`, `get_medication_statements()`, `get_medication_administrations()`, `get_medication_requests()`, `get_allergy_intolerances()`, `get_conditions()` (TASK-002, TASK-003)
- [ ] Pydantic models: `PatientModel`, `EncounterModel`, `MedicationStatementModel`, `MedicationAdministrationModel`, `MedicationRequestModel`, `AllergyIntoleranceModel`, `ConditionModel` (TASK-001)
- [ ] All models validated against FHIR R4 resource schemas (using `fhir.resources` library) (TASK-001)
- [ ] Non-persistence enforced: unit tests confirm no ORM `session.add()` calls occur in FHIR fetch code paths (TASK-004)
- [ ] MRN fallback logic with `partial_match` flag (TASK-003)
- [ ] Unit tests with FHIR R4 JSON test fixtures for all 7 resource types (TASK-004)
- [ ] Code reviewed and approved (All tasks)

---

## Implementation Order

```
TASK-001 (Foundation: Pydantic wrapper models + FHIRValidationError)
    ↓
TASK-002 (FHIRClient with fetch methods, rate limiter, circuit breaker)
    ↓
TASK-003 (Patient resolution with MRN fallback logic)
    ↓
TASK-004 (Comprehensive unit tests + non-persistence validation)
```

---

## Technical Notes

### Module Structure
```
backend/app/core/fhir/
├── __init__.py              # Public exports
├── exceptions.py            # FHIRAuthenticationError (US-016)
├── discovery.py             # SMART discovery (US-016)
├── token_cache.py           # Token cache (US-016)
├── auth.py                  # FHIRAuthClient (US-016)
├── models.py                # Pydantic wrapper models (TASK-001)
├── rate_limiter.py          # Token bucket rate limiter (TASK-002)
├── circuit_breaker.py       # Circuit breaker pattern (TASK-002)
└── client.py                # FHIRClient with fetch methods (TASK-002, TASK-003)
```

### Test Structure
```
backend/tests/unit/core/fhir/
├── __init__.py
├── test_discovery.py           # US-016
├── test_token_cache.py         # US-016
├── test_auth.py                # US-016
├── test_models.py              # TASK-004: 14 tests (7 valid + 7 invalid)
├── test_client.py              # TASK-004: 25 tests (fetch + rate limit + circuit breaker)
└── test_patient_resolution.py  # TASK-004: 8 tests (MRN + fallback + unresolved)

backend/tests/fixtures/fhir_r4/
├── patient_valid.json
├── patient_invalid.json
├── encounter_valid.json
├── medication_statement_valid.json
└── ... (14 JSON fixtures total)
```

### FHIR Search Parameters

| Resource | Search Example |
|----------|----------------|
| Patient (MRN) | `GET /Patient?identifier=http://hospital.org/mrn\|MRN-001` |
| Patient (Name+DOB) | `GET /Patient?family=Smith&birthdate=1980-01-01` |
| Encounter | `GET /Encounter/{encounterId}` |
| MedicationStatement | `GET /MedicationStatement?patient={patientId}` |
| MedicationAdministration | `GET /MedicationAdministration?encounter={encounterId}` |
| MedicationRequest | `GET /MedicationRequest?patient={patientId}` |
| AllergyIntolerance | `GET /AllergyIntolerance?patient={patientId}` |
| Condition | `GET /Condition?patient={patientId}` |

### Rate Limiter Token Bucket

- **Capacity:** 100 tokens
- **Refill rate:** 100 tokens/min = 1.67 tokens/sec
- **Scope:** Per `FHIRClient` instance (per agent instance)
- **Behavior:** If bucket empty, sleep with exponential backoff (1s, 2s, 4s) then retry

### Circuit Breaker

- **Failure threshold:** 10 consecutive failures in 60s window
- **Open duration:** 120s
- **Half-open probe:** After 120s, allow 1 request to test if service recovered
- **Close:** If half-open probe succeeds, reset failure count and close circuit

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-016 | Story | FHIRAuthClient required for all FHIR API calls |
| fhir.resources | Package | FHIR R4 base model classes (Python) |
| httpx | Package | Already in tech stack (async HTTP client) |
| respx | Package | Already added for US-016 tests |

---

## Non-Persistence Enforcement

Per AIR-012 and Constraint C-03, FHIR resource data must **never** be written to SmartHandoff database tables. This constraint is enforced by:

1. **Code Review:** No `session.add()` calls in `app.core.fhir` module
2. **Unit Tests:** Mock SQLAlchemy session and assert `session.add.call_count == 0` after fetch operations
3. **Documentation:** All fetch methods include docstring note: "FHIR data returned in-memory only; never persisted to SmartHandoff DB"

### Agent Usage Pattern

```python
# In agent task execution:
from app.core.fhir import FHIRClient

async def process_admission(encounter_id: str):
    fhir_client = FHIRClient()
    
    # Fetch FHIR data (in-memory only)
    patient = await fhir_client.get_patient_by_mrn("MRN-001")
    medications = await fhir_client.get_medication_statements(patient.id)
    
    # Use data in agent logic (stays in memory)
    summary = generate_summary(patient, medications)
    
    # Only summary persisted to SmartHandoff DB, not raw FHIR data
    await db.documents.create(content=summary)
    
    # FHIR data garbage collected when agent task completes
```

---

## Architecture Integration Requirements Coverage

| AIR | Requirement | Implementation |
|-----|-------------|----------------|
| AIR-010 | FHIR authentication | US-016 (FHIRAuthClient) |
| AIR-011 | FHIR resource fetching | TASK-002 (retry + circuit breaker) |
| AIR-012 | FHIR data not persisted | TASK-004 (non-persistence tests) |
| AIR-013 | FHIR rate limiting | TASK-002 (token bucket decorator) |
| AIR-014 | FHIR patient resolution | TASK-003 (MRN fallback logic) |

---

## Validation Loops

Each task includes validation steps to confirm correct implementation before proceeding to the next task:

- **TASK-001:** Python import check, Pydantic model validation with valid/invalid FHIR R4 JSON
- **TASK-002:** Manual fetch test with mock FHIR server, rate limiter threshold test
- **TASK-003:** Patient resolution with MRN hit/miss scenarios
- **TASK-004:** Full pytest suite with ≥90% coverage report

---
