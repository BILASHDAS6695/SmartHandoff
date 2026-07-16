# US-019 Implementation Tasks — Resolve Patient Identity from FHIR via MRN with Partial-Match Fallback

> **Epic:** EP-002 — EHR / FHIR Integration | **Sprint:** 2 | **Story Points:** 3  
> **Status:** Draft | **Date:** 2026-07-16

---

## Task Breakdown Summary

| Task ID | Title | Layer | Effort | Dependencies |
|---------|-------|-------|--------|--------------|
| TASK-001 | Implement Patient Models, Custom Exceptions, and FHIR Query Builders | Backend | 6 h | US-017 |
| TASK-002 | Implement PatientResolver Service with Cascading Resolution Logic | Backend | 8 h | TASK-001, US-017, US-018 |
| TASK-003 | Implement Encounter Status Management and Care Team Alert Dispatch | Backend | 6 h | TASK-002 |
| TASK-004 | Write Comprehensive Unit Tests for All Resolution Paths | Backend Testing | 4 h | TASK-001, TASK-002, TASK-003 |

**Total:** 24 hours = 3 story points ✓

---

## Task Descriptions

### TASK-001: Implement Patient Models, Custom Exceptions, and FHIR Query Builders
**Effort:** 6 h | **File:** [task_001_patient_models_exceptions_queries.md](task_001_patient_models_exceptions_queries.md)

**Scope:**
- Extend `PatientModel` with `resolution_method` and `partial_match` fields
- Create `ResolutionMethod` enum (MRN, NAME_DOB, UNRESOLVED)
- Create `PatientResolutionStatus` enum (RESOLVED, AMBIGUOUS, UNRESOLVED)
- Implement `PatientAmbiguousError` exception class
- Implement `PatientNotFoundWarning` warning class
- Create FHIR query builder functions for MRN and name+DOB lookups
- Add configurable `FHIR_MRN_SYSTEM_URI` to settings

**Acceptance Criteria Addressed:**
- AC Scenario 1 (resolution_method field)
- AC Scenario 2 (partial_match field)
- AC Scenario 3 (PatientAmbiguousError exception)
- AC Scenario 4 (PatientNotFoundWarning)

**Files Created:**
- `backend/app/models/patient.py` (or extend existing)
- `backend/app/core/fhir/exceptions.py` (extend with patient exceptions)
- `backend/app/core/fhir/queries.py`

**Files Modified:**
- `backend/app/core/config.py` (FHIR_MRN_SYSTEM_URI setting)
- `backend/app/models/encounter.py` (patient_resolution_status field)

---

### TASK-002: Implement PatientResolver Service with Cascading Resolution Logic
**Effort:** 8 h | **File:** [task_002_patient_resolver_service.md](task_002_patient_resolver_service.md)

**Scope:**
- Create `PatientResolver` service class in `backend/app/services/patient_resolver.py`
- Implement `resolve_patient(mrn: str, name: dict, dob: str)` method
- Primary MRN lookup: `Patient?identifier={system}|{mrn}`
- Name+DOB fallback: `Patient?family={name}&birthdate={dob}`
- Ambiguous match detection (count > 1) → raise `PatientAmbiguousError`
- Unresolvable case (count == 0) → return `None` with warning log
- Integration with `FHIRClient` from US-017 with resilience wrappers from US-018
- Logging: WARNING for partial matches, CRITICAL for unresolvable patients

**Acceptance Criteria Addressed:**
- AC Scenario 1 (MRN primary lookup)
- AC Scenario 2 (name+DOB fallback)
- AC Scenario 3 (ambiguous detection)
- AC Scenario 4 (unresolvable handling)

**Files Created:**
- `backend/app/services/patient_resolver.py`
- `backend/app/services/__init__.py` (if not exists)

**Files Modified:**
- None (new service)

---

### TASK-003: Implement Encounter Status Management and Care Team Alert Dispatch
**Effort:** 6 h | **File:** [task_003_encounter_status_alert_dispatch.md](task_003_encounter_status_alert_dispatch.md)

**Scope:**
- Update `Encounter` model with `patient_resolution_status` field (enum)
- Modify encounter creation logic to accept resolution status
- Implement care team alert dispatch via Pub/Sub `notification-requests` topic
- Alert payload: `{type: "PATIENT_RESOLUTION_ALERT", status: "AMBIGUOUS"|"UNRESOLVED", encounter_id, mrn, name, dob}`
- Implement agent task status update: set `status=BLOCKED` for ambiguous/unresolved encounters
- Integration with existing Pub/Sub publisher from EP-013 infra

**Acceptance Criteria Addressed:**
- AC Scenario 3 (care team alert for ambiguous)
- AC Scenario 4 (partial encounter creation with UNRESOLVED status, blocked agent tasks)

