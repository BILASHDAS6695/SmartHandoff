---
id: TASK-002
title: "Create `hl7-listener/app/mllp/ack_builder.py` — HL7 ACK (AA) and NACK (AE+ERR) Message Builder"
user_story: US-011
epic: EP-001
sprint: 1
layer: Backend
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-011/TASK-001]
---

# TASK-002: Create `hl7-listener/app/mllp/ack_builder.py` — HL7 ACK (AA) and NACK (AE+ERR) Message Builder

> **Story:** US-011 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

Every received HL7 message requires an acknowledgement. The MLLP protocol mandates:

- **ACK (AA — Application Accept)**: Returned when the message was successfully received and parsed. MSH-9 = `ACK`, MSA-1 = `AA`, MSA-2 = original MSH-10 (Message Control ID).
- **NACK (AE — Application Error)**: Returned when parsing fails or a structural validation error occurs. MSA-1 = `AE`, ERR segment included with error code `207` ("Application Internal Error").

The Technical Notes in US-011 specify the exact ACK structure:
> *"ACK MSH-9 = `ACK`, MSA-1 = `AA`, MSA-2 = original MSH-10 (message control ID)"*

This module constructs these response messages from scratch using `hl7apy`. The TCP server (TASK-003) calls `build_ack_response()` or `build_nack_response()` immediately after frame extraction and hands back the MLLP-wrapped bytes to write to the socket — ensuring the 200ms ACK SLA in AIR-001 is met.

Design refs: AIR-001 (MLLP ACK within 200ms, NACK with error code 207), US-011 AC Scenario 1 and 2.

---

## Acceptance Criteria Addressed

| US-011 AC | Requirement |
|---|---|
| **Scenario 1** | `build_ack_response()` returns MLLP-wrapped MSH+MSA(AA) within the 200ms SLA |
| **Scenario 2** | `build_nack_response()` returns MLLP-wrapped MSH+MSA(AE)+ERR with error code 207 |
| **DoD** | ACK (MSH + MSA with `AA`) generated and returned within 200ms |
| **DoD** | NACK (MSH + MSA with `AE` + ERR segment) generated on parse failure |

---

## Implementation Steps

### 1. Create `hl7-listener/app/mllp/ack_builder.py`

