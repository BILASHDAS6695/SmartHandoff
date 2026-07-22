"""Unit tests for app/mllp/ack_builder.py — ACK (AA) and NACK (AE) message construction.

Test coverage:
  - build_ack_response: MLLP framing, MSA|AA with echoed message control ID,
    MSH-9 includes trigger event
  - build_nack_response: MLLP framing, MSA|AE, ERR segment with code 207,
    fallback when raw_hl7=None
  - _extract_msh_fields: missing MSH, insufficient fields

Coverage target: ≥80% branch coverage on app/mllp/ack_builder.py (TR-020).
"""
from __future__ import annotations

import pytest

from app.mllp.ack_builder import (
    _extract_msh_fields,
    build_ack_response,
    build_nack_response,
)
from app.mllp.framing import MLLP_END, MLLP_START

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_ADT_A01 = (
    "MSH|^~\\&|EHR|HOSP|SmartHandoff|HOSP|20260715120000||ADT^A01|MSG001|P|2.5\r"
    "EVN|A01|20260715120000\r"
    "PID|1||MRN001^^^HOSP^MR||Doe^John||19800101|M\r"
)

VALID_ADT_A02 = (
    "MSH|^~\\&|EHR|HOSP|SmartHandoff|HOSP|20260715121500||ADT^A02|MSG002|P|2.5\r"
    "EVN|A02|20260715121500\r"
    "PID|1||MRN001^^^HOSP^MR\r"
)


# ---------------------------------------------------------------------------
# build_ack_response
# ---------------------------------------------------------------------------

class TestBuildAckResponse:
    def test_output_is_mllp_framed(self) -> None:
        result = build_ack_response(VALID_ADT_A01)
        assert result[0:1] == MLLP_START, "ACK must start with VT (0x0B)"
        assert result[-2:] == MLLP_END, "ACK must end with FS+CR (0x1C 0x0D)"

    def test_msa_aa_present(self) -> None:
        result = build_ack_response(VALID_ADT_A01)
        assert b"MSA|AA|" in result, "ACK must contain MSA segment with AA code"

    def test_msa_echoes_original_message_control_id(self) -> None:
        """MSA-2 must echo the original MSH-10 value (MSG001)."""
        result = build_ack_response(VALID_ADT_A01)
        assert b"MSA|AA|MSG001" in result, "MSA-2 must echo original MSH-10 control ID"

    def test_msh9_contains_ack_and_trigger(self) -> None:
        """ACK MSH-9 should be ACK^A01 (mirrors inbound trigger event)."""
        result = build_ack_response(VALID_ADT_A01)
        assert b"ACK^A01" in result, "MSH-9 in ACK must be ACK^{trigger}"

    def test_different_message_control_ids_are_echoed(self) -> None:
        """Each ACK echoes the correct control ID from its source message."""
        ack1 = build_ack_response(VALID_ADT_A01)
        ack2 = build_ack_response(VALID_ADT_A02)
        assert b"MSG001" in ack1
        assert b"MSG002" in ack2

    def test_raises_on_missing_msh(self) -> None:
        with pytest.raises(ValueError, match="No MSH segment"):
            build_ack_response("EVN|A01|20260715\r")

    def test_returns_bytes(self) -> None:
        result = build_ack_response(VALID_ADT_A01)
        assert isinstance(result, bytes)

    def test_msh3_sending_app_is_smarthandoff(self) -> None:
        """ACK MSH-3 must be SmartHandoff (listener identity)."""
        result = build_ack_response(VALID_ADT_A01)
        assert b"SmartHandoff" in result


# ---------------------------------------------------------------------------
# build_nack_response
# ---------------------------------------------------------------------------

class TestBuildNackResponse:
    def test_output_is_mllp_framed(self) -> None:
        result = build_nack_response(VALID_ADT_A01, "Test error")
        assert result[0:1] == MLLP_START
        assert result[-2:] == MLLP_END

    def test_msa_ae_present(self) -> None:
        result = build_nack_response(VALID_ADT_A01, "Parse failure")
        assert b"MSA|AE|" in result, "NACK must contain MSA segment with AE code"

    def test_msa_echoes_original_control_id(self) -> None:
        result = build_nack_response(VALID_ADT_A01, "Parse failure")
        assert b"MSA|AE|MSG001" in result

    def test_err_segment_contains_code_207(self) -> None:
        """ERR segment must include HL7 error code 207 (AIR-001)."""
        result = build_nack_response(VALID_ADT_A01, "Missing MSH field")
        assert b"207" in result, "NACK ERR segment must contain error code 207"

    def test_err_segment_contains_hl70357_table(self) -> None:
        result = build_nack_response(VALID_ADT_A01, "Parse error")
        assert b"HL70357" in result

    def test_err_segment_contains_error_text(self) -> None:
        error_text = "Segment MSH missing required field at position 9"
        result = build_nack_response(VALID_ADT_A01, error_text)
        assert error_text.encode("ascii") in result

    def test_error_text_truncated_at_200_chars(self) -> None:
        long_error = "X" * 300
        result = build_nack_response(VALID_ADT_A01, long_error)
        # 300-char string must be truncated — confirm ≤200 Xs appear consecutively
        assert b"X" * 201 not in result, "Error text must be truncated to 200 chars"

    def test_fallback_nack_when_raw_hl7_is_none(self) -> None:
        """NACK must be constructable even when the HL7 message cannot be parsed at all."""
        result = build_nack_response(None, "MLLP framing error: missing VT")
        assert result[0:1] == MLLP_START
        assert b"MSA|AE|UNKNOWN" in result
        assert b"207" in result

    def test_fallback_nack_when_msh_malformed(self) -> None:
        """NACK falls back to UNKNOWN control ID if MSH is present but malformed."""
        malformed = "MSH|^~\\&|EHR\r"  # Only 3 fields — insufficient
        result = build_nack_response(malformed, "Short MSH")
        assert b"MSA|AE|UNKNOWN" in result

    def test_returns_bytes(self) -> None:
        result = build_nack_response(VALID_ADT_A01, "error")
        assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# _extract_msh_fields (internal helper — tested for DoD coverage)
# ---------------------------------------------------------------------------

class TestExtractMshFields:
    def test_extracts_all_required_fields(self) -> None:
        fields = _extract_msh_fields(VALID_ADT_A01)
        assert fields["sending_app"] == "EHR"
        assert fields["sending_facility"] == "HOSP"
        assert fields["message_type"] == "ADT^A01"
        assert fields["message_control_id"] == "MSG001"
        assert fields["processing_id"] == "P"

    def test_raises_if_no_msh_segment(self) -> None:
        with pytest.raises(ValueError, match="No MSH segment"):
            _extract_msh_fields("EVN|A01|20260715\rPID|1\r")

    def test_raises_if_msh_has_insufficient_fields(self) -> None:
        with pytest.raises(ValueError, match=r"fewer than 11 fields|only \d+ fields"):
            _extract_msh_fields("MSH|^~\\&|EHR|HOSP\r")

    def test_extracts_adt_a02_fields(self) -> None:
        fields = _extract_msh_fields(VALID_ADT_A02)
        assert fields["message_control_id"] == "MSG002"
        assert fields["message_type"] == "ADT^A02"
