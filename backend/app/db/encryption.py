# backend/app/db/encryption.py
"""PHI field-level encryption for SQLAlchemy ORM columns.

Implements AES-256-GCM encryption as required by:
  - BR-020: PHI must be encrypted at the application layer
  - SEC-004: AES-256 encryption at rest (defense-in-depth with Cloud SQL CMEK)
  - DR-002: Named PHI columns must store ciphertext, not plaintext
  - ADR-007: SQLAlchemy TypeDecorator pattern with GCP Secret Manager key loading

Two TypeDecorator classes are provided:

  EncryptedString
    Non-deterministic: generates a fresh random 96-bit nonce per encryption
    operation. Two encryptions of the same plaintext produce different
    ciphertexts. Use for all PHI fields except MRN.

  DeterministicEncryptedString
    Deterministic: derives the nonce from HMAC-SHA256(key, plaintext)[:12].
    Two encryptions of the same plaintext always produce the same ciphertext,
    enabling a PostgreSQL UNIQUE constraint on the encrypted column (DR-020).
    Use ONLY for `patient.mrn_encrypted`.

  EncryptedText
    Subclass of EncryptedString that uses PostgreSQL TEXT (no length cap).
    Use for large PHI fields: Document.content, ChatbotTranscript.message_content.

Wire format (both variants):
    base64url( nonce(12 bytes) || aesgcm_output(plaintext_len + 16 bytes) )

    AESGCM.encrypt() appends the 16-byte authentication tag automatically.
    On decrypt, AESGCM.decrypt() verifies the tag and raises InvalidTag if
    the ciphertext has been tampered with.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.db.encryption_key import get_phi_encryption_key

# ── AESGCM import with clear error if cryptography is missing ─────────────────
try:
    from cryptography.exceptions import InvalidTag  # noqa: F401 (re-exported)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as exc:
    raise ImportError(
        "The 'cryptography' package is required for PHI field encryption. "
        "Add 'cryptography>=42.0.0' to requirements.txt."
    ) from exc

_NONCE_BYTES: int = 12   # GCM standard: 96-bit nonce
_TAG_BYTES: int = 16     # GCM authentication tag appended by AESGCM.encrypt()


# ── Non-deterministic TypeDecorator ──────────────────────────────────────────

class EncryptedString(TypeDecorator[str]):
    """Non-deterministic AES-256-GCM encrypted VARCHAR column.

    Encrypts on INSERT/UPDATE (process_bind_param) and decrypts
    transparently on SELECT (process_result_value).

    Each encryption uses a fresh random 96-bit nonce — two encryptions
    of the same plaintext produce different ciphertexts.

    Wire format stored in the database:
        base64url( nonce[12] || aesgcm_encrypt_output[plaintext_len + 16] )

    Args:
        length: VARCHAR storage length in characters. Default 256.
                Must accommodate: ceil((12 + plaintext_bytes + 16) / 3) * 4
    """

    impl = String
    cache_ok = True  # TypeDecorator is stateless; key loaded via module cache

    def __init__(self, length: int = 256, *args: Any, **kwargs: Any) -> None:
        super().__init__(length, *args, **kwargs)

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Encrypt plaintext → ciphertext before writing to the database."""
        if value is None:
            return None
        return _encrypt(value.encode("utf-8"))

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Decrypt ciphertext → plaintext after reading from the database."""
        if value is None:
            return None
        return _decrypt(value).decode("utf-8")


class EncryptedText(EncryptedString):
    """EncryptedString variant backed by PostgreSQL TEXT (no VARCHAR length cap).

    Use for large PHI fields: Document.content, ChatbotTranscript.message_content.
    AES-256-GCM + base64 adds ~33% overhead, so a 32KB document grows to ~44KB.
    """

    impl = Text

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Do not forward a length arg — Text has no length parameter.
        super(EncryptedString, self).__init__(*args, **kwargs)


# ── Deterministic TypeDecorator ───────────────────────────────────────────────

class DeterministicEncryptedString(TypeDecorator[str]):
    """Deterministic AES-256-GCM encrypted VARCHAR column for MRN deduplication.

    Same plaintext always produces the same ciphertext because the 96-bit
    nonce is derived from HMAC-SHA256(key, plaintext)[:12].

    This enables a PostgreSQL UNIQUE constraint on the encrypted column,
    satisfying DR-020 (MRN deduplication without exposing plaintext MRNs).

    Security note: Use ONLY for `patient.mrn_encrypted`. For all other
    PHI fields, use `EncryptedString` (random nonce, non-deterministic).

    Wire format (identical to EncryptedString for seamless TASK-007 re-encryption):
        base64url( hmac_nonce[12] || aesgcm_encrypt_output[plaintext_len + 16] )

    Args:
        length: VARCHAR storage length. Default 256.
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int = 256, *args: Any, **kwargs: Any) -> None:
        super().__init__(length, *args, **kwargs)

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Deterministically encrypt plaintext → ciphertext before DB write."""
        if value is None:
            return None
        return _encrypt_deterministic(value.encode("utf-8"))

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Decrypt ciphertext → plaintext after DB read.

        Re-uses the same `_decrypt` helper as `EncryptedString` because the
        wire format is identical — the nonce is always the first 12 bytes.
        """
        if value is None:
            return None
        return _decrypt(value).decode("utf-8")


