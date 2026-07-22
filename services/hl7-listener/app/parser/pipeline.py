"""End-to-end HL7 parse → route pipeline for the MLLP server.

Provides a single entry point used by ``app/mllp/server.py`` to process
an inbound raw HL7 message string.  Separates the MLLP server from the
parser and router internals.

Usage in server.py::

    from app.parser.pipeline import process_hl7_message

    try:
        result = process_hl7_message(raw_hl7_str)
    except HL7ValidationError as exc:
        # Build NACK
        ...

Design refs: US-012, AIR-002, FR-002.
"""
from __future__ import annotations

import logging
from typing import Any

from app.parser.hl7_parser import HL7Parser
from app.parser.models import HL7ValidationError
from app.parser.router import default_router

logger = logging.getLogger(__name__)

_parser = HL7Parser()


def process_hl7_message(raw_hl7: str) -> Any:
    """Parse a raw HL7 string and route the resulting ADTEvent.

    Args:
        raw_hl7: CR-terminated HL7 v2 text (MLLP framing already stripped).

    Returns:
        The return value of the registered handler (or None for stubs).

    Raises:
        HL7ValidationError: Propagated from parser or router for any
            structural failure — caller converts this to a NACK.
    """
    event = _parser.parse(raw_hl7)
    return default_router.route(event)
