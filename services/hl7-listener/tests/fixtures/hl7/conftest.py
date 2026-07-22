"""Shared pytest fixtures for loading HL7 test fixture files.

Provides a ``load_hl7_fixture(filename)`` helper that reads a fixture file
from the ``tests/fixtures/hl7/`` directory and normalises line endings to CR.
"""
from __future__ import annotations

import pathlib

_FIXTURE_DIR = pathlib.Path(__file__).parent


def load_hl7_fixture(filename: str) -> str:
    """Read an HL7 fixture file and return its content with CR line endings.

    Args:
        filename: Filename relative to ``tests/fixtures/hl7/``.

    Returns:
        HL7 message string with ``\\r``-terminated segments.
    """
    path = _FIXTURE_DIR / filename
    text = path.read_text(encoding="utf-8")
    # Normalise to CR-only line endings (HL7 standard)
    return text.replace("\r\n", "\r").replace("\n", "\r")
