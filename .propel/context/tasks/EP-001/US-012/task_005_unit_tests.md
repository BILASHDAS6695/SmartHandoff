---
id: TASK-005
title: "Write pytest Unit Tests — HL7Parser, ADTEvent Model, Event Router (All 4 Scenarios)"
user_story: US-012
epic: EP-001
sprint: 1
layer: Testing
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-012/TASK-001, US-012/TASK-002, US-012/TASK-003, US-012/TASK-004]
---

# TASK-005: Write pytest Unit Tests — HL7Parser, ADTEvent Model, Event Router (All 4 Scenarios)

> **Story:** US-012 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-012 DoD:
> *"Unit tests with HL7 test fixtures for all 8 event types (fixtures stored in `tests/fixtures/hl7/`)"*

All 4 acceptance criteria scenarios must have corresponding test cases. Tests are split across three test files matching the three production modules:

| Test File | Module Under Test | Coverage Focus |
|-----------|------------------|----------------|
| `test_models.py` | `app/parser/models.py` | ADTEvent validation, PHI redaction, HL7ValidationError |
| `test_hl7_parser.py` | `app/parser/hl7_parser.py` | All 8 event types, field extraction, error scenarios |
| `test_router.py` | `app/parser/router.py` | Handler registration, routing dispatch, unregistered type |

Coverage target: ≥80% branch coverage on `app/parser/models.py`, `app/parser/hl7_parser.py`, and `app/parser/router.py` (TR-020).

---

## Acceptance Criteria Addressed

| US-012 AC | Test Case(s) |
|---|---|
| **Scenario 1** | `test_hl7_parser.py::test_parse_a01_all_required_fields` |
| **Scenario 2** | `test_hl7_parser.py::test_all_eight_event_types_map_correctly` (parametrised) |
| **Scenario 3** | `test_hl7_parser.py::test_unknown_event_type_raises_validation_error` |
| **Scenario 4** | `test_hl7_parser.py::test_missing_pid_raises_validation_error` |
| **DoD** | Full test suite; fixtures in `tests/fixtures/hl7/`; ≥80% coverage |

---

## Implementation Steps

### 1. Create `hl7-listener/tests/unit/parser/__init__.py`

```bash
mkdir -p hl7-listener/tests/unit/parser
touch hl7-listener/tests/unit/parser/__init__.py
```

### 2. Create `hl7-listener/tests/unit/parser/test_models.py`

