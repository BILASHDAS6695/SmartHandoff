---
id: TASK-006
title: "Code Review & DoD Sign-off — US-012 HL7 Parser & Event Router"
user_story: US-012
epic: EP-001
sprint: 1
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer + Security Engineer
upstream: [US-012/TASK-001, US-012/TASK-002, US-012/TASK-003, US-012/TASK-004, US-012/TASK-005]
---

# TASK-006: Code Review & DoD Sign-off — US-012 HL7 Parser & Event Router

> **Story:** US-012 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This is the final task for US-012. It verifies that all implementation tasks (TASK-001 through TASK-005) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story. The HL7 parser is the first point at which PHI fields (MRN, patient name, DOB, address) are extracted from HL7 messages and placed in-memory. Any logging bug here could cause PHI to leak into Cloud Logging in plaintext, violating HIPAA (BR-020).

Review focus areas beyond standard code quality:
1. **PHI log safety** — confirm no PHI appears in any `logger.*` call in `hl7_parser.py`, `router.py`, or `pipeline.py`.
2. **NACK correctness** — `HL7ValidationError` is raised (not swallowed) for all 4 failure scenarios.
3. **No direct exception to `Exception`** — parser must not catch bare `Exception` and swallow it silently.
4. **Pydantic strict mode** — `ADTEvent` uses `ConfigDict(strict=True)` to prevent type coercions.

---

## Pre-Review Validation Sequence

Run all checks from the `hl7-listener/` directory before requesting review:

```bash
cd hl7-listener

# -----------------------------------------------------------------------
# 1. Install dependencies
# -----------------------------------------------------------------------
pip install -r requirements.txt

# -----------------------------------------------------------------------
# 2. Syntax check — all parser modules
# -----------------------------------------------------------------------
python -c "
import ast, pathlib
for p in sorted(pathlib.Path('app/parser').rglob('*.py')):
    ast.parse(p.read_text())
    print(f'  {p}: OK')
print('Syntax check: PASSED')
"

# -----------------------------------------------------------------------
# 3. Import check — all public symbols
# -----------------------------------------------------------------------
python -c "
from app.parser import (
    ADTEvent, EventType, HL7ValidationError, HL7_TRIGGER_MAP,
    HL7Parser, ADTRouter, default_router, process_hl7_message
)
print('Import check: PASSED')
"

# -----------------------------------------------------------------------
# 4. Verify EventType enum completeness
# -----------------------------------------------------------------------
python -c "
from app.parser.models import EventType, HL7_TRIGGER_MAP
assert len(list(EventType)) == 8, f'Expected 8 EventType values, got {len(list(EventType))}'
assert len(HL7_TRIGGER_MAP) == 8, f'Expected 8 trigger mappings, got {len(HL7_TRIGGER_MAP)}'
expected_codes = {'A01','A02','A03','A04','A08','A11','A12','A13'}
assert set(HL7_TRIGGER_MAP.keys()) == expected_codes
print('EventType completeness: PASSED')
"

# -----------------------------------------------------------------------
# 5. Verify A01 parse (Scenario 1)
# -----------------------------------------------------------------------
python -c "
from app.parser.hl7_parser import HL7Parser
from app.parser.models import EventType

hl7_a01 = (
    'MSH|^~\&|EHR|HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG001|P|2.5\r'
    'EVN|A01|20260715095500\r'
    'PID|1||MRN-1001^^^HOSP^MR||Smith^John||19800115|M|||100 Oak Ave\r'
    'PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||ADM|||20260715095500||||||||||||||||||||ENC-9001\r'
    'PV2|||Chest pain\r'
)
parser = HL7Parser()
event = parser.parse(hl7_a01)
assert event.event_type == EventType.ADMIT
assert event.patient_mrn == 'MRN-1001'
assert event.encounter_id == 'ENC-9001'
assert event.admit_reason == 'Chest pain'
assert event.attending_provider is not None
print('Scenario 1 (A01 parse): PASSED')
print('repr (no PHI):', repr(event))
"

# -----------------------------------------------------------------------
# 6. Verify unknown event type raises HL7ValidationError (Scenario 3)
# -----------------------------------------------------------------------
python -c "
from app.parser.hl7_parser import HL7Parser
from app.parser.models import HL7ValidationError

hl7_a99 = (
    'MSH|^~\&|EHR|HOSP|SmartHandoff|HOSP|20260715100000||ADT^A99|MSG002|P|2.5\r'
    'EVN|A99|20260715095500\r'
    'PID|1||MRN-9999^^^HOSP^MR||Brown^Alice||19750505|F\r'
)
parser = HL7Parser()
try:
    parser.parse(hl7_a99)
    print('FAIL: No exception raised for A99')
    exit(1)
except HL7ValidationError as e:
    assert 'A99' in str(e), f'Expected A99 in error message, got: {e}'
    print('Scenario 3 (unknown event type → HL7ValidationError): PASSED')
"

# -----------------------------------------------------------------------
# 7. Verify missing PID raises HL7ValidationError (Scenario 4)
# -----------------------------------------------------------------------
python -c "
from app.parser.hl7_parser import HL7Parser
from app.parser.models import HL7ValidationError

hl7_no_pid = (
    'MSH|^~\&|EHR|HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG003|P|2.5\r'
    'EVN|A01|20260715095500\r'
    'PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||ADM|||20260715095500||||||||||||||||||||ENC-9001\r'
)
parser = HL7Parser()
try:
    parser.parse(hl7_no_pid)
    print('FAIL: No exception raised for missing PID')
    exit(1)
except HL7ValidationError as e:
    assert e.segment == 'PID', f'Expected segment=PID, got segment={e.segment}'
    print('Scenario 4 (missing PID → HL7ValidationError): PASSED')
"

# -----------------------------------------------------------------------
# 8. Verify default router has all 8 stub handlers
# -----------------------------------------------------------------------
python -c "
from app.parser.router import default_router
from app.parser.models import EventType
for et in EventType:
    assert default_router.is_registered(et), f'Missing handler for {et.value}'
print('Default router stub handlers: PASSED (8/8 event types registered)')
"

# -----------------------------------------------------------------------
# 9. Run full unit test suite with coverage
# -----------------------------------------------------------------------
pytest tests/unit/parser/ -v \
  --cov=app/parser/models \
  --cov=app/parser/hl7_parser \
  --cov=app/parser/router \
  --cov-report=term-missing \
  --cov-fail-under=80

# -----------------------------------------------------------------------
# 10. SAST scan — no HIGH or CRITICAL findings
# -----------------------------------------------------------------------
pip install bandit
bandit -r app/parser/ -ll --skip B101
# B101 skipped: assert only in test helpers and validation scripts, not production paths

# -----------------------------------------------------------------------
# 11. PHI log safety scan — confirm no PHI field names in log calls
# -----------------------------------------------------------------------
echo "=== Checking for PHI in log statements ==="
! grep -rn "patient_last_name\|patient_first_name\|patient_dob\|patient_address" \
    app/parser/hl7_parser.py app/parser/router.py app/parser/pipeline.py \
    | grep -i "log\." && echo "PHI log scan: PASSED" || echo "WARNING: Possible PHI in log statement"
```

