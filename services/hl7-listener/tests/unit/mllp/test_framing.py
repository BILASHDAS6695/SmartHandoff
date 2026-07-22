"""Unit tests for app/mllp/framing.py — MLLP frame parsing and serialisation.

Test coverage:
  - extract_hl7_message: valid frame, empty input, missing VT, missing FS+CR, empty payload
  - wrap_hl7_message: valid bytes, empty bytes (ValueError)
  - read_mllp_frame: complete frame, incomplete frame, multi-frame buffer, no VT

Coverage target: ≥80% branch coverage on app/mllp/framing.py (TR-020).
"""
from __future__ import annotations

import pytest

from app.mllp.framing import (
    MLLP_END,
    MLLP_START,
    MllpFramingError,
    extract_hl7_message,
    read_mllp_frame,
    wrap_hl7_message,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_HL7 = (
    b"MSH|^~\\&|EHR|HOSP|SmartHandoff|HOSP|20260715120000||ADT^A01|MSG001|P|2.5\r"
    b"EVN|A01|20260715120000\r"
    b"PID|1||MRN001^^^HOSP^MR\r"
)


def make_mllp_frame(hl7_bytes: bytes) -> bytes:
    """Helper: wrap HL7 bytes in MLLP framing."""
    return MLLP_START + hl7_bytes + MLLP_END


# ---------------------------------------------------------------------------
# extract_hl7_message
# ---------------------------------------------------------------------------

class TestExtractHl7Message:
    def test_valid_frame_returns_hl7_bytes(self) -> None:
        frame = make_mllp_frame(SAMPLE_HL7)
        result = extract_hl7_message(frame)
        assert result == SAMPLE_HL7

    def test_empty_input_raises_framing_error(self) -> None:
        with pytest.raises(MllpFramingError, match="Empty frame"):
            extract_hl7_message(b"")

    def test_missing_vt_raises_framing_error(self) -> None:
        """Frame without VT start byte must be rejected."""
        with pytest.raises(MllpFramingError, match="does not begin with VT"):
            extract_hl7_message(SAMPLE_HL7 + MLLP_END)

    def test_missing_fs_cr_raises_framing_error(self) -> None:
        """Frame with VT but no FS+CR terminator must be rejected."""
        with pytest.raises(MllpFramingError, match=r"missing FS\+CR"):
            extract_hl7_message(MLLP_START + SAMPLE_HL7)

    def test_empty_payload_between_framing_raises_error(self) -> None:
        """VT immediately followed by FS+CR with no content is invalid."""
        with pytest.raises(MllpFramingError, match="no HL7 content"):
            extract_hl7_message(MLLP_START + MLLP_END)

    def test_content_after_fscr_is_ignored(self) -> None:
        """Bytes after the FS+CR terminator are ignored (not part of this frame)."""
        frame = make_mllp_frame(SAMPLE_HL7) + b"trailing garbage"
        result = extract_hl7_message(frame)
        assert result == SAMPLE_HL7

    def test_mllp_framing_error_is_value_error_subclass(self) -> None:
        """MllpFramingError must be a subclass of ValueError."""
        with pytest.raises(ValueError):
            extract_hl7_message(b"")


# ---------------------------------------------------------------------------
# wrap_hl7_message
# ---------------------------------------------------------------------------

class TestWrapHl7Message:
    def test_wraps_bytes_with_vt_and_fscr(self) -> None:
        wrapped = wrap_hl7_message(SAMPLE_HL7)
        assert wrapped[0:1] == MLLP_START
        assert wrapped[-2:] == MLLP_END
        assert wrapped[1:-2] == SAMPLE_HL7

    def test_roundtrip_extract_after_wrap(self) -> None:
        wrapped = wrap_hl7_message(SAMPLE_HL7)
        extracted = extract_hl7_message(wrapped)
        assert extracted == SAMPLE_HL7

    def test_empty_bytes_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Cannot wrap empty bytes"):
            wrap_hl7_message(b"")

    def test_wrapped_length_equals_payload_plus_three(self) -> None:
        """Wrapped frame should be len(payload) + 3 (VT + FS + CR)."""
        wrapped = wrap_hl7_message(SAMPLE_HL7)
        assert len(wrapped) == len(SAMPLE_HL7) + 3


# ---------------------------------------------------------------------------
# read_mllp_frame
# ---------------------------------------------------------------------------

class TestReadMllpFrame:
    def test_complete_frame_extracted(self) -> None:
        buffer = make_mllp_frame(SAMPLE_HL7)
        hl7_bytes, remainder = read_mllp_frame(buffer)
        assert hl7_bytes == SAMPLE_HL7
        assert remainder == b""

    def test_incomplete_frame_returns_none(self) -> None:
        """Buffer has VT but no FS+CR yet — waiting for more data."""
        buffer = MLLP_START + SAMPLE_HL7[:50]
        hl7_bytes, remainder = read_mllp_frame(buffer)
        assert hl7_bytes is None
        assert remainder == buffer  # buffer returned unchanged

    def test_no_vt_returns_none(self) -> None:
        """Buffer contains no VT byte — no frame start detected."""
        hl7_bytes, _ = read_mllp_frame(b"garbage data")
        assert hl7_bytes is None

    def test_empty_buffer_returns_none(self) -> None:
        hl7_bytes, remainder = read_mllp_frame(b"")
        assert hl7_bytes is None
        assert remainder == b""

    def test_multi_frame_buffer_returns_first_only(self) -> None:
        """When two complete frames are in the buffer, only the first is returned."""
        second_hl7 = b"MSH|^~\\&|EHR|HOSP|||20260715||ADT^A02|MSG002|P|2.5\r"
        buffer = make_mllp_frame(SAMPLE_HL7) + make_mllp_frame(second_hl7)
        hl7_bytes, remainder = read_mllp_frame(buffer)
        assert hl7_bytes == SAMPLE_HL7
        assert remainder == make_mllp_frame(second_hl7)

    def test_remainder_allows_second_frame_extraction(self) -> None:
        """Iterating on the remainder yields the second frame."""
        second_hl7 = b"MSH|^~\\&|EHR|HOSP|||20260715||ADT^A02|MSG002|P|2.5\r"
        buffer = make_mllp_frame(SAMPLE_HL7) + make_mllp_frame(second_hl7)

        hl7_first, remainder = read_mllp_frame(buffer)
        hl7_second, final_remainder = read_mllp_frame(remainder)

        assert hl7_first == SAMPLE_HL7
        assert hl7_second == second_hl7
        assert final_remainder == b""
