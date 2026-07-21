# backend/app/db/encryption.py — STUB (replace with US-007 full implementation)
"""Stub PHI encryption TypeDecorators.

Replace this file with the full US-007 implementation before deploying to any environment.
# TODO(US-007): Replace stub with AES-256-GCM implementation
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Dialect


class EncryptedString(sa.TypeDecorator):
    """Stub: stores plaintext. Replace with AES-256-GCM implementation (US-007)."""

    impl = sa.Text
    cache_ok = True

    def process_bind_processor(self, dialect: Dialect):
        return lambda value: value  # No-op stub

    def process_result_processor(self, dialect: Dialect, coltype):
        return lambda value: value  # No-op stub


class DeterministicEncryptedString(EncryptedString):
    """Stub: deterministic variant for MRN uniqueness. Replace with US-007."""
    pass