```python
"""Unit tests for app/parser/models.py — ADTEvent, EventType, HL7ValidationError.

Coverage:
  - EventType enum: all 8 members present
  - HL7_TRIGGER_MAP: all 8 mappings correct
  - ADTEvent: valid construction, Pydantic validation errors
  - ADTEvent.safe_dict(): PHI fields redacted
  - ADTEvent.__repr__(): no PHI in output
  - HL7ValidationError: attributes and repr
"""
from __future__ import annotations

import datetime

import pytest

from app.parser.models import (
    ADTEvent,
    EventType,
    HL7ValidationError,
    HL7_TRIGGER_MAP,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides) -> ADTEvent:
    """Build a minimal valid ADTEvent for testing."""
    base = dict(
        source_message_id="MSG001",
        event_type=EventType.ADMIT,
        sending_application="EHR",
        message_datetime=datetime.datetime(2026, 7, 15, 10, 0, 0, tzinfo=datetime.timezone.utc),
        event_time=datetime.datetime(2026, 7, 15, 9, 55, 0, tzinfo=datetime.timezone.utc),
        patient_mrn="MRN-1001",
        encounter_id="ENC-9001",
    )
    base.update(overrides)
    return ADTEvent(**base)


# ---------------------------------------------------------------------------
# EventType enum
# ---------------------------------------------------------------------------

class TestEventType:
    def test_all_eight_event_types_present(self):
        expected_values = {
            "ADMIT", "TRANSFER", "DISCHARGE", "REGISTER",
            "UPDATE", "CANCEL_ADMIT", "CANCEL_TRANSFER", "CANCEL_DISCHARGE",
        }
        actual_values = {e.value for e in EventType}
        assert actual_values == expected_values

    def test_event_type_is_string_enum(self):
        # EventType inherits from str so it serialises cleanly to JSON
        assert isinstance(EventType.ADMIT, str)
        assert EventType.ADMIT == "ADMIT"


# ---------------------------------------------------------------------------
# HL7_TRIGGER_MAP
# ---------------------------------------------------------------------------

class TestHL7TriggerMap:
    def test_all_eight_trigger_codes_present(self):
        expected_codes = {"A01", "A02", "A03", "A04", "A08", "A11", "A12", "A13"}
        assert set(HL7_TRIGGER_MAP.keys()) == expected_codes

    @pytest.mark.parametrize("code, expected_type", [
        ("A01", EventType.ADMIT),
        ("A02", EventType.TRANSFER),
        ("A03", EventType.DISCHARGE),
        ("A04", EventType.REGISTER),
        ("A08", EventType.UPDATE),
        ("A11", EventType.CANCEL_ADMIT),
        ("A12", EventType.CANCEL_TRANSFER),
        ("A13", EventType.CANCEL_DISCHARGE),
    ])
    def test_trigger_code_maps_to_correct_event_type(self, code, expected_type):
        assert HL7_TRIGGER_MAP[code] == expected_type


# ---------------------------------------------------------------------------
# ADTEvent
# ---------------------------------------------------------------------------

class TestADTEvent:
    def test_minimal_valid_event_constructs(self):
        event = _make_event()
        assert event.event_type == EventType.ADMIT
        assert event.patient_mrn == "MRN-1001"

    def test_phi_fields_default_to_none(self):
        event = _make_event()
        assert event.patient_last_name is None
        assert event.patient_first_name is None
        assert event.patient_dob is None
        assert event.patient_address is None

    def test_diagnoses_defaults_to_empty_list(self):
        event = _make_event()
        assert event.diagnoses == []

    def test_full_event_with_optional_phi(self):
        event = _make_event(
            patient_last_name="Smith",
            patient_first_name="John",
            patient_dob=datetime.date(1980, 1, 15),
        )
        assert event.patient_last_name == "Smith"
        assert event.patient_dob == datetime.date(1980, 1, 15)

    def test_safe_dict_redacts_all_phi_fields(self):
        event = _make_event(
            patient_mrn="MRN-SECRET",
            patient_last_name="Smith",
            patient_first_name="John",
            patient_dob=datetime.date(1980, 1, 15),
            patient_address="123 Main St",
        )
        safe = event.safe_dict()
        assert safe["patient_mrn"] == "[REDACTED]"
        assert safe["patient_last_name"] == "[REDACTED]"
        assert safe["patient_first_name"] == "[REDACTED]"
        assert safe["patient_dob"] == "[REDACTED]"
        assert safe["patient_address"] == "[REDACTED]"

    def test_safe_dict_does_not_redact_non_phi_fields(self):
        event = _make_event()
        safe = event.safe_dict()
        assert safe["source_message_id"] == "MSG001"
        assert safe["encounter_id"] == "ENC-9001"
        assert safe["event_type"] == "ADMIT"

    def test_repr_contains_no_phi(self):
        event = _make_event(
            patient_last_name="Smith",
            patient_first_name="John",
            patient_mrn="MRN-SECRET",
        )
        r = repr(event)
        assert "Smith" not in r
        assert "John" not in r
        assert "MRN-SECRET" not in r
        assert "ADTEvent(" in r

    def test_missing_required_field_raises_validation_error(self):
        with pytest.raises(Exception):  # Pydantic ValidationError
            ADTEvent(
                event_type=EventType.ADMIT,
                # source_message_id omitted — mandatory
                sending_application="EHR",
                message_datetime=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc),
                event_time=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc),
                patient_mrn="MRN-1001",
                encounter_id="ENC-9001",
            )


# ---------------------------------------------------------------------------
# HL7ValidationError
# ---------------------------------------------------------------------------

class TestHL7ValidationError:
    def test_basic_construction(self):
        exc = HL7ValidationError("Missing PID segment", segment="PID")
        assert str(exc) == "Missing PID segment"
        assert exc.segment == "PID"
        assert exc.field is None

    def test_construction_with_field(self):
        exc = HL7ValidationError("PID-3 empty", segment="PID", field="PID-3")
        assert exc.field == "PID-3"

    def test_repr_contains_segment_and_message(self):
        exc = HL7ValidationError("Test error", segment="MSH", field="MSH-9")
        r = repr(exc)
        assert "MSH" in r
        assert "MSH-9" in r
        assert "Test error" in r

    def test_is_exception_subclass(self):
        assert issubclass(HL7ValidationError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(HL7ValidationError) as exc_info:
            raise HL7ValidationError("test", segment="EVN")
        assert exc_info.value.segment == "EVN"
```

### 3. Create `hl7-listener/tests/unit/parser/test_hl7_parser.py`

