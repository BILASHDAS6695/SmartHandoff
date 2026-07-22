---
id: TASK-002
title: "Create `hl7-listener/app/parser/hl7_parser.py` — HL7Parser Segment Extraction (MSH, EVN, PID, PV1, PV2, DG1)"
user_story: US-012
epic: EP-001
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-012/TASK-001]
---

# TASK-002: Create `hl7-listener/app/parser/hl7_parser.py` — HL7Parser Segment Extraction (MSH, EVN, PID, PV1, PV2, DG1)

> **Story:** US-012 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

`HL7Parser` is the transformation layer that converts a raw HL7 v2.x string (already MLLP-unwrapped by TASK-001 of US-011) into a typed `ADTEvent` object. It is the most technically complex module in the US-012 scope.

Key implementation details from the US-012 Technical Notes and DoD:

| Field | Segment | hl7apy access | Note |
|-------|---------|---------------|------|
| `source_message_id` | MSH-10 | `msg.msh.msh_10.value` | Unique message control ID |
| `event_type` | MSH-9.2 | `msg.msh.msh_9.msh_9_2.value` | Trigger event code (A01–A13) |
| `sending_application` | MSH-3 | `msg.msh.msh_3.value` | Sending app name |
| `message_datetime` | MSH-7 | `msg.msh.msh_7.value` | DTM format: YYYYMMDDHHMMSS |
| `event_time` | EVN-2 | `msg.evn.evn_2.value` | DTM format |
| `patient_mrn` | PID-3 | First CX repetition where CX-5 == `"MR"` | See Technical Notes |
| `patient_last_name` | PID-5.1 | `msg.pid.pid_5.pid_5_1.value` | XPN family name |
| `patient_first_name` | PID-5.2 | `msg.pid.pid_5.pid_5_2.value` | XPN given name |
| `patient_dob` | PID-7 | `msg.pid.pid_7.value` | YYYYMMDD |
| `patient_address` | PID-11 | `msg.pid.pid_11.pid_11_1.value` | Street address |
| `patient_class` | PV1-2 | `msg.pv1.pv1_2.value` | |
| `assigned_location` | PV1-3 | `msg.pv1.pv1_3.value` | Composite location string |
| `attending_provider` | PV1-7 | `msg.pv1.pv1_7.value` | Composite XCN string |
| `patient_type` | PV1-18 | `msg.pv1.pv1_18.value` | |
| `encounter_id` | PV1-19 | `msg.pv1.pv1_19.value` | Visit number |
| `admit_reason` | PV2-3 | `msg.pv2.pv2_3.value` | Optional PV2 segment |
| `diagnoses` | DG1-3 | All DG1 repetitions → CWE-1 (code) | DG1 may repeat |

**hl7apy validation modes**:
- `VALIDATION_LEVEL.STRICT` for segment presence checking (raises `ValidationError` on missing mandatory segments)
- `VALIDATION_LEVEL.QUIET` for optional field population (returns empty string instead of raising)

**PID-3 MRN extraction** (Technical Notes):
> *"PID-3 (patient identifier list): extract first CX component with type MR for MRN"*

`hl7apy` returns PID-3 as a repeating field. Each repetition is a CX composite where `CX-5` is the identifier type code. Iterate repetitions until one with `CX-5 == "MR"` is found; fall back to the first repetition if none is typed.

**DG1 multi-segment** (Technical Notes):
> *"DG1 segment may be repeated; capture all diagnoses as a list"*

`hl7apy` exposes repeated segments via `msg.children` filtering on segment name.

Design refs: FR-002, FR-003, AIR-002, DR-022, US-012 DoD.

---

## Acceptance Criteria Addressed

| US-012 AC | Requirement |
|---|---|
| **Scenario 1** | A01 parsed → `ADTEvent` with correct `event_type`, `patient_mrn`, `encounter_id`, `event_time`, `attending_provider`, `admit_reason` |
| **Scenario 2** | All 8 event types produce correct `EventType` enum value |
| **Scenario 3** | Unknown trigger event (A99) raises `HL7ValidationError`; no `ADTEvent` created |
| **Scenario 4** | Missing PID raises `HL7ValidationError`; raw message still archived (handled in server layer) |
| **DoD** | `HL7Parser` class using `hl7apy` extracting all 15 specified fields |

