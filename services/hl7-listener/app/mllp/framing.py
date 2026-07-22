"""MLLP (Minimal Lower Layer Protocol) frame parsing and serialisation.

MLLP wraps every HL7 v2 message with a three-byte envelope:

    VT  (0x0B) — Vertical Tab     — Start-of-block byte
    FS  (0x1C) — File Separator   — End-of-block byte   ┐ two-byte trailer
    CR  (0x0D) — Carriage Return  — End-of-block byte   ┘

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

MLLP_START: bytes = b"\x0b"        # VT — Vertical Tab   (0x0B)
MLLP_END: bytes = b"\x1c\x0d"     # FS (0x1C) + CR (0x0D)


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
