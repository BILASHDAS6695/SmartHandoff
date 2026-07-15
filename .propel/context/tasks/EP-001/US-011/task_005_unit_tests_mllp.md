---
id: TASK-005
title: "Write pytest Unit Tests — MLLP Framing, ACK/NACK Generation, and Connection Semaphore"
user_story: US-011
epic: EP-001
sprint: 1
layer: Testing
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-011/TASK-001, US-011/TASK-002, US-011/TASK-003]
---

# TASK-005: Write pytest Unit Tests — MLLP Framing, ACK/NACK Generation, and Connection Semaphore

> **Story:** US-011 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

The US-011 DoD requires: *"Unit tests for MLLP frame parsing and ACK/NACK generation"*.

Tests cover four areas:

1. **MLLP frame parsing** — `framing.py`: valid frames extracted, malformed frames raise `MllpFramingError`, `read_mllp_frame` handles partial and multi-frame buffers.
2. **ACK/NACK construction** — `ack_builder.py`: ACK contains `MSA|AA` with echoed control ID; NACK contains `MSA|AE` and ERR code 207; fallback NACK works when `raw_hl7=None`.
3. **TCP server connection limit** — `server.py`: semaphore enforced; NACK sent on parse error path.
4. **Metrics integration** — `metrics.py`: Counter/Histogram/Gauge are importable and have correct metric names.

Tests use `pytest-asyncio` for async test cases and `unittest.mock` for controlled failure injection. No live TCP sockets are opened in unit tests — async stream pairs are simulated using `asyncio.StreamReader` / `asyncio.StreamWriter` via `asyncio.open_connection` against a loopback test server.

Coverage target: ≥80% branch coverage on `app/mllp/framing.py` and `app/mllp/ack_builder.py` (TR-020).

---

## Acceptance Criteria Addressed

| US-011 AC | Requirement |
|---|---|
| **Scenario 1** | `test_ack_builder.py::test_build_ack_response_valid` asserts `MSA|AA|{control_id}` |
| **Scenario 2** | `test_ack_builder.py::test_build_nack_response` asserts `MSA|AE` + ERR code `207` |
| **DoD** | Unit tests for MLLP frame parsing and ACK/NACK generation |

---

## Implementation Steps

### 1. Create `hl7-listener/tests/unit/mllp/test_framing.py`

```python
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
        with pytest.raises(MllpFramingError, match="missing FS\\+CR"):
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
        hl7_bytes, remainder = read_mllp_frame(b"garbage")
        assert hl7_bytes is None

    def test_multi_frame_buffer_returns_first_only(self) -> None:
        """When two complete frames are in the buffer, only the first is returned."""
        second_hl7 = b"MSH|^~\\&|EHR|HOSP|||20260715||ADT^A02|MSG002|P|2.5\r"
        buffer = make_mllp_frame(SAMPLE_HL7) + make_mllp_frame(second_hl7)
        hl7_bytes, remainder = read_mllp_frame(buffer)
        assert hl7_bytes == SAMPLE_HL7
        # Remainder should be the second complete frame
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
```

### 2. Create `hl7-listener/tests/unit/mllp/test_ack_builder.py`

```python
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

    def test_err_segment_contains_error_text(self) -> None:
        error_text = "Segment MSH missing required field at position 9"
        result = build_nack_response(VALID_ADT_A01, error_text)
        assert error_text.encode("ascii") in result

    def test_error_text_truncated_at_200_chars(self) -> None:
        long_error = "X" * 300
        result = build_nack_response(VALID_ADT_A01, long_error)
        # The 300-char string must be truncated; confirm <300 chars in error field
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


# ---------------------------------------------------------------------------
# _extract_msh_fields (internal helper)
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
        with pytest.raises(ValueError, match="fewer than 11 fields|only.*fields"):
            _extract_msh_fields("MSH|^~\\&|EHR|HOSP\r")
```

### 3. Create `hl7-listener/pytest.ini`

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = --tb=short -q
```

### 4. Run tests and confirm coverage

```bash
cd hl7-listener
pip install -r requirements.txt

pytest tests/unit/mllp/ -v \
  --cov=app/mllp/framing \
  --cov=app/mllp/ack_builder \
  --cov-report=term-missing \
  --cov-fail-under=80
```

Expected: all tests pass, coverage ≥80% on both modules.

---

## Definition of Done Checklist

- [ ] `hl7-listener/tests/unit/mllp/test_framing.py` created with ≥10 test cases
- [ ] `hl7-listener/tests/unit/mllp/test_ack_builder.py` created with ≥11 test cases
- [ ] `hl7-listener/pytest.ini` created with `asyncio_mode = auto`
- [ ] All tests pass: `pytest tests/unit/mllp/ -v`
- [ ] Coverage ≥80% on `app/mllp/framing.py` and `app/mllp/ack_builder.py`
- [ ] No test accesses PHI fixtures (patient name, DOB, MRN are generic placeholders)