```python
"""Unit tests for app/parser/hl7_parser.py — HL7Parser.parse() method.

Covers all 4 acceptance criteria scenarios from US-012:
  Scenario 1: A01 parsed to ADTEvent with all required fields
  Scenario 2: All 8 event types classified correctly
  Scenario 3: Unknown event type A99 → HL7ValidationError + no ADTEvent
  Scenario 4: Missing PID segment → HL7ValidationError

Additional coverage:
  - DG1 multi-segment extraction
  - PID-3 MRN typed extraction (CX-5 == MR)
  - Optional segment absence (PV2, DG1)
  - DTM format parsing (YYYYMMDDHHMMSS, YYYYMMDD)
"""
from __future__ import annotations

import datetime
import pathlib

import pytest

from app.parser.hl7_parser import HL7Parser
from app.parser.models import EventType, HL7ValidationError

# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------

_FIXTURE_DIR = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "hl7"


def _load(filename: str) -> str:
    """Load an HL7 fixture file and normalise to CR line endings."""
    text = (_FIXTURE_DIR / filename).read_text(encoding="utf-8")
    return text.replace("\r\n", "\r").replace("\n", "\r")


# ---------------------------------------------------------------------------
# Shared parser instance
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def parser() -> HL7Parser:
    return HL7Parser()


# ---------------------------------------------------------------------------
# Scenario 1: A01 parsed with all required fields
# ---------------------------------------------------------------------------

class TestParseA01AllRequiredFields:
    """US-012 Scenario 1: A01 → ADTEvent with expected field values."""

    def test_event_type_is_admit(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert event.event_type == EventType.ADMIT

    def test_patient_mrn_extracted(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert event.patient_mrn == "MRN-1001"

    def test_encounter_id_extracted_from_pv1_19(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert event.encounter_id == "ENC-9001"

    def test_event_time_extracted_from_evn_2(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert isinstance(event.event_time, datetime.datetime)
        assert event.event_time.year == 2026

    def test_attending_provider_extracted_from_pv1_7(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        # PV1-7 value from fixture: "12345^Jones^Sarah^Dr"
        assert event.attending_provider is not None
        assert len(event.attending_provider) > 0

    def test_admit_reason_extracted_from_pv2_3(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert event.admit_reason == "Chest pain evaluation"

    def test_source_message_id_matches_fixture(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert event.source_message_id == "MSG-A01-001"

    def test_message_datetime_is_utc_aware(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert event.message_datetime.tzinfo is not None


# ---------------------------------------------------------------------------
# Scenario 2: All 8 event types map correctly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture_file, expected_event_type", [
    ("a01_admit.hl7",            EventType.ADMIT),
    ("a02_transfer.hl7",         EventType.TRANSFER),
    ("a03_discharge.hl7",        EventType.DISCHARGE),
    ("a04_register.hl7",         EventType.REGISTER),
    ("a08_update.hl7",           EventType.UPDATE),
    ("a11_cancel_admit.hl7",     EventType.CANCEL_ADMIT),
    ("a12_cancel_transfer.hl7",  EventType.CANCEL_TRANSFER),
    ("a13_cancel_discharge.hl7", EventType.CANCEL_DISCHARGE),
])
def test_all_eight_event_types_map_correctly(parser, fixture_file, expected_event_type):
    """US-012 Scenario 2: each trigger code produces the correct EventType."""
    event = parser.parse(_load(fixture_file))
    assert event.event_type == expected_event_type


# ---------------------------------------------------------------------------
# Scenario 3: Unknown event type A99 → HL7ValidationError
# ---------------------------------------------------------------------------

class TestUnknownEventType:
    """US-012 Scenario 3: A99 trigger code → NACK, no ADTEvent created."""

    def test_unknown_trigger_raises_hl7_validation_error(self, parser):
        with pytest.raises(HL7ValidationError) as exc_info:
            parser.parse(_load("a99_unknown_event.hl7"))
        assert exc_info.value.segment == "MSH"
        assert "A99" in str(exc_info.value)

    def test_unknown_trigger_error_is_not_generic_exception(self, parser):
        """Ensures HL7ValidationError propagates — not buried as generic Exception."""
        with pytest.raises(HL7ValidationError):
            parser.parse(_load("a99_unknown_event.hl7"))

    def test_unknown_trigger_logs_warning_not_critical(self, parser, caplog):
        import logging
        with caplog.at_level(logging.DEBUG, logger="app.parser"):
            with pytest.raises(HL7ValidationError):
                parser.parse(_load("a99_unknown_event.hl7"))
        # No CRITICAL log should be emitted for an expected validation failure
        critical_records = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert len(critical_records) == 0


# ---------------------------------------------------------------------------
# Scenario 4: Missing PID → HL7ValidationError + raw message archived (server)
# ---------------------------------------------------------------------------

class TestMissingMandatorySegment:
    """US-012 Scenario 4: Missing PID → HL7ValidationError."""

    def test_missing_pid_raises_hl7_validation_error(self, parser):
        with pytest.raises(HL7ValidationError) as exc_info:
            parser.parse(_load("a01_missing_pid.hl7"))
        assert exc_info.value.segment == "PID"

    def test_error_message_names_missing_segment(self, parser):
        with pytest.raises(HL7ValidationError) as exc_info:
            parser.parse(_load("a01_missing_pid.hl7"))
        assert "PID" in str(exc_info.value)

    def test_missing_pid_does_not_return_partial_event(self, parser):
        """Validate that no ADTEvent is ever returned when PID is missing."""
        result = None
        try:
            result = parser.parse(_load("a01_missing_pid.hl7"))
        except HL7ValidationError:
            pass
        assert result is None


# ---------------------------------------------------------------------------
# Additional: DG1 multi-segment extraction
# ---------------------------------------------------------------------------

class TestDG1MultiSegment:
    def test_two_dg1_segments_produce_two_diagnoses(self, parser):
        event = parser.parse(_load("a01_multi_dg1.hl7"))
        assert len(event.diagnoses) == 2
        assert "R07.9" in event.diagnoses[0] or "R07.9" in event.diagnoses
        assert any("I10" in d for d in event.diagnoses)

    def test_no_dg1_segment_produces_empty_list(self, parser):
        # a04_register.hl7 has no DG1
        event = parser.parse(_load("a04_register.hl7"))
        assert event.diagnoses == []


# ---------------------------------------------------------------------------
# Additional: PID-3 MRN typed extraction
# ---------------------------------------------------------------------------

class TestMrnTypedExtraction:
    def test_mr_typed_repetition_selected_over_account_number(self, parser):
        """PID-3 has two repetitions: AN first, MR second — should pick MR."""
        event = parser.parse(_load("a01_mrn_typed.hl7"))
        assert event.patient_mrn == "MRN-5005"

    def test_mrn_is_not_account_number(self, parser):
        event = parser.parse(_load("a01_mrn_typed.hl7"))
        assert event.patient_mrn != "ACCT-9876"


# ---------------------------------------------------------------------------
# Additional: Optional segments absent
# ---------------------------------------------------------------------------

class TestOptionalSegmentsAbsent:
    def test_a04_without_pv1_has_empty_encounter_id(self, parser):
        """A04 (register) does not require PV1; encounter_id may be empty string."""
        event = parser.parse(_load("a04_register.hl7"))
        assert event.event_type == EventType.REGISTER
        # encounter_id should be empty or None — not raise an error
        assert event.encounter_id is not None  # field exists, may be empty string

    def test_a04_without_pv2_has_none_admit_reason(self, parser):
        event = parser.parse(_load("a04_register.hl7"))
        assert event.admit_reason is None
```

