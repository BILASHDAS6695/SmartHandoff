---
id: TASK-004
title: "Create HL7 Test Fixtures for All 8 ADT Event Types + Edge Cases"
user_story: US-012
epic: EP-001
sprint: 1
layer: Testing
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-012/TASK-001]
---

# TASK-004: Create HL7 Test Fixtures for All 8 ADT Event Types + Edge Cases

> **Story:** US-012 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Testing | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

The US-012 DoD specifies:

> *"Unit tests with HL7 test fixtures for all 8 event types (fixtures stored in `tests/fixtures/hl7/`)"*

Static `.hl7` fixture files serve as the single source of truth for parser tests. Using files rather than inline strings in test code:

1. Keeps test files readable and focused on assertions.
2. Mirrors real EHR messages in format (CRLF-separated segments, full segment sets).
3. Allows future replay against the MLLP server.

Each fixture file contains a single complete HL7 message with all segments relevant to that event type. PHI in fixtures uses clearly synthetic values (e.g. `Smith^John`, `MRN-XXXX`, `DOB 19800101`) — these are never persisted.

**Fixture inventory:**

| Filename | Trigger | EventType | Note |
|----------|---------|-----------|------|
| `a01_admit.hl7` | A01 | ADMIT | Full segments: MSH, EVN, PID, PV1, PV2, DG1 |
| `a02_transfer.hl7` | A02 | TRANSFER | PV1-3 has new location |
| `a03_discharge.hl7` | A03 | DISCHARGE | PV2 discharge disposition |
| `a04_register.hl7` | A04 | REGISTER | No PV1 (outpatient pre-registration) |
| `a08_update.hl7` | A08 | UPDATE | Updated PID fields |
| `a11_cancel_admit.hl7` | A11 | CANCEL_ADMIT | Cancels A01 |
| `a12_cancel_transfer.hl7` | A12 | CANCEL_TRANSFER | Cancels A02 |
| `a13_cancel_discharge.hl7` | A13 | CANCEL_DISCHARGE | Cancels A03 |
| `a01_missing_pid.hl7` | A01 | — | Missing PID → expect HL7ValidationError |
| `a99_unknown_event.hl7` | A99 | — | Unknown trigger → expect HL7ValidationError |
| `a01_multi_dg1.hl7` | A01 | ADMIT | Two DG1 segments → diagnoses list has 2 entries |
| `a01_mrn_typed.hl7` | A01 | ADMIT | PID-3 has multiple CX repetitions; MR-typed one is second |

---

## Acceptance Criteria Addressed

| US-012 AC | Requirement |
|---|---|
| **Scenario 1** | `a01_admit.hl7` used by TASK-005 to verify all required fields |
| **Scenario 2** | All 8 event-type fixtures verify correct `EventType` mapping |
| **Scenario 3** | `a99_unknown_event.hl7` triggers `HL7ValidationError` in TASK-005 |
| **Scenario 4** | `a01_missing_pid.hl7` triggers `HL7ValidationError` in TASK-005 |
| **DoD** | Fixtures stored in `tests/fixtures/hl7/` |

---

## Implementation Steps

### 1. Scaffold fixture directory

```bash
mkdir -p hl7-listener/tests/fixtures/hl7
```

### 2. Create `tests/fixtures/hl7/a01_admit.hl7`