---

## Implementation Steps

### 1. Create `hl7-listener/app/parser/hl7_parser.py`

```python
"""HL7 v2.x ADT message parser — extracts a typed ADTEvent from raw HL7 text.

Responsibilities:
  1. Validate mandatory segment presence (MSH, EVN, PID; PV1 for A01/A02/A03).
  2. Classify the trigger event code (MSH-9.2) via HL7_TRIGGER_MAP.
  3. Extract all required fields from MSH, EVN, PID, PV1, PV2, DG1.
  4. Return a fully validated ``ADTEvent`` Pydantic object.

Raises:
  HL7ValidationError — for missing mandatory segments, unknown event types,
                       or mandatory field extraction failures.

hl7apy usage:
  - ``VALIDATION_LEVEL.STRICT``  — segment presence (raises on missing mandatory)
  - ``VALIDATION_LEVEL.QUIET``   — optional field population (empty str on miss)

PID-3 MRN extraction (Technical Notes):
  PID-3 is a repeating CX field. Iterate repetitions; pick the first where
  CX-5 (identifier type code) == ``"MR"``. Fall back to PID-3[0] if no typed
  ``MR`` repetition exists.

DG1 multi-segment:
  hl7apy exposes repeated DG1 segments via ``msg.children``.  Filter by name
  ``"DG1"`` and extract ``DG1-3.1`` (CWE component 1 = code) from each.

Design refs:
    FR-002   — ADT event type classification (A01–A13)
    FR-003   — HL7 message validation: mandatory segments, field extraction
    AIR-002  — Mandatory: MSH, EVN, PID; PV1 for A01/A02/A03
    DR-022   — Idempotency: MSH-10 stored as source_message_id
    US-012   — DoD: HL7Parser with all 15+ field extractions
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from hl7apy.core import Message
from hl7apy.exceptions import ValidationError as Hl7apyValidationError
from hl7apy import VALIDATION_LEVEL

from app.parser.models import (
    ADTEvent,
    EventType,
    HL7ValidationError,
    HL7_TRIGGER_MAP,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event types requiring PV1 as mandatory (AIR-002)
# ---------------------------------------------------------------------------

_PV1_REQUIRED_TRIGGERS: frozenset[str] = frozenset({"A01", "A02", "A03"})

# ---------------------------------------------------------------------------
# DTM format helpers
# ---------------------------------------------------------------------------

_DTM_FORMATS = [
    "%Y%m%d%H%M%S",   # YYYYMMDDHHMMSS
    "%Y%m%d%H%M",     # YYYYMMDDHHMM
    "%Y%m%d",         # YYYYMMDD
]


def _parse_dtm(value: str, field_ref: str) -> datetime.datetime:
    """Parse an HL7 DTM string to a UTC-aware datetime.

    Tries formats from most specific to least specific.
    Raises ``HL7ValidationError`` if no format matches.
    """
    value = value.strip()
    for fmt in _DTM_FORMATS:
        try:
            dt = datetime.datetime.strptime(value[:len(fmt.replace('%Y', '0000').replace('%m', '00').replace('%d', '00').replace('%H', '00').replace('%M', '00').replace('%S', '00'))], fmt)
            return dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    raise HL7ValidationError(
        f"Cannot parse DTM value '{value}' in field {field_ref}",
        field=field_ref,
    )


def _parse_date(value: str, field_ref: str) -> Optional[datetime.date]:
    """Parse an HL7 date string (YYYYMMDD) to a date.  Returns None if blank."""
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        logger.warning("Cannot parse date '%s' in field %s — skipping", value, field_ref)
        return None


def _safe_value(component, field_ref: str) -> str:
    """Return the `.value` of an hl7apy component/field, or empty string on error."""
    try:
        val = component.value
        return val.strip() if val else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# HL7Parser
# ---------------------------------------------------------------------------

class HL7Parser:
    """Parses a raw HL7 v2.x ADT message string into a typed ``ADTEvent``.

    Usage::

        parser = HL7Parser()
        event = parser.parse(raw_hl7_string)

    The parser is stateless and thread-safe; a single instance may be reused
    across multiple ``parse()`` calls.
    """

    def parse(self, raw_hl7: str) -> ADTEvent:
        """Parse a raw HL7 string and return a validated ``ADTEvent``.

        Args:
            raw_hl7: Raw HL7 v2.x text (CR-terminated segments, no MLLP framing).

        Returns:
            A fully populated ``ADTEvent`` instance.

        Raises:
            HL7ValidationError: If mandatory segments are absent, the trigger
                event code is not in the supported set, or a mandatory field
                cannot be extracted.
        """
        # -- 1. Parse with hl7apy -----------------------------------------------
        try:
            msg = Message(raw_hl7, validation_level=VALIDATION_LEVEL.QUIET)
        except (Hl7apyValidationError, Exception) as exc:
            raise HL7ValidationError(
                f"hl7apy failed to parse message: {exc}",
                segment="MSH",
            ) from exc

        # -- 2. Validate mandatory segments ------------------------------------
        self._validate_mandatory_segments(msg, raw_hl7)

        # -- 3. Extract MSH fields ---------------------------------------------
        trigger_code = self._extract_trigger_code(msg)
        event_type = self._resolve_event_type(trigger_code)
        source_message_id = _safe_value(msg.msh.msh_10, "MSH-10")
        if not source_message_id:
            raise HL7ValidationError(
                "MSH-10 (message control ID) is empty — required for idempotency",
                segment="MSH",
                field="MSH-10",
            )
        sending_application = _safe_value(msg.msh.msh_3, "MSH-3")
        message_datetime = _parse_dtm(
            _safe_value(msg.msh.msh_7, "MSH-7"), "MSH-7"
        )

        # -- 4. Extract EVN-2 --------------------------------------------------
        event_time = _parse_dtm(_safe_value(msg.evn.evn_2, "EVN-2"), "EVN-2")

        # -- 5. Extract PID fields ---------------------------------------------
        patient_mrn = self._extract_mrn(msg)
        patient_last_name = _safe_value(
            msg.pid.pid_5.pid_5_1, "PID-5.1"
        ) or None
        patient_first_name = _safe_value(
            msg.pid.pid_5.pid_5_2, "PID-5.2"
        ) or None
        patient_dob = _parse_date(_safe_value(msg.pid.pid_7, "PID-7"), "PID-7")
        patient_address = _safe_value(msg.pid.pid_11.pid_11_1, "PID-11.1") or None

        # -- 6. Extract PV1 fields (optional for A04/A08/cancels) --------------
        encounter_id, patient_class, assigned_location, attending_provider, patient_type = (
            self._extract_pv1_fields(msg, trigger_code)
        )

        # -- 7. Extract PV2-3 (optional) ----------------------------------------
        admit_reason = self._extract_admit_reason(msg)

        # -- 8. Extract DG1 diagnoses (repeating segment) ----------------------
        diagnoses = self._extract_diagnoses(msg)

        # -- 9. Build and return ADTEvent --------------------------------------
        return ADTEvent(
            source_message_id=source_message_id,
            event_type=event_type,
            sending_application=sending_application,
            message_datetime=message_datetime,
            event_time=event_time,
            patient_mrn=patient_mrn,
            patient_last_name=patient_last_name,
            patient_first_name=patient_first_name,
            patient_dob=patient_dob,
            patient_address=patient_address,
            encounter_id=encounter_id,
            patient_class=patient_class,
            assigned_location=assigned_location,
            attending_provider=attending_provider,
            patient_type=patient_type,
            admit_reason=admit_reason,
            diagnoses=diagnoses,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_mandatory_segments(self, msg: Message, raw_hl7: str) -> None:
        """Raise HL7ValidationError if MSH, EVN, or PID are absent.

        PV1 is additionally required for trigger codes A01, A02, A03 (AIR-002).
        The trigger code is read from MSH-9.2 before PV1 is checked so that the
        error message can mention the trigger code.
        """
        segment_names = {seg.name for seg in msg.children}

        for required in ("MSH", "EVN", "PID"):
            if required not in segment_names:
                raise HL7ValidationError(
                    f"Mandatory segment '{required}' is absent from the HL7 message",
                    segment=required,
                )

        # PV1 required for admission, transfer, discharge events
        trigger_raw = ""
        try:
            trigger_raw = _safe_value(msg.msh.msh_9.msh_9_2, "MSH-9.2")
        except Exception:
            pass

        if trigger_raw in _PV1_REQUIRED_TRIGGERS and "PV1" not in segment_names:
            raise HL7ValidationError(
                f"Mandatory segment 'PV1' is absent for trigger event {trigger_raw}",
                segment="PV1",
            )

    def _extract_trigger_code(self, msg: Message) -> str:
        """Extract and normalise the MSH-9.2 trigger event code."""
        try:
            code = _safe_value(msg.msh.msh_9.msh_9_2, "MSH-9.2")
        except Exception as exc:
            raise HL7ValidationError(
                f"Cannot read MSH-9 (message type/trigger event): {exc}",
                segment="MSH",
                field="MSH-9",
            ) from exc

        if not code:
            raise HL7ValidationError(
                "MSH-9.2 (trigger event code) is empty",
                segment="MSH",
                field="MSH-9.2",
            )
        return code.upper()

    def _resolve_event_type(self, trigger_code: str) -> EventType:
        """Map a HL7 trigger code to an EventType; raise HL7ValidationError if unknown."""
        event_type = HL7_TRIGGER_MAP.get(trigger_code)
        if event_type is None:
            raise HL7ValidationError(
                f"Unknown or unsupported HL7 trigger event code: '{trigger_code}'",
                segment="MSH",
                field="MSH-9.2",
            )
        return event_type

    def _extract_mrn(self, msg: Message) -> str:
        """Extract patient MRN from PID-3 (first CX repetition with type 'MR').

        Per Technical Notes: iterate PID-3 repetitions; pick first where CX-5
        (identifier type code) == 'MR'. Fall back to first repetition if none
        is typed 'MR'.
        """
        try:
            pid3_reps = msg.pid.pid_3  # may return a single field or list
        except Exception as exc:
            raise HL7ValidationError(
                f"Cannot access PID-3 (patient identifier list): {exc}",
                segment="PID",
                field="PID-3",
            ) from exc

        # Normalise to list (hl7apy may return single or list)
        if not isinstance(pid3_reps, list):
            pid3_reps = [pid3_reps]

        mrn: Optional[str] = None
        fallback: Optional[str] = None

        for rep in pid3_reps:
            try:
                id_value = _safe_value(rep.cx_1, "PID-3.1")
                id_type = _safe_value(rep.cx_5, "PID-3.5")
            except Exception:
                id_value = _safe_value(rep, "PID-3")
                id_type = ""

            if fallback is None and id_value:
                fallback = id_value

            if id_type == "MR" and id_value:
                mrn = id_value
                break

        result = mrn or fallback
        if not result:
            raise HL7ValidationError(
                "PID-3 (patient identifier list) is empty or MRN cannot be extracted",
                segment="PID",
                field="PID-3",
            )
        return result

    def _extract_pv1_fields(
        self, msg: Message, trigger_code: str
    ) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Extract PV1 fields. Returns (encounter_id, patient_class,
        assigned_location, attending_provider, patient_type).

        PV1 is optional for A04, A08, A11, A12, A13; returns empty/None for
        those event types when the segment is absent.
        """
        try:
            pv1 = msg.pv1
        except Exception:
            if trigger_code in _PV1_REQUIRED_TRIGGERS:
                raise HL7ValidationError(
                    f"PV1 segment required for trigger {trigger_code} but not accessible",
                    segment="PV1",
                )
            return ("", None, None, None, None)

        encounter_id = _safe_value(pv1.pv1_19, "PV1-19")
        if not encounter_id and trigger_code in _PV1_REQUIRED_TRIGGERS:
            raise HL7ValidationError(
                "PV1-19 (visit number/encounter ID) is empty",
                segment="PV1",
                field="PV1-19",
            )

        patient_class = _safe_value(pv1.pv1_2, "PV1-2") or None
        assigned_location = _safe_value(pv1.pv1_3, "PV1-3") or None
        attending_provider = _safe_value(pv1.pv1_7, "PV1-7") or None
        patient_type = _safe_value(pv1.pv1_18, "PV1-18") or None

        return encounter_id, patient_class, assigned_location, attending_provider, patient_type

    def _extract_admit_reason(self, msg: Message) -> Optional[str]:
        """Extract PV2-3 (admit reason text). Returns None if PV2 absent."""
        try:
            return _safe_value(msg.pv2.pv2_3, "PV2-3") or None
        except Exception:
            return None

    def _extract_diagnoses(self, msg: Message) -> list[str]:
        """Extract all DG1-3 diagnosis codes (DG1 may repeat).

        Iterates all child segments named 'DG1' and extracts the CWE code
        component (DG1-3.1) from each.
        """
        diagnoses: list[str] = []
        try:
            dg1_segments = [seg for seg in msg.children if seg.name == "DG1"]
        except Exception:
            return diagnoses

        for dg1 in dg1_segments:
            try:
                code = _safe_value(dg1.dg1_3.dg1_3_1, "DG1-3.1")
                if code:
                    diagnoses.append(code)
            except Exception:
                logger.debug("Could not extract DG1-3 code from DG1 segment — skipping")

        return diagnoses
```