```python
"""HL7 v2 ACK and NACK message builder for the MLLP TCP listener.

Constructs HL7 v2.5 acknowledgement messages to send back to the EHR after
receiving an inbound ADT message over MLLP.

ACK structure (Application Accept — AA):
    MSH|^~\\&|SmartHandoff|HOSP||EHR|{datetime}||ACK^A01|{msg_id}|P|2.5
    MSA|AA|{original_msg_control_id}|Message accepted

NACK structure (Application Error — AE):
    MSH|^~\\&|SmartHandoff|HOSP||EHR|{datetime}||ACK^A01|{msg_id}|P|2.5
    MSA|AE|{original_msg_control_id}|Application error
    ERR|||207^Application internal error^HL70357|E|||{error_text}

The output of both builders is already MLLP-wrapped (VT + HL7 bytes + FS + CR)
so the TCP server can write it directly to the socket without further processing.

Design refs:
    AIR-001  — MLLP ACK (AA) sent within 200ms; NACK (AE) on parse failure
    US-011   — DoD: ACK MSH-9=ACK, MSA-1=AA, MSA-2=original MSH-10
"""
from __future__ import annotations

import datetime
import logging
import uuid

from app.mllp.framing import wrap_hl7_message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SENDING_APP = "SmartHandoff"
_SENDING_FACILITY = "HOSP"
_HL7_VERSION = "2.5"
_FIELD_SEP = "|"
_ENCODING_CHARS = "^~\\&"
_CR = "\r"

# HL7 Table 0357 — Message Error Condition Codes
# 207 = Application internal error (used for parse failures per AIR-001)
_ERR_CODE_APP_INTERNAL = "207"
_ERR_CODE_TEXT = "Application internal error"
_ERR_CODE_TABLE = "HL70357"
_ERR_SEVERITY = "E"  # E = Error


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hl7_datetime() -> str:
    """Return current UTC timestamp in HL7 DTM format: YYYYMMDDHHMMSS."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")


def _new_msg_control_id() -> str:
    """Generate a unique message control ID for the outbound ACK/NACK MSH-10."""
    return uuid.uuid4().hex[:20].upper()


def _extract_msh_fields(raw_hl7: str) -> dict[str, str]:
    """Parse the MSH segment of an inbound HL7 message and return key fields.

    Extracts only the fields required to construct a well-formed ACK/NACK:
    - MSH-3  Sending Application  (becomes ACK Receiving Application)
    - MSH-4  Sending Facility     (becomes ACK Receiving Facility)
    - MSH-9  Message Type         (used in ACK MSH-9: ACK^<trigger>)
    - MSH-10 Message Control ID   (echoed in MSA-2)
    - MSH-11 Processing ID        (echoed verbatim — P for production, T for test)

    Args:
        raw_hl7: The complete HL7 message as a string, with segments
            separated by carriage returns (``\\r``).

    Returns:
        A dict with keys: ``sending_app``, ``sending_facility``,
        ``message_type``, ``message_control_id``, ``processing_id``.

    Raises:
        ValueError: If the message does not contain an MSH segment or the
            MSH segment has fewer than 11 fields.
    """
    for line in raw_hl7.split(_CR):
        if line.startswith("MSH"):
            fields = line.split(_FIELD_SEP)
            # MSH fields: MSH|^~\&|3|4|5|6|7|8|9|10|11|12...
            # Index:        0   1   2 3 4 5 6 7 8  9  10 11
            if len(fields) < 11:
                raise ValueError(
                    f"MSH segment has only {len(fields)} fields; expected ≥11"
                )
            return {
                "sending_app": fields[2],
                "sending_facility": fields[3],
                "message_type": fields[8],   # e.g. "ADT^A01"
                "message_control_id": fields[9],
                "processing_id": fields[10],
            }
    raise ValueError("No MSH segment found in HL7 message")


def _build_ack_msh(msh_fields: dict[str, str]) -> str:
    """Construct the MSH segment for an outbound ACK or NACK.

    The ACK MSH mirrors the original message's Sending App/Facility into
    the Receiving App/Facility fields, and sets MSH-9 to ``ACK``.
    """
    trigger = ""
    if "^" in msh_fields["message_type"]:
        trigger = "^" + msh_fields["message_type"].split("^")[1]

    fields = [
        "MSH",
        _ENCODING_CHARS,                       # MSH-2
        _SENDING_APP,                          # MSH-3 Sending App
        _SENDING_FACILITY,                     # MSH-4 Sending Facility
        msh_fields["sending_app"],             # MSH-5 Receiving App
        msh_fields["sending_facility"],        # MSH-6 Receiving Facility
        _hl7_datetime(),                       # MSH-7 Date/Time
        "",                                    # MSH-8 Security (empty)
        f"ACK{trigger}",                       # MSH-9 Message Type (ACK^A01)
        _new_msg_control_id(),                 # MSH-10 Message Control ID
        msh_fields["processing_id"],           # MSH-11 Processing ID
        _HL7_VERSION,                          # MSH-12 Version ID
    ]
    return _FIELD_SEP.join(fields)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_ack_response(raw_hl7: str) -> bytes:
    """Build an MLLP-wrapped HL7 ACK (AA) response for a successfully parsed message.

    The ACK is constructed per US-011 Technical Notes:
    - MSH-9  = ``ACK`` (or ``ACK^<trigger>`` if the original has a trigger)
    - MSA-1  = ``AA``  (Application Accept)
    - MSA-2  = original MSH-10 (Message Control ID, echoed verbatim)

    Args:
        raw_hl7: The complete inbound HL7 message as a string (already
            MLLP-unwrapped by ``framing.extract_hl7_message``).

    Returns:
        MLLP-wrapped bytes ready to write directly to the TCP socket.

    Raises:
        ValueError: If ``raw_hl7`` does not contain a parseable MSH segment.
    """
    msh_fields = _extract_msh_fields(raw_hl7)

    msh = _build_ack_msh(msh_fields)
    msa = _FIELD_SEP.join([
        "MSA",
        "AA",                                     # MSA-1 Acknowledgement Code
        msh_fields["message_control_id"],         # MSA-2 Message Control ID
        "Message accepted",                       # MSA-3 Text Message
    ])

    hl7_response = _CR.join([msh, msa]) + _CR
    logger.debug(
        "Built ACK for message_control_id=%s", msh_fields["message_control_id"]
    )
    return wrap_hl7_message(hl7_response.encode("ascii"))


def build_nack_response(raw_hl7: str | None, error_text: str) -> bytes:
    """Build an MLLP-wrapped HL7 NACK (AE + ERR) response for a failed message.

    Constructs MSH + MSA(AE) + ERR with error code 207 per AIR-001:
    *"NACK (AE) on parse failure"*, error code ``207`` ("Application
    Internal Error", HL7 Table 0357).

    Args:
        raw_hl7: The inbound HL7 message as a string, or ``None`` if the
            message could not be parsed at all (e.g. missing VT byte). When
            ``None``, the ACK MSH uses placeholder Receiving App/Facility
            values and MSA-2 is set to ``"UNKNOWN"``.
        error_text: Human-readable error description to include in ERR-8
            (Original Text). Must not contain PHI.

    Returns:
        MLLP-wrapped bytes ready to write directly to the TCP socket.
    """
    if raw_hl7 is not None:
        try:
            msh_fields = _extract_msh_fields(raw_hl7)
        except ValueError:
            msh_fields = None
    else:
        msh_fields = None

    if msh_fields is None:
        # Fallback MSH fields when the original message cannot be parsed at all
        msh_fields = {
            "sending_app": "UNKNOWN",
            "sending_facility": "UNKNOWN",
            "message_type": "ADT",
            "message_control_id": "UNKNOWN",
            "processing_id": "P",
        }

    msh = _build_ack_msh(msh_fields)
    msa = _FIELD_SEP.join([
        "MSA",
        "AE",                                      # MSA-1 Acknowledgement Code
        msh_fields["message_control_id"],          # MSA-2 Message Control ID
        "Application error",                       # MSA-3 Text Message
    ])

    # ERR segment — HL7 v2.5 ERR-3 (HL7 Error Code) + ERR-4 (Severity) + ERR-8 (User Message)
    err_code_triplet = (
        f"{_ERR_CODE_APP_INTERNAL}^{_ERR_CODE_TEXT}^{_ERR_CODE_TABLE}"
    )
    err = _FIELD_SEP.join([
        "ERR",
        "",                  # ERR-1 Error Code and Location (deprecated in v2.5)
        "",                  # ERR-2 Error Location
        err_code_triplet,    # ERR-3 HL7 Error Code
        _ERR_SEVERITY,       # ERR-4 Severity
        "",                  # ERR-5 Application Error Code
        "",                  # ERR-6 Application Error Parameter
        "",                  # ERR-7 Diagnostic Information
        error_text[:200],    # ERR-8 User Message (truncated; must not contain PHI)
    ])

    hl7_response = _CR.join([msh, msa, err]) + _CR
    logger.warning(
        "Built NACK for message_control_id=%s error=%s",
        msh_fields["message_control_id"],
        error_text,
    )
    return wrap_hl7_message(hl7_response.encode("ascii"))
```