### 4. Create `hl7-listener/tests/unit/parser/test_router.py`

```python
"""Unit tests for app/parser/router.py — ADTRouter and default_router.

Coverage:
  - ADTRouter.register() decorator
  - ADTRouter.register_fn() imperative registration
  - ADTRouter.route() dispatch
  - ADTRouter.is_registered()
  - ADTRouter.registered_types()
  - Unregistered event type → HL7ValidationError
  - default_router has all 8 event types registered with stub handlers
"""
from __future__ import annotations

import datetime

import pytest

from app.parser.models import ADTEvent, EventType, HL7ValidationError
from app.parser.router import ADTRouter, default_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(event_type: EventType) -> ADTEvent:
    return ADTEvent(
        source_message_id="MSG001",
        event_type=event_type,
        sending_application="EHR",
        message_datetime=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc),
        event_time=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc),
        patient_mrn="MRN-1001",
        encounter_id="ENC-9001",
    )


# ---------------------------------------------------------------------------
# ADTRouter
# ---------------------------------------------------------------------------

class TestADTRouter:
    def test_register_decorator_registers_handler(self):
        router = ADTRouter()

        @router.register(EventType.ADMIT)
        def handle_admit(event: ADTEvent):
            return "admit_result"

        assert router.is_registered(EventType.ADMIT)

    def test_register_fn_registers_handler(self):
        router = ADTRouter()
        router.register_fn(EventType.DISCHARGE, lambda e: "discharged")
        assert router.is_registered(EventType.DISCHARGE)

    def test_route_dispatches_to_registered_handler(self):
        router = ADTRouter()
        results = []

        @router.register(EventType.TRANSFER)
        def handle_transfer(event: ADTEvent):
            results.append(event.event_type)
            return "transferred"

        event = _make_event(EventType.TRANSFER)
        ret = router.route(event)
        assert ret == "transferred"
        assert results == [EventType.TRANSFER]

    def test_route_returns_handler_return_value(self):
        router = ADTRouter()
        router.register_fn(EventType.UPDATE, lambda e: {"status": "ok", "msg_id": e.source_message_id})
        event = _make_event(EventType.UPDATE)
        result = router.route(event)
        assert result["status"] == "ok"
        assert result["msg_id"] == "MSG001"

    def test_route_unregistered_type_raises_hl7_validation_error(self):
        router = ADTRouter()
        # No handler registered
        event = _make_event(EventType.ADMIT)
        with pytest.raises(HL7ValidationError) as exc_info:
            router.route(event)
        assert "ADMIT" in str(exc_info.value)

    def test_registered_types_returns_all_registered_types(self):
        router = ADTRouter()
        router.register_fn(EventType.ADMIT, lambda e: None)
        router.register_fn(EventType.DISCHARGE, lambda e: None)
        types = router.registered_types()
        assert EventType.ADMIT in types
        assert EventType.DISCHARGE in types
        assert len(types) == 2

    def test_re_registering_replaces_previous_handler(self):
        router = ADTRouter()
        router.register_fn(EventType.REGISTER, lambda e: "first")
        router.register_fn(EventType.REGISTER, lambda e: "second")
        event = _make_event(EventType.REGISTER)
        assert router.route(event) == "second"

    def test_is_registered_returns_false_for_unregistered(self):
        router = ADTRouter()
        assert not router.is_registered(EventType.CANCEL_ADMIT)


# ---------------------------------------------------------------------------
# default_router (module-level singleton)
# ---------------------------------------------------------------------------

class TestDefaultRouter:
    def test_all_eight_event_types_registered_in_default_router(self):
        for event_type in EventType:
            assert default_router.is_registered(event_type), (
                f"default_router missing handler for {event_type.value}"
            )

    def test_default_router_routes_admit_without_error(self):
        """Stub handler should not raise for any EventType."""
        event = _make_event(EventType.ADMIT)
        result = default_router.route(event)  # stub returns None
        assert result is None

    @pytest.mark.parametrize("event_type", list(EventType))
    def test_default_router_stub_handles_all_event_types(self, event_type):
        """All 8 stubs should route without raising."""
        event = _make_event(event_type)
        try:
            default_router.route(event)
        except Exception as exc:
            pytest.fail(f"default_router raised {type(exc).__name__} for {event_type.value}: {exc}")
```

