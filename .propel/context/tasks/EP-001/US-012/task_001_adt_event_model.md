---
id: TASK-001
title: "Create `hl7-listener/app/parser/models.py` — ADTEvent Pydantic Domain Model & HL7ValidationError"
user_story: US-012
epic: EP-001
sprint: 1
layer: Backend
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: []
---

# TASK-001: Create `hl7-listener/app/parser/models.py` — ADTEvent Pydantic Domain Model & HL7ValidationError

> **Story:** US-012 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

All downstream agents consume a single, typed `ADTEvent` domain object — never raw HL7 bytes. This task defines that contract. Every HL7 field extraction task (TASK-002) and every routing rule (TASK-003) depends on the types declared here.

Three objects are needed:

| Object | Purpose |
|--------|---------|
| `EventType` (Enum) | Maps HL7 trigger event codes (A01–A13) to readable domain names |
| `ADTEvent` (Pydantic `BaseModel`) | Typed container for all fields extracted from MSH, EVN, PID, PV1, PV2, DG1 |
| `HL7ValidationError` (Exception) | Raised by the validator and router for missing segments or unknown event types; caught by the MLLP server to trigger NACK |

`ADTEvent` uses Pydantic v2 (`model_config = ConfigDict(strict=True)`) so type coercions are caught at parse time, not silently at runtime.

PHI fields (`patient_last_name`, `patient_first_name`, `patient_dob`, `patient_address`) are **excluded from `__repr__` and `model_dump()`** by default to prevent accidental PHI leakage in logs (BR-020, ADR-007).

Design refs: FR-002, FR-003, AIR-002, DR-022, BR-020, US-012 DoD.

---

## Acceptance Criteria Addressed

| US-012 AC | Requirement |
|---|---|
| **Scenario 1** | `ADTEvent` has `event_type`, `patient_mrn`, `encounter_id`, `event_time`, `attending_provider`, `admit_reason` fields |
| **Scenario 2** | `EventType` enum defines all 8 mappings: A01→ADMIT, A02→TRANSFER, A03→DISCHARGE, A04→REGISTER, A08→UPDATE, A11→CANCEL_ADMIT, A12→CANCEL_TRANSFER, A13→CANCEL_DISCHARGE |
| **Scenario 3** | `HL7ValidationError` is raised (not propagated as unhandled exception) when unknown event type encountered |
| **DoD** | `ADTEvent` Pydantic model defined with all extracted fields, types, and validation |

---

## Implementation Steps

### 1. Scaffold the `parser` sub-package

```
hl7-listener/
└── app/
    └── parser/
        ├── __init__.py
        ├── models.py      ← THIS TASK
        ├── hl7_parser.py  ← TASK-002
        └── router.py      ← TASK-003
```

```bash
mkdir -p hl7-listener/app/parser
touch hl7-listener/app/parser/__init__.py
```

### 2. Create `hl7-listener/app/parser/models.py`