> **Note:** HL7 segments are separated by `\r` (CR, 0x0D). Each fixture uses `\r`-terminated lines. The files below show each segment on its own line for readability — when writing the files, terminate each segment with a single `\r` character (not `\r\n`).

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG-A01-001|P|2.5
EVN|A01|20260715095500
PID|1||MRN-1001^^^CITY_HOSP^MR||Smith^John^A||19800115|M|||100 Oak Ave^^Boston^MA^02101^USA
PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||ADM|||20260715095500||||||||||||||||||||ENC-9001
PV2|||Chest pain evaluation
DG1|1||R07.9^Chest pain unspecified^ICD10
```

### 3. Create `tests/fixtures/hl7/a02_transfer.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715110000||ADT^A02|MSG-A02-001|P|2.5
EVN|A02|20260715105500
PID|1||MRN-1001^^^CITY_HOSP^MR||Smith^John^A||19800115|M|||100 Oak Ave^^Boston^MA^02101^USA
PV1|1|I|3W^3010^B|||||||12345^Jones^Sarah^Dr|||||||TRF|||20260715105500||||||||||||||||||||ENC-9001
```

### 4. Create `tests/fixtures/hl7/a03_discharge.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260716140000||ADT^A03|MSG-A03-001|P|2.5
EVN|A03|20260716135500
PID|1||MRN-1001^^^CITY_HOSP^MR||Smith^John^A||19800115|M|||100 Oak Ave^^Boston^MA^02101^USA
PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||DCH|||20260716135500||||||||||||||||||||ENC-9001
PV2|||Home with follow-up in 2 weeks
```

### 5. Create `tests/fixtures/hl7/a04_register.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715080000||ADT^A04|MSG-A04-001|P|2.5
EVN|A04|20260715075500
PID|1||MRN-2002^^^CITY_HOSP^MR||Doe^Jane^B||19920310|F|||55 Elm St^^Boston^MA^02115^USA
```

### 6. Create `tests/fixtures/hl7/a08_update.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715120000||ADT^A08|MSG-A08-001|P|2.5
EVN|A08|20260715115500
PID|1||MRN-1001^^^CITY_HOSP^MR||Smith^John^A||19800115|M|||200 Maple Ave^^Boston^MA^02101^USA
PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||ADM|||20260715095500||||||||||||||||||||ENC-9001
```

### 7. Create `tests/fixtures/hl7/a11_cancel_admit.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715101500||ADT^A11|MSG-A11-001|P|2.5
EVN|A11|20260715101000
PID|1||MRN-1001^^^CITY_HOSP^MR||Smith^John^A||19800115|M|||100 Oak Ave^^Boston^MA^02101^USA
PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||ADM|||20260715095500||||||||||||||||||||ENC-9001
```

### 8. Create `tests/fixtures/hl7/a12_cancel_transfer.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715112000||ADT^A12|MSG-A12-001|P|2.5
EVN|A12|20260715111500
PID|1||MRN-1001^^^CITY_HOSP^MR||Smith^John^A||19800115|M|||100 Oak Ave^^Boston^MA^02101^USA
PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||TRF|||20260715105500||||||||||||||||||||ENC-9001
```

### 9. Create `tests/fixtures/hl7/a13_cancel_discharge.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260716141000||ADT^A13|MSG-A13-001|P|2.5
EVN|A13|20260716140500
PID|1||MRN-1001^^^CITY_HOSP^MR||Smith^John^A||19800115|M|||100 Oak Ave^^Boston^MA^02101^USA
PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||DCH|||20260716135500||||||||||||||||||||ENC-9001
```

### 10. Create `tests/fixtures/hl7/a01_missing_pid.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG-A01-NOPID|P|2.5
EVN|A01|20260715095500
PV1|1|I|2E^2012^A|||||||12345^Jones^Sarah^Dr|||||||ADM|||20260715095500||||||||||||||||||||ENC-9001
```

### 11. Create `tests/fixtures/hl7/a99_unknown_event.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715100000||ADT^A99|MSG-A99-001|P|2.5
EVN|A99|20260715095500
PID|1||MRN-3003^^^CITY_HOSP^MR||Brown^Alice||19750505|F|||77 Pine St^^Boston^MA^02116^USA
```

### 12. Create `tests/fixtures/hl7/a01_multi_dg1.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG-A01-MULTI|P|2.5
EVN|A01|20260715095500
PID|1||MRN-4004^^^CITY_HOSP^MR||Wilson^Robert||19651220|M|||88 Cedar Ln^^Boston^MA^02118^USA
PV1|1|I|4N^4020^C|||||||67890^Patel^Anita^Dr|||||||ADM|||20260715095500||||||||||||||||||||ENC-9002
DG1|1||R07.9^Chest pain unspecified^ICD10
DG1|2||I10^Essential primary hypertension^ICD10
```

### 13. Create `tests/fixtures/hl7/a01_mrn_typed.hl7`

```
MSH|^~\&|EHR_PROD|CITY_HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG-A01-MRNTYP|P|2.5
EVN|A01|20260715095500
PID|1||ACCT-9876^^^CITY_HOSP^AN~MRN-5005^^^CITY_HOSP^MR||Garcia^Maria||19900901|F|||15 Birch Rd^^Boston^MA^02119^USA
PV1|1|I|5S^5030^D|||||||11111^Kim^David^Dr|||||||ADM|||20260715095500||||||||||||||||||||ENC-9003
```

### 14. Create `tests/fixtures/hl7/__init__.py` (empty, makes it a package for imports)

```bash
touch hl7-listener/tests/fixtures/__init__.py
touch hl7-listener/tests/fixtures/hl7/__init__.py
```

### 15. Create `tests/fixtures/hl7/conftest.py` — shared fixture loader

```python
"""Shared pytest fixtures for loading HL7 test fixture files.

Provides a ``load_hl7_fixture(filename)`` helper that reads a fixture file
from the ``tests/fixtures/hl7/`` directory and normalises line endings to CR.
"""
from __future__ import annotations

import pathlib

_FIXTURE_DIR = pathlib.Path(__file__).parent


def load_hl7_fixture(filename: str) -> str:
    """Read an HL7 fixture file and return its content with CR line endings.

    Args:
        filename: Filename relative to ``tests/fixtures/hl7/``.

    Returns:
        HL7 message string with ``\\r``-terminated segments.
    """
    path = _FIXTURE_DIR / filename
    text = path.read_text(encoding="utf-8")
    # Normalise to CR-only line endings (HL7 standard)
    return text.replace("\r\n", "\r").replace("\n", "\r")
```

---

## Validation

```bash
# Verify all 12 fixture files exist
ls -la hl7-listener/tests/fixtures/hl7/*.hl7 | wc -l
# Expected: 12

# Spot check: a01_admit.hl7 contains expected control ID
grep "MSG-A01-001" hl7-listener/tests/fixtures/hl7/a01_admit.hl7

# Verify a01_mrn_typed.hl7 has two PID-3 repetitions (~ as separator)
grep "AN~MRN-5005" hl7-listener/tests/fixtures/hl7/a01_mrn_typed.hl7
```

---

## Definition of Done Checklist

- [ ] 12 `.hl7` fixture files created in `tests/fixtures/hl7/`
- [ ] All 8 standard event type fixtures (A01–A13 subset) present
- [ ] Edge case fixtures: missing PID, unknown A99, multi-DG1, multi-repetition MRN
- [ ] `conftest.py` fixture loader normalises CR line endings
- [ ] Fixture files use synthetic (non-real) PHI values