---

## Code Review Checklist

### Functionality
- [ ] All 4 acceptance criteria scenarios validated by automated tests
- [ ] All 8 event type fixtures parse correctly (parametrised test passes)
- [ ] `HL7ValidationError` raised (not generic `Exception`) for all failure paths
- [ ] `process_hl7_message()` pipeline integrates parser + router end-to-end

### Security (HIPAA / BR-020)
- [ ] No PHI field names (`patient_mrn`, `patient_last_name`, `patient_first_name`, `patient_dob`, `patient_address`) appear in any `logger.*` call
- [ ] `ADTEvent.__repr__()` verified to exclude PHI
- [ ] `ADTEvent.safe_dict()` redacts all 5 PHI fields
- [ ] No bare `except Exception` that could swallow `HL7ValidationError`
- [ ] `hl7apy` parsing does not log raw HL7 messages (confirm hl7apy log level is WARNING or higher)

### Code Quality
- [ ] `HL7Parser` is stateless — no mutable instance state between `parse()` calls
- [ ] `ADTEvent` uses Pydantic v2 `ConfigDict(strict=True)` — no silent coercions
- [ ] `HL7_TRIGGER_MAP` and `_PV1_REQUIRED_TRIGGERS` are module-level constants (not computed per call)
- [ ] All `Optional[str]` fields default to `None` (not empty string)
- [ ] DG1 multi-segment iteration is resilient to missing `DG1-3` component

### Testing
- [ ] ≥80% branch coverage on `models.py`, `hl7_parser.py`, `router.py`
- [ ] Parametrised test covers all 8 event types
- [ ] Each of the 4 acceptance criteria scenarios has a dedicated test class or function
- [ ] Test fixtures use synthetic PHI only (no real patient data)
- [ ] `pytest` runs without warnings or deprecation notices

### Integration Readiness
- [ ] `process_hl7_message()` is importable from `app.parser.pipeline`
- [ ] `default_router` can accept real Pub/Sub publisher handlers via `register_fn()`
- [ ] Stub handlers log at INFO level — visible in Cloud Logging for deployment verification

---

## US-012 Definition of Done — Final Checklist

- [ ] `HL7Parser` class implemented using `hl7apy` with extraction for: MSH-3, MSH-7, MSH-9, MSH-10; EVN-2; PID-3, PID-5, PID-7, PID-11; PV1-2, PV1-3, PV1-7, PV1-18, PV1-19; PV2-3; DG1-3
- [ ] `ADTEvent` Pydantic model defined with all extracted fields, types, and validation
- [ ] Event type routing map `{A01: admit_handler, A02: transfer_handler, ...}` with handler registration pattern
- [ ] Mandatory segment validator: raises `HL7ValidationError` if MSH, PID, or PV1 (for A01/A02/A03) are absent
- [ ] Unknown event types log warning and raise `HL7ValidationError`; no unhandled exception propagates to MLLP layer
- [ ] Unit tests with HL7 test fixtures for all 8 event types (fixtures in `tests/fixtures/hl7/`)
- [ ] Code reviewed and approved (Backend Engineer + Security Engineer sign-off)

---

## Deliverables Summary

| File | Description |
|------|-------------|
| `hl7-listener/app/parser/__init__.py` | Package exports |
| `hl7-listener/app/parser/models.py` | `ADTEvent`, `EventType`, `HL7ValidationError`, `HL7_TRIGGER_MAP` |
| `hl7-listener/app/parser/hl7_parser.py` | `HL7Parser` — segment extraction for 15 fields across 6 segments |
| `hl7-listener/app/parser/router.py` | `ADTRouter`, `default_router` singleton, 8 stub handlers |
| `hl7-listener/app/parser/pipeline.py` | `process_hl7_message()` — end-to-end parse + route entry point |
| `hl7-listener/tests/fixtures/hl7/*.hl7` | 12 HL7 fixture files (8 event types + 4 edge cases) |
| `hl7-listener/tests/fixtures/hl7/conftest.py` | Fixture loader helper |
| `hl7-listener/tests/unit/parser/test_models.py` | ADTEvent + HL7ValidationError unit tests |
| `hl7-listener/tests/unit/parser/test_hl7_parser.py` | Parser unit tests (all 4 scenarios) |
| `hl7-listener/tests/unit/parser/test_router.py` | Router + default_router unit tests |