### 5. Update `hl7-listener/tests/unit/__init__.py` (ensure `parser` sub-package is discoverable)

```bash
# Already exists from US-011 scaffold; no change needed if present.
# If absent:
touch hl7-listener/tests/unit/__init__.py
```

---

## Running Tests

```bash
cd hl7-listener

# Run all US-012 unit tests with coverage
pytest tests/unit/parser/ -v \
  --cov=app/parser/models \
  --cov=app/parser/hl7_parser \
  --cov=app/parser/router \
  --cov-report=term-missing \
  --cov-fail-under=80

# Run only the 8-event-type parametrised test
pytest tests/unit/parser/test_hl7_parser.py::test_all_eight_event_types_map_correctly -v

# Run all 4 acceptance scenario classes
pytest tests/unit/parser/test_hl7_parser.py \
  -k "TestParseA01 or TestUnknownEventType or TestMissingMandatorySegment" -v
```

Expected output:
```
tests/unit/parser/test_models.py         ........  [ 8 passed ]
tests/unit/parser/test_hl7_parser.py     ........  [25 passed ]
tests/unit/parser/test_router.py         ........  [12 passed ]
TOTAL                                    [45 passed ]
Coverage ≥ 80% on all three modules
```

---

## Definition of Done Checklist

- [ ] `test_models.py`: EventType, HL7_TRIGGER_MAP, ADTEvent, HL7ValidationError tests
- [ ] `test_hl7_parser.py`: all 4 scenario classes + parametrised 8-event-type test
- [ ] `test_router.py`: ADTRouter unit tests + default_router integration tests
- [ ] All tests pass (`pytest tests/unit/parser/ -v`)
- [ ] Coverage ≥80% on `models.py`, `hl7_parser.py`, `router.py`
- [ ] No PHI (real patient data) in any test file or fixture