### 2. Add parser import to `hl7-listener/app/parser/__init__.py`

```python
"""HL7 parser package: domain model, parser, and event type router."""

from app.parser.models import ADTEvent, EventType, HL7ValidationError, HL7_TRIGGER_MAP
from app.parser.hl7_parser import HL7Parser

__all__ = ["ADTEvent", "EventType", "HL7ValidationError", "HL7_TRIGGER_MAP", "HL7Parser"]
```

---

## Validation

```bash
cd hl7-listener

python -c "
from app.parser.hl7_parser import HL7Parser
from app.parser.models import EventType

# Build a minimal A01 message (CR-terminated)
hl7_a01 = (
    'MSH|^~\&|EHR|HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG001|P|2.5\r'
    'EVN|A01|20260715095500\r'
    'PID|1||MRN-001^^^HOSP^MR||Smith^John||19800101|M|||123 Main St\r'
    'PV1|1|I|2E^2012^A|||||||DrJones|||||||||ADM|20260715095500|||||||||||||||||||||ENC-9001\r'
    'PV2|||Chest pain\r'
)

parser = HL7Parser()
event = parser.parse(hl7_a01)
assert event.event_type == EventType.ADMIT, f'Expected ADMIT, got {event.event_type}'
assert event.patient_mrn == 'MRN-001', f'Expected MRN-001, got {event.patient_mrn}'
assert event.encounter_id == 'ENC-9001', f'Expected ENC-9001, got {event.encounter_id}'
assert event.admit_reason == 'Chest pain', f'Expected Chest pain, got {event.admit_reason}'
print('HL7Parser A01 parse: PASSED')
print('event repr (no PHI):', repr(event))
"
```

---

## Definition of Done Checklist

- [ ] `HL7Parser.parse()` returns `ADTEvent` for all 8 supported trigger codes
- [ ] PID-3 MRN extraction iterates CX repetitions and selects type `MR`
- [ ] DG1 multi-segment extraction collects all diagnoses into a list
- [ ] `_parse_dtm()` handles YYYYMMDDHHMMSS, YYYYMMDDHHMM, YYYYMMDD formats
- [ ] `HL7ValidationError` raised (not `Exception`) for all 4 failure scenarios
- [ ] No PHI in any log statement (logger calls use `safe_dict()` or non-PHI identifiers)
- [ ] Validation script above runs without errors