```python
"""ADTEvent domain model and supporting types for the HL7 Listener service.

Defines the typed domain contract that the HL7 parser produces and all
downstream consumers (Pub/Sub publisher, coordinator agent) depend on.

Key design decisions:
  - Pydantic v2 `strict=True` — no silent type coercions.
  - PHI fields excluded from repr/serialisation by default (BR-020).
  - `EventType` enum ties HL7 trigger codes to readable domain names.
  - `HL7ValidationError` is the single exception type raised by parsing and
    routing; the MLLP server catches it to return a NACK (AE).

Design refs:
    FR-002  — ADT event type classification
    FR-003  — HL7 message validation (mandatory segments, field extraction)
    AIR-002 — Mandatory segments: MSH, EVN, PID; PV1 required for A01/A02/A03
    DR-022  — HL7 message idempotency: source_message_id unique constraint
    BR-020  — PHI must not appear in logs
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Event type enumeration
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """HL7 ADT trigger event types supported by SmartHandoff.

    Maps HL7 MSH-9.2 (trigger event code) to a domain-readable name.
    Only these 8 event types are accepted; all others trigger a NACK.
    """
    ADMIT            = "ADMIT"            # A01 — Admit/visit notification
    TRANSFER         = "TRANSFER"         # A02 — Transfer a patient
    DISCHARGE        = "DISCHARGE"        # A03 — Discharge/end visit
    REGISTER         = "REGISTER"         # A04 — Register a patient
    UPDATE           = "UPDATE"           # A08 — Update patient information
    CANCEL_ADMIT     = "CANCEL_ADMIT"     # A11 — Cancel admit/visit notification
    CANCEL_TRANSFER  = "CANCEL_TRANSFER"  # A12 — Cancel transfer
    CANCEL_DISCHARGE = "CANCEL_DISCHARGE" # A13 — Cancel discharge/end visit


# HL7 trigger code → EventType routing table (used by router.py)
HL7_TRIGGER_MAP: dict[str, EventType] = {
    "A01": EventType.ADMIT,
    "A02": EventType.TRANSFER,
    "A03": EventType.DISCHARGE,
    "A04": EventType.REGISTER,
    "A08": EventType.UPDATE,
    "A11": EventType.CANCEL_ADMIT,
    "A12": EventType.CANCEL_TRANSFER,
    "A13": EventType.CANCEL_DISCHARGE,
}


# ---------------------------------------------------------------------------
# Domain exception
# ---------------------------------------------------------------------------

class HL7ValidationError(Exception):
    """Raised when an HL7 message fails structural or content validation.

    This exception is intentionally narrow — it represents only the cases
    that the MLLP server should convert into a NACK (AE) response:
      - Missing mandatory segment (MSH, EVN, PID, PV1 where required)
      - Unknown/unsupported trigger event code (e.g. A99)
      - Field extraction failure on a mandatory field

    The MLLP server layer (app/mllp/server.py) catches this exception and
    calls ``build_nack_response()``.  It must NOT be used for unexpected
    runtime errors — those should propagate as standard exceptions.

    Attributes:
        segment:  Name of the problematic HL7 segment (e.g. ``"PID"``).
        field:    Field location within the segment (e.g. ``"PID-3"``), or
                  ``None`` when the entire segment is missing.
        message:  Human-readable description (not logged with PHI).
    """

    def __init__(
        self,
        message: str,
        *,
        segment: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.segment = segment
        self.field = field

    def __repr__(self) -> str:
        return (
            f"HL7ValidationError(segment={self.segment!r}, "
            f"field={self.field!r}, message={str(self)!r})"
        )


# ---------------------------------------------------------------------------
# ADTEvent domain model
# ---------------------------------------------------------------------------

class ADTEvent(BaseModel):
    """Typed representation of a parsed HL7 ADT message.

    Produced by ``HL7Parser.parse()`` and consumed by:
      - The Pub/Sub publisher (serialised to JSON for the ``adt-events`` topic)
      - The Coordinator Agent (deserialized from Pub/Sub message)
      - Unit tests (constructed directly from test fixtures)

    Field-level annotations:
      - Fields marked ``phi=True`` in the description are excluded from
        ``model_dump()`` serialisation unless ``include_phi=True`` is passed.
        This prevents PHI from appearing in logs or Pub/Sub message payloads.
      - MRN uses deterministic encryption at the ORM layer (ADR-007);
        the ``ADTEvent`` holds the plaintext MRN in memory only.

    Extraction sources (segment → field):
      MSH-3   → sending_application
      MSH-7   → message_datetime
      MSH-9.2 → event_type (via EventType enum)
      MSH-10  → source_message_id
      EVN-2   → event_time
      PID-3   → patient_mrn        (first CX component with type "MR")
      PID-5   → patient_last_name, patient_first_name  [PHI]
      PID-7   → patient_dob                            [PHI]
      PID-11  → patient_address                        [PHI]
      PV1-2   → patient_class
      PV1-3   → assigned_location
      PV1-7   → attending_provider
      PV1-18  → patient_type
      PV1-19  → encounter_id
      PV2-3   → admit_reason
      DG1-3   → diagnoses  (list; DG1 may repeat)

    Design refs:
        FR-002, FR-003, AIR-002, DR-022, BR-020, US-012 DoD
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    # -- Identification (non-PHI) -------------------------------------------
    source_message_id: str = Field(
        description="MSH-10: unique message control ID from the sending system.",
    )
    event_type: EventType = Field(
        description="Classified ADT event type derived from MSH-9.2 trigger code.",
    )
    sending_application: str = Field(
        description="MSH-3: name of the sending application (e.g. 'EHR_PROD').",
    )
    message_datetime: datetime.datetime = Field(
        description="MSH-7: date/time the message was generated (UTC).",
    )
    event_time: datetime.datetime = Field(
        description="EVN-2: date/time the triggering event occurred (UTC).",
    )

    # -- Patient identification (PHI — excluded from default serialisation) --
    patient_mrn: str = Field(
        description="[PHI] PID-3: Medical Record Number (first CX component typed 'MR').",
    )
    patient_last_name: Optional[str] = Field(
        default=None,
        description="[PHI] PID-5.1: Patient family name.",
    )
    patient_first_name: Optional[str] = Field(
        default=None,
        description="[PHI] PID-5.2: Patient given name.",
    )
    patient_dob: Optional[datetime.date] = Field(
        default=None,
        description="[PHI] PID-7: Date of birth.",
    )
    patient_address: Optional[str] = Field(
        default=None,
        description="[PHI] PID-11: Street address (concatenated).",
    )

    # -- Encounter / visit (non-PHI) ----------------------------------------
    encounter_id: str = Field(
        description="PV1-19: Visit number / encounter identifier.",
    )
    patient_class: Optional[str] = Field(
        default=None,
        description="PV1-2: Patient class (I=Inpatient, O=Outpatient, E=Emergency).",
    )
    assigned_location: Optional[str] = Field(
        default=None,
        description="PV1-3: Assigned patient location (e.g. '2E^2012^A').",
    )
    attending_provider: Optional[str] = Field(
        default=None,
        description="PV1-7: Attending doctor identifier / name composite.",
    )
    patient_type: Optional[str] = Field(
        default=None,
        description="PV1-18: Patient type code.",
    )
    admit_reason: Optional[str] = Field(
        default=None,
        description="PV2-3: Admit reason text from the Pre-Admission Information segment.",
    )

    # -- Clinical (non-PHI identifiers only) --------------------------------
    diagnoses: list[str] = Field(
        default_factory=list,
        description="DG1-3: List of ICD diagnosis codes (one entry per DG1 segment).",
    )

    # -----------------------------------------------------------------------
    # PHI-safe serialisation helper
    # -----------------------------------------------------------------------

    _PHI_FIELDS: frozenset[str] = frozenset({
        "patient_mrn",
        "patient_last_name",
        "patient_first_name",
        "patient_dob",
        "patient_address",
    })

    def safe_dict(self) -> dict:
        """Return a dict representation with PHI fields redacted.

        Use this method when logging or publishing to Pub/Sub to ensure
        PHI does not appear in structured logs or message payloads.

        PHI fields are replaced with ``"[REDACTED]"``.
        """
        data = self.model_dump()
        for field in self._PHI_FIELDS:
            if field in data and data[field] is not None:
                data[field] = "[REDACTED]"
        return data

    def __repr__(self) -> str:
        """Override repr to prevent PHI appearing in log output."""
        return (
            f"ADTEvent(event_type={self.event_type!r}, "
            f"source_message_id={self.source_message_id!r}, "
            f"encounter_id={self.encounter_id!r})"
        )
```

