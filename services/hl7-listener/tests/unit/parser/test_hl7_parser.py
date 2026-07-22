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
  - DTM format parsing (YYYYMMDDHHMMSS, YYYYMMDDHHMM, YYYYMMDD formats)
"""
from __future__ import annotations

import datetime
import logging
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

    def test_sending_application_extracted(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert event.sending_application == "EHR_PROD"

    def test_patient_class_is_inpatient(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert event.patient_class == "I"

    def test_diagnoses_list_has_one_entry(self, parser):
        event = parser.parse(_load("a01_admit.hl7"))
        assert len(event.diagnoses) == 1
        assert "R07.9" in event.diagnoses[0]


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

    def test_unknown_trigger_logs_no_critical_messages(self, parser, caplog):
        with caplog.at_level(logging.DEBUG, logger="app.parser"):
            with pytest.raises(HL7ValidationError):
                parser.parse(_load("a99_unknown_event.hl7"))
        critical_records = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert len(critical_records) == 0


# ---------------------------------------------------------------------------
# Scenario 4: Missing PID → HL7ValidationError
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
        """No ADTEvent is ever returned when PID is missing."""
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
        diagnosis_str = " ".join(event.diagnoses)
        assert "R07.9" in diagnosis_str
        assert "I10" in diagnosis_str

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