**Files Created:**
- `backend/app/services/care_team_alerts.py`

**Files Modified:**
- `backend/app/models/encounter.py` (patient_resolution_status field)
- `backend/app/services/encounter_service.py` (status handling)
- `backend/app/models/agent_task.py` (BLOCKED status if not exists)

---

### TASK-004: Write Comprehensive Unit Tests for All Resolution Paths
**Effort:** 4 h | **File:** [task_004_unit_tests_patient_resolution.md](task_004_unit_tests_patient_resolution.md)

**Scope:**
- Test suite for PatientResolver with mocked FHIR responses (12 tests)
  - Test MRN resolution success (AC1)
  - Test name+DOB fallback success (AC2)
  - Test ambiguous match detection and exception (AC3)
  - Test unresolvable patient handling (AC4)
  - Test FHIR client integration errors
  - Test logging output
- Test suite for care team alert dispatch (4 tests)
  - Test AMBIGUOUS alert sent
  - Test UNRESOLVED alert sent
  - Test Pub/Sub integration
- Test suite for encounter status management (4 tests)
  - Test encounter created with RESOLVED status
  - Test encounter created with AMBIGUOUS status
  - Test encounter created with UNRESOLVED status
  - Test agent tasks blocked for unresolved
- Mock FHIR API with `respx`
- Mock Pub/Sub with `unittest.mock`
- Achieve ≥90% code coverage

**Acceptance Criteria Addressed:**
- All AC scenarios validated via unit tests

**Files Created:**
- `backend/tests/unit/services/__init__.py`
- `backend/tests/unit/services/test_patient_resolver.py`
- `backend/tests/unit/services/test_care_team_alerts.py`

---

## Acceptance Criteria Coverage Matrix

| AC Scenario | TASK-001 | TASK-002 | TASK-003 | TASK-004 |
|-------------|----------|----------|----------|----------|
| AC1: Patient resolved by MRN on first attempt | ✓ (model) | ✓ (logic) | | ✓ (test) |
| AC2: Patient resolved by name+DOB fallback | ✓ (model) | ✓ (logic) | | ✓ (test) |
| AC3: Multiple name+DOB matches → ambiguous | ✓ (exception) | ✓ (detection) | ✓ (alert) | ✓ (test) |
| AC4: Unresolvable patient → partial encounter | ✓ (warning) | ✓ (handling) | ✓ (status) | ✓ (test) |

---

## Definition of Done Checklist

### US-019 Overall DoD

- [ ] `PatientResolver` service class with `resolve_patient(mrn, name, dob)` method (TASK-002)
- [ ] MRN primary lookup: `Patient?identifier={mrn_system}|{mrn}` (TASK-001, TASK-002)
- [ ] Name+DOB fallback: `Patient?family={name}&birthdate={dob}` (TASK-001, TASK-002)
- [ ] Ambiguous resolution: multiple matches → `PatientAmbiguousError` + care team alert (TASK-002, TASK-003)
- [ ] Unresolvable: zero matches → partial encounter with `UNRESOLVED` status (TASK-002, TASK-003)
- [ ] `resolution_method` and `partial_match` fields added to `PatientModel` (TASK-001)
- [ ] Unit tests covering all 4 resolution paths (TASK-004)
- [ ] Code reviewed and approved (All tasks)

---

## Implementation Order

```
TASK-001 (Foundation: models, exceptions, query builders)
    ↓
TASK-002 (PatientResolver service with cascading logic)
    ↓
TASK-003 (Encounter status management + alert dispatch)
    ↓
TASK-004 (Comprehensive unit tests for all paths)
```

---

## Technical Notes

### Module Structure
```
backend/app/
├── models/
│   ├── patient.py               # PatientModel with resolution fields
│   └── encounter.py             # patient_resolution_status field
├── core/fhir/
│   ├── exceptions.py            # PatientAmbiguousError, PatientNotFoundWarning
│   └── queries.py               # FHIR query builders
├── services/
│   ├── patient_resolver.py      # PatientResolver service
│   ├── care_team_alerts.py      # Alert dispatch via Pub/Sub
│   └── encounter_service.py     # Encounter creation with status
```

### Test Structure
```
backend/tests/unit/services/
├── __init__.py
├── test_patient_resolver.py     # 12 tests for resolution logic
└── test_care_team_alerts.py     # 4 tests for alert dispatch
```

### FHIR Query Examples

**MRN Lookup:**
```
GET {FHIR_BASE_URL}/Patient?identifier=http://hospital.org/mrn|MRN-789
```

**Name+DOB Fallback:**
```
GET {FHIR_BASE_URL}/Patient?family=Smith&birthdate=1980-01-15
```