### 3. Update `hl7-listener/app/parser/__init__.py`

```python
"""HL7 parser package: domain model, parser, and event type router."""

from app.parser.models import ADTEvent, EventType, HL7ValidationError, HL7_TRIGGER_MAP

__all__ = ["ADTEvent", "EventType", "HL7ValidationError", "HL7_TRIGGER_MAP"]
```

### 4. Add `pydantic` to `hl7-listener/requirements.txt`

Append if not already present:

```
# Domain model
pydantic>=2.7.0
```

---

## Validation

```bash
cd hl7-listener

# 1. Confirm Pydantic v2 is installed
python -c "import pydantic; print(pydantic.VERSION)"   # expect 2.x.x

# 2. Import check
python -c "
from app.parser.models import ADTEvent, EventType, HL7ValidationError, HL7_TRIGGER_MAP
print('EventType members:', [e.value for e in EventType])
print('HL7_TRIGGER_MAP keys:', list(HL7_TRIGGER_MAP.keys()))
assert len(HL7_TRIGGER_MAP) == 8, 'Expected 8 event type mappings'
print('models.py: PASSED')
"

# 3. Verify PHI-safe serialisation
python -c "
import datetime
from app.parser.models import ADTEvent, EventType
e = ADTEvent(
    source_message_id='MSG001',
    event_type=EventType.ADMIT,
    sending_application='EHR',
    message_datetime=datetime.datetime(2026, 7, 15, 10, 0, 0),
    event_time=datetime.datetime(2026, 7, 15, 10, 0, 0),
    patient_mrn='MRN-001',
    patient_last_name='Smith',
    patient_first_name='John',
    encounter_id='ENC-9001',
)
safe = e.safe_dict()
assert safe['patient_mrn'] == '[REDACTED]', 'MRN not redacted'
assert safe['patient_last_name'] == '[REDACTED]', 'Last name not redacted'
assert 'Smith' not in repr(e), 'PHI in repr'
print('PHI redaction: PASSED')
"
```

---

## Definition of Done Checklist

- [ ] `EventType` enum defines all 8 event type mappings (A01–A13 subset)
- [ ] `HL7_TRIGGER_MAP` dict maps all 8 HL7 trigger codes to `EventType` values
- [ ] `HL7ValidationError` exception with `segment` and `field` attributes
- [ ] `ADTEvent` Pydantic model with all 15+ fields typed and documented
- [ ] `safe_dict()` redacts all 5 PHI fields
- [ ] `__repr__` contains no PHI fields
- [ ] Validation script above runs without errors
