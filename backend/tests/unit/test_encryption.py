"""Unit tests for PHI AES-256-GCM encryption primitives.

Tests cover:
- Non-deterministic encryption (EncryptedString): random nonce, ciphertext differs per call
- Deterministic encryption (DeterministicEncryptedString): same ciphertext per call
- Tamper detection: InvalidTag raised on modified ciphertext
- Key management: caching, validation, clear

US-007 acceptance criteria: AC1 (ciphertext stored), AC2 (transparent decrypt).
"""
from __future__ import annotations

import base64
import os
from unittest.mock import MagicMock

import pytest
from cryptography.exceptions import InvalidTag

from app.db.encryption import (
    _NONCE_BYTES,
    _TAG_BYTES,
    _decrypt,
    _encrypt,
    _encrypt_deterministic,
    DeterministicEncryptedString,
    EncryptedString,
)
from app.db.encryption_key import clear_cached_key, get_phi_encryption_key


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def phi_test_key(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Inject a fresh random 32-byte test key for each test.

    autouse=True ensures every test in this module gets an isolated key,
    preventing inter-test key state contamination.
    """
    clear_cached_key()
    test_key = os.urandom(32)
    key_b64 = base64.urlsafe_b64encode(test_key).decode()
    monkeypatch.setenv("PHI_ENCRYPTION_KEY", key_b64)
    monkeypatch.delenv("PHI_ENCRYPTION_KEY_SECRET_ID", raising=False)
    yield test_key
    clear_cached_key()


# ── Non-deterministic encryption ──────────────────────────────────────────────

class TestEncryptedString:
    """Tests for the non-deterministic EncryptedString._encrypt / _decrypt."""

    def test_encrypt_returns_string(self) -> None:
        ciphertext = _encrypt(b"John")
        assert isinstance(ciphertext, str)

    def test_encrypt_produces_valid_base64url(self) -> None:
        ciphertext = _encrypt(b"John Doe")
        decoded = base64.urlsafe_b64decode(ciphertext + "==")
        assert len(decoded) >= _NONCE_BYTES + _TAG_BYTES

    def test_encrypt_non_deterministic(self) -> None:
        """Same plaintext must produce different ciphertexts (non-deterministic)."""
        c1 = _encrypt(b"John")
        c2 = _encrypt(b"John")
        assert c1 != c2, "Non-deterministic encryption produced identical ciphertexts!"

    def test_round_trip_ascii(self) -> None:
        plaintext = b"John Doe"
        assert _decrypt(_encrypt(plaintext)) == plaintext

    def test_round_trip_unicode(self) -> None:
        plaintext = "José García".encode("utf-8")
        assert _decrypt(_encrypt(plaintext)) == plaintext

    def test_round_trip_long_string(self) -> None:
        # Simulate a 32KB discharge summary
        plaintext = b"X" * 32_768
        assert _decrypt(_encrypt(plaintext)) == plaintext

    def test_tamper_detection_raises_invalid_tag(self) -> None:
        """Modifying any byte of the ciphertext must raise InvalidTag."""
        ciphertext_b64 = _encrypt(b"John")
        raw = bytearray(base64.urlsafe_b64decode(ciphertext_b64 + "=="))
        raw[-1] ^= 0xFF  # Flip the last byte of the GCM tag
        tampered_b64 = base64.urlsafe_b64encode(bytes(raw)).decode()
        with pytest.raises(InvalidTag):
            _decrypt(tampered_b64)

    def test_decrypt_raises_on_truncated_payload(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            _decrypt(base64.urlsafe_b64encode(b"tooshort").decode())

    def test_null_passthrough(self) -> None:
        """TypeDecorator must pass None through unchanged (NULL semantics)."""
        td = EncryptedString()
        dialect = MagicMock()
        assert td.process_bind_param(None, dialect) is None
        assert td.process_result_value(None, dialect) is None

    def test_bind_param_encrypts(self) -> None:
        td = EncryptedString()
        dialect = MagicMock()
        result = td.process_bind_param("John", dialect)
        assert result is not None
        assert result != "John"
        assert isinstance(result, str)

    def test_result_value_decrypts(self) -> None:
        td = EncryptedString()
        dialect = MagicMock()
        ciphertext = td.process_bind_param("John", dialect)
        plaintext = td.process_result_value(ciphertext, dialect)
        assert plaintext == "John"


# ── Deterministic encryption ──────────────────────────────────────────────────

class TestDeterministicEncryptedString:
    """Tests for DeterministicEncryptedString._encrypt_deterministic."""

    def test_deterministic_same_input_same_output(self) -> None:
        """Same plaintext must always produce the same ciphertext."""
        c1 = _encrypt_deterministic(b"MRN12345")
        c2 = _encrypt_deterministic(b"MRN12345")
        assert c1 == c2, "Deterministic encryption produced different ciphertexts!"

    def test_deterministic_different_inputs_different_outputs(self) -> None:
        c1 = _encrypt_deterministic(b"MRN12345")
        c2 = _encrypt_deterministic(b"MRN99999")
        assert c1 != c2

    def test_deterministic_different_from_non_deterministic(self) -> None:
        """Deterministic and non-deterministic encryption of same plaintext differ."""
        nd = _encrypt(b"MRN12345")
        det = _encrypt_deterministic(b"MRN12345")
        assert nd != det

    def test_deterministic_decrypt_round_trip(self) -> None:
        ciphertext = _encrypt_deterministic(b"MRN12345")
        assert _decrypt(ciphertext) == b"MRN12345"

    def test_deterministic_bind_param(self) -> None:
        td = DeterministicEncryptedString()
        dialect = MagicMock()
        c1 = td.process_bind_param("MRN12345", dialect)
        c2 = td.process_bind_param("MRN12345", dialect)
        assert c1 == c2  # deterministic
        assert c1 != "MRN12345"  # encrypted

    def test_deterministic_null_passthrough(self) -> None:
        td = DeterministicEncryptedString()
        dialect = MagicMock()
        assert td.process_bind_param(None, dialect) is None
        assert td.process_result_value(None, dialect) is None


# ── Key management unit tests ─────────────────────────────────────────────────

class TestKeyManagement:
    def test_key_length_is_32_bytes(self) -> None:
        key = get_phi_encryption_key()
        assert len(key) == 32

    def test_key_cached_after_first_call(self) -> None:
        k1 = get_phi_encryption_key()
        k2 = get_phi_encryption_key()
        assert k1 is k2  # same object reference — cached

    def test_invalid_key_length_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clear_cached_key()
        short_key_b64 = base64.urlsafe_b64encode(b"tooshort").decode()
        monkeypatch.setenv("PHI_ENCRYPTION_KEY", short_key_b64)
        with pytest.raises(ValueError, match="32 bytes"):
            get_phi_encryption_key()

    def test_missing_env_var_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clear_cached_key()
        monkeypatch.delenv("PHI_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("PHI_ENCRYPTION_KEY_SECRET_ID", raising=False)
        with pytest.raises(RuntimeError, match="not configured"):
            get_phi_encryption_key()