### Care Team Alert Payload

```json
{
  "type": "PATIENT_RESOLUTION_ALERT",
  "priority": "HIGH",
  "status": "AMBIGUOUS",
  "encounter_id": "enc-12345",
  "mrn": "MRN-789",
  "name": {"family": "Smith", "given": "John"},
  "dob": "1980-01-15",
  "match_count": 3,
  "message": "Manual resolution required: 3 matching patients found",
  "timestamp": "2026-07-16T10:30:00Z"
}
```

### Configuration

Add to `backend/app/core/config.py`:
```python
class Settings(BaseSettings):
    # ... existing settings ...
    
    # FHIR Patient Resolution
    FHIR_MRN_SYSTEM_URI: str = Field(
        default="http://hospital.org/mrn",
        description="FHIR identifier system URI for MRN"
    )
```

### Enum Definitions

```python
from enum import Enum

class ResolutionMethod(str, Enum):
    MRN = "MRN"
    NAME_DOB = "NAME_DOB"
    UNRESOLVED = "UNRESOLVED"

class PatientResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"
```

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-017 | Story | FHIR fetch infrastructure required |
| US-018 | Story | Resilience wrappers needed for all FHIR calls |
| AIR-014 | Requirement | FHIR R4 integration architecture |
| FR-003 | Requirement | Patient identity resolution functional requirement |
| DR-024 | Requirement | Patient data model requirements |

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Multiple EHR MRN system URIs | High | High | Make `FHIR_MRN_SYSTEM_URI` configurable per environment |
| Name matching false positives | Medium | High | Log all name+DOB fallback matches with WARNING level; require manual review |
| FHIR server returns partial Patient resources | Medium | Medium | Validate required fields (family, given, birthdate) in query response parser |
| Alert dispatch failures block encounter creation | Low | High | Make alert dispatch async and non-blocking; retry via dead-letter queue |
| Race condition on concurrent patient lookups | Low | Low | PatientResolver is stateless; each request independent |

---

## Future Enhancements (Out of Scope for US-019)

- **Fuzzy name matching:** Levenshtein distance for misspelled names (requires NLP library)
- **Patient merge handling:** When EHR merges duplicate patients, update historical encounters
- **Multi-identifier support:** Some hospitals use both MRN and SSN; support multiple identifier lookups
- **Patient resolution confidence score:** ML model to score match quality for manual review prioritization
- **Automated patient creation:** For truly new patients (ED trauma arrivals), create placeholder patient record

---

## Validation

### Manual End-to-End Test

After completing all tasks, validate the full resolution flow:

```bash
# Set test credentials
export FHIR_BASE_URL="https://test-ehr.example.com/fhir"
export FHIR_MRN_SYSTEM_URI="http://test-hospital.org/mrn"

# Run Python test script
python -c "
import asyncio
from app.services.patient_resolver import PatientResolver

async def test():
    resolver = PatientResolver()
    
    # Test 1: MRN resolution
    patient1 = await resolver.resolve_patient(
        mrn='MRN-789',
        name={'family': 'Smith', 'given': 'John'},
        dob='1980-01-15'
    )
    assert patient1.resolution_method == 'MRN'
    print('✓ Test 1: MRN resolution passed')
    
    # Test 2: Name+DOB fallback
    patient2 = await resolver.resolve_patient(
        mrn='MRN-INVALID',
        name={'family': 'Doe', 'given': 'Jane'},
        dob='1990-05-20'
    )
    assert patient2.resolution_method == 'NAME_DOB'
    assert patient2.partial_match == True
    print('✓ Test 2: Name+DOB fallback passed')
    
    print('✓ All resolution paths validated successfully')

asyncio.run(test())
"
```

Expected output:
```
WARNING: MRN lookup failed for MRN-INVALID, attempting name+DOB fallback
✓ Test 1: MRN resolution passed
✓ Test 2: Name+DOB fallback passed
✓ All resolution paths validated successfully
```

---

## Questions for Product Owner

1. **MRN system URI:** What is the production FHIR identifier system URI for MRN (e.g., `http://hospital.org/mrn`)?
2. **Name matching rules:** Should we match on `family` name only, or include `given` name in fallback query?
3. **Care team notification:** Who should receive ambiguous/unresolved patient alerts (charge nurse, bed coordinator, IT helpdesk)?
4. **Manual resolution workflow:** What UI workflow should clinical staff use to resolve ambiguous patients (future story)?
5. **Patient creation policy:** Should the system ever auto-create patient records for unresolvable cases, or always require manual EHR entry?

---

*Tasks generated on 2026-07-16 from US-019 acceptance criteria by plan-development-tasks workflow.*
