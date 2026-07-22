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

    def test_event_type_count_is_eight(self):
        assert len(list(EventType)) == 8


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

    def test_unknown_trigger_code_not_in_map(self):
        assert "A99" not in HL7_TRIGGER_MAP
        assert HL7_TRIGGER_MAP.get("A99") is None


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

    def test_safe_dict_none_phi_fields_remain_none(self):
        event = _make_event()
        safe = event.safe_dict()
        # None PHI fields are not redacted (they are already absent)
        assert safe["patient_last_name"] is None

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

    def test_repr_contains_event_type_and_message_id(self):
        event = _make_event()
        r = repr(event)
        assert "ADMIT" in r
        assert "MSG001" in r
        assert "ENC-9001" in r

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

    def test_diagnoses_can_be_populated(self):
        event = _make_event(diagnoses=["R07.9", "I10"])
        assert len(event.diagnoses) == 2
        assert "R07.9" in event.diagnoses


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

    def test_no_segment_or_field_allowed(self):
        exc = HL7ValidationError("Generic parse failure")
        assert exc.segment is None
        assert exc.field is None