---

## Validation

After creating the file, verify both builders produce non-empty MLLP frames:

```bash
cd hl7-listener
python - <<'EOF'
from app.mllp.ack_builder import build_ack_response, build_nack_response

sample_hl7 = (
    "MSH|^~\\&|EHR|HOSP|SmartHandoff|HOSP|20260715120000||ADT^A01|MSG001|P|2.5\r"
    "EVN|A01|20260715120000\r"
    "PID|1||MRN001^^^HOSP^MR||Doe^John||19800101|M\r"
)

ack = build_ack_response(sample_hl7)
assert ack[0:1] == b"\x0b", "ACK missing VT"
assert ack[-2:] == b"\x1c\x0d", "ACK missing FS+CR"
assert b"MSA|AA|MSG001" in ack, "ACK MSA not echoing control ID"
print(f"ACK: {len(ack)} bytes — OK")

nack = build_nack_response(sample_hl7, "Segment MSH missing required field")
assert b"MSA|AE|MSG001" in nack, "NACK MSA code incorrect"
assert b"207" in nack, "NACK ERR code 207 missing"
print(f"NACK: {len(nack)} bytes — OK")
EOF
```

---

## Definition of Done Checklist

- [ ] `hl7-listener/app/mllp/ack_builder.py` created
- [ ] `build_ack_response(raw_hl7)` returns MLLP-wrapped bytes with `MSA|AA|{original_control_id}`
- [ ] `build_nack_response(raw_hl7, error_text)` returns MLLP-wrapped bytes with `MSA|AE|{control_id}` and ERR segment containing code `207`
- [ ] `_extract_msh_fields` raises `ValueError` on missing or malformed MSH
- [ ] Fallback NACK works when `raw_hl7=None` (complete parse failure before MSH extraction)
- [ ] Validation script runs without errors
