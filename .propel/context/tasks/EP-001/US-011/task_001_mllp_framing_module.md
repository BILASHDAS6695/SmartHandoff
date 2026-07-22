---
id: TASK-001
title: "Create `hl7-listener/app/mllp/framing.py` — MLLP VT/FS/CR Frame Parsing & Serialisation"
user_story: US-011
epic: EP-001
sprint: 1
layer: Backend
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: []
---

# TASK-001: Create `hl7-listener/app/mllp/framing.py` — MLLP VT/FS/CR Frame Parsing & Serialisation

> **Story:** US-011 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

MLLP (Minimal Lower Layer Protocol) wraps every HL7 v2 message with a three-byte envelope:

| Byte | Hex | Name | Position |
|------|-----|------|----------|
| `\x0b` | 0x0B | VT — Vertical Tab | Start of block |
| `\x1c` | 0x1C | FS — File Separator | End of block (first byte) |
| `\x0d` | 0x0D | CR — Carriage Return | End of block (second byte) |

A well-formed MLLP frame is: `VT + <HL7 message bytes> + FS + CR`.

This framing module is the lowest-level primitive in the HL7 Listener service. Every other module (ACK builder, TCP server) depends on it to extract raw HL7 bytes from the TCP stream and to wrap outgoing ACK/NACK bytes before they are written back to the socket.

Design refs: AIR-001 (200ms ACK SLA), AIR-004 (MLLP connection management), US-011 DoD.

---

## Acceptance Criteria Addressed

| US-011 AC | Requirement |
|---|---|
| **DoD** | MLLP framing: VT (0x0B) start block + FS (0x1C) end block + CR parsing implemented |
| **Scenario 1** | Valid MLLP-framed ADT^A01 message correctly unwrapped so hl7apy can parse it |
| **Scenario 2** | Malformed frame (missing VT) raises `MllpFramingError` → NACK path triggered |

---

## Implementation Steps

### 1. Scaffold the `hl7-listener` service directory

Create the following directory structure (all files listed in this task or subsequent tasks):

```
hl7-listener/
├── app/
│   ├── __init__.py
│   ├── main.py                # asyncio entry point (TASK-003)
│   ├── mllp/
│   │   ├── __init__.py
│   │   ├── framing.py         # THIS TASK
│   │   ├── ack_builder.py     # TASK-002
│   │   └── server.py          # TASK-003
│   └── health.py              # TASK-004
├── tests/
│   └── unit/
│       └── mllp/
│           ├── __init__.py
│           ├── test_framing.py      # TASK-005
│           └── test_ack_builder.py  # TASK-005
├── requirements.txt
└── Dockerfile
```

Create the scaffold files now:

```bash
mkdir -p hl7-listener/app/mllp hl7-listener/tests/unit/mllp
touch hl7-listener/app/__init__.py
touch hl7-listener/app/mllp/__init__.py
touch hl7-listener/tests/__init__.py
touch hl7-listener/tests/unit/__init__.py
touch hl7-listener/tests/unit/mllp/__init__.py
```

### 2. Create `hl7-listener/requirements.txt`

```
# HL7 parsing
hl7apy==1.3.4

# Prometheus metrics (TASK-004)
prometheus_client>=0.20.0

# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

### 3. Create `hl7-listener/app/mllp/framing.py`

```python
"""MLLP (Minimal Lower Layer Protocol) frame parsing and serialisation.

MLLP wraps every HL7 v2 message with:
    VT  (0x0B) — start-of-block byte
    FS  (0x1C) — end-of-block byte   } two-byte trailer
    CR  (0x0D) — carriage return     }

Well-formed frame: b'\\x0b' + <HL7 bytes> + b'\\x1c\\x0d'

This module operates on raw bytes only — it has no knowledge of HL7 message
content. The asyncio TCP server (server.py) uses these helpers to extract the
HL7 payload from the incoming TCP stream and to wrap outgoing ACK/NACK bytes
before writing them back to the socket.

Design refs:
    AIR-001  — MLLP ACK within 200ms
    AIR-004  — MLLP connection management
    US-011   — Build MLLP TCP Listener for HL7 ADT Event Ingestion
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# MLLP constants
# ---------------------------------------------------------------------------

MLLP_START: bytes = b"\x0b"        # VT — Vertical Tab (0x0B)
MLLP_END: bytes = b"\x1c\x0d"     # FS (0x1C) + CR (0x0D)

_MLLP_END_FS: int = 0x1C
_MLLP_END_CR: int = 0x0D


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MllpFramingError(ValueError):
    """Raised when an inbound byte sequence cannot be decoded as a valid MLLP frame.

    The TCP server catches this exception and triggers the NACK path (AIR-001).
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_hl7_message(raw: bytes) -> bytes:
    """Strip MLLP framing and return the raw HL7 message bytes.

    Args:
        raw: Raw bytes received from the TCP socket, including MLLP framing.

    Returns:
        The HL7 message bytes without the VT start byte or FS+CR trailer.

    Raises:
        MllpFramingError: If ``raw`` does not start with VT (0x0B) or does
            not contain the FS+CR (0x1C 0x0D) end-of-block sequence.

    Example::

        hl7_bytes = extract_hl7_message(b"\\x0bMSH|...|\\x1c\\x0d")
        # → b"MSH|...|"
    """
    if not raw:
        raise MllpFramingError("Empty frame received — no VT start byte")

    if raw[0:1] != MLLP_START:
        raise MllpFramingError(
            f"Frame does not begin with VT (0x0B); got 0x{raw[0]:02X}"
        )

    end_pos = raw.find(MLLP_END)
    if end_pos == -1:
        raise MllpFramingError(
            "Frame missing FS+CR (0x1C 0x0D) end-of-block sequence"
        )

    # Slice between VT and FS+CR (exclusive of both framing bytes)
    hl7_bytes = raw[1:end_pos]

    if not hl7_bytes:
        raise MllpFramingError("Frame contains VT and FS+CR but no HL7 content")

    return hl7_bytes