# ── Cryptographic helpers ─────────────────────────────────────────────────────

def _encrypt(plaintext: bytes) -> str:
    """Encrypt plaintext bytes with AES-256-GCM using a random nonce.

    Returns base64url-encoded: nonce || aesgcm_output
    """
    key = get_phi_encryption_key()
    nonce = os.urandom(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    encrypted = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    payload = nonce + encrypted
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _encrypt_deterministic(plaintext: bytes) -> str:
    """Encrypt plaintext bytes with AES-256-GCM using an HMAC-derived nonce.

    The nonce is deterministic: HMAC-SHA256(key, plaintext)[:12].
    Same plaintext + same key → same ciphertext (enables UNIQUE index on MRN).

    Returns base64url-encoded: hmac_nonce || aesgcm_output
    """
    key = get_phi_encryption_key()
    # Derive a deterministic, collision-resistant nonce.
    # HMAC-SHA256 output is 32 bytes; take first 12 as the GCM nonce.
    hmac_digest = hmac.new(key, plaintext, hashlib.sha256).digest()
    nonce = hmac_digest[:_NONCE_BYTES]  # 12 bytes
    aesgcm = AESGCM(key)
    encrypted = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    payload = nonce + encrypted
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decrypt(ciphertext_b64: str) -> bytes:
    """Decrypt a base64url-encoded payload produced by `_encrypt` or `_encrypt_deterministic`.

    Raises:
        cryptography.exceptions.InvalidTag: If the ciphertext has been
            tampered with or the wrong key is being used. Do NOT swallow
            this exception — it indicates data corruption or a key mismatch.
        ValueError: If the payload is too short to contain a valid nonce.
    """
    payload = base64.urlsafe_b64decode(ciphertext_b64 + "==")  # padding-tolerant
    if len(payload) < _NONCE_BYTES + _TAG_BYTES:
        raise ValueError(
            f"Encrypted payload is too short ({len(payload)} bytes). "
            f"Expected at least {_NONCE_BYTES + _TAG_BYTES} bytes (nonce + tag)."
        )
    nonce = payload[:_NONCE_BYTES]
    encrypted = payload[_NONCE_BYTES:]
    key = get_phi_encryption_key()
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, encrypted, associated_data=None)


__all__ = [
    "EncryptedString",
    "EncryptedText",
    "DeterministicEncryptedString",
    "get_phi_encryption_key",
    "_encrypt",
    "_encrypt_deterministic",
    "_decrypt",
    "_NONCE_BYTES",
    "_TAG_BYTES",
]