def wrap_hl7_message(hl7_bytes: bytes) -> bytes:
    """Wrap raw HL7 message bytes in MLLP framing for transmission.

    Args:
        hl7_bytes: Raw HL7 message bytes (e.g. an ACK or NACK message).

    Returns:
        MLLP-framed bytes: VT + hl7_bytes + FS + CR.

    Raises:
        ValueError: If ``hl7_bytes`` is empty.

    Example::

        frame = wrap_hl7_message(b"MSH|^~\\\\&|ACK|...")
        # → b"\\x0bMSH|^~\\\\&|ACK|...\\x1c\\x0d"
    """
    if not hl7_bytes:
        raise ValueError("Cannot wrap empty bytes in MLLP framing")

    return MLLP_START + hl7_bytes + MLLP_END


def read_mllp_frame(buffer: bytes) -> tuple[bytes | None, bytes]:
    """Extract one complete MLLP frame from a byte buffer without raising.

    Used by the TCP server's streaming reader to detect whether a complete
    frame has arrived. Returns the extracted HL7 bytes and the remaining
    unconsumed buffer.

    Args:
        buffer: Accumulated bytes from the TCP socket read loop.

    Returns:
        A ``(hl7_bytes, remainder)`` tuple:
        - ``hl7_bytes`` is the unwrapped HL7 content if a complete frame is
          present; ``None`` if the frame is incomplete (more bytes expected).
        - ``remainder`` is the bytes after the end of the consumed frame
          (typically empty; non-empty if multiple frames arrived in one read).

    Note:
        Callers should check for ``MllpFramingError`` separately before calling
        this function — if the buffer starts with a non-VT byte it indicates a
        protocol violation and the connection should be closed.
    """
    if MLLP_START not in buffer:
        return None, buffer  # No VT yet — waiting for frame start

    start_idx = buffer.index(MLLP_START)
    end_idx = buffer.find(MLLP_END, start_idx + 1)

    if end_idx == -1:
        return None, buffer  # VT found but FS+CR not yet arrived

    hl7_bytes = buffer[start_idx + 1 : end_idx]
    remainder = buffer[end_idx + len(MLLP_END) :]

    return hl7_bytes, remainder
```

---

## Validation

After creating the file, verify the module imports without errors:

```bash
cd hl7-listener
python -c "from app.mllp.framing import extract_hl7_message, wrap_hl7_message, MllpFramingError; print('framing.py: OK')"
```

Expected output: `framing.py: OK`

---

## Definition of Done Checklist

- [ ] `hl7-listener/app/mllp/framing.py` created with `extract_hl7_message`, `wrap_hl7_message`, `read_mllp_frame`, and `MllpFramingError`
- [ ] `MLLP_START = b'\x0b'` and `MLLP_END = b'\x1c\x0d'` constants defined
- [ ] `MllpFramingError(ValueError)` raised on missing VT, missing FS+CR, and empty content
- [ ] Service scaffold directory structure created (`hl7-listener/app/mllp/`, `tests/unit/mllp/`)
- [ ] `hl7-listener/requirements.txt` created with `hl7apy==1.3.4` and `prometheus_client>=0.20.0`
- [ ] Module imports successfully
