---
id: TASK-006
title: "Write Unit Tests — Ciphertext Storage, Transparent ORM Decryption, MRN Uniqueness, and Key Rotation"
user_story: US-007
epic: EP-DATA
sprint: 1
layer: Backend (Test)
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-006: Write Unit Tests — Ciphertext Storage, Transparent ORM Decryption, MRN Uniqueness, and Key Rotation

> **Story:** US-007 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend (Test) | **Est:** 3 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-007 has four explicit acceptance criterion scenarios. Each requires a corresponding test. This task implements the full test suite covering:

1. **AC1** — PHI columns store ciphertext in the DB (not plaintext)
2. **AC2** — ORM access transparently decrypts to plaintext (no explicit decrypt call by caller)
3. **AC3** — Duplicate MRN raises `UniqueConstraintViolation` via deterministic encryption
4. **AC4** — Re-encryption with a new key succeeds; ORM decryption continues to work after rotation

Tests are organised into two files:
- `backend/tests/unit/test_encryption.py` — pure unit tests for `_encrypt`, `_decrypt`, `_encrypt_deterministic`, `get_phi_encryption_key()` (no DB required)
- `backend/tests/integration/test_phi_encryption_orm.py` — integration tests against a real PostgreSQL 15 container (testcontainers, same pattern as US-006/TASK-008)

---

## Acceptance Criteria Addressed

| US-007 AC | Test | File |
|---|---|---|
| **Scenario 1** | `test_phi_stored_as_ciphertext` | `test_phi_encryption_orm.py` |
| **Scenario 2** | `test_orm_decrypts_transparently` | `test_phi_encryption_orm.py` |
| **Scenario 3** | `test_mrn_unique_constraint_violation` | `test_phi_encryption_orm.py` |
| **Scenario 4** | `test_key_rotation_reencryption` | `test_phi_encryption_orm.py` |
| **DoD** | Unit tests: raw DB = ciphertext, ORM access = plaintext | `test_encryption.py` |

---

## Implementation Steps

### 1. Create `backend/tests/unit/test_encryption.py`

Pure unit tests — no database, no Docker, no network. These run in milliseconds in CI.

```python
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

import pytest
from cryptography.exceptions import InvalidTag

from app.db.encryption import (
    _NONCE_BYTES,
    _TAG_BYTES,
    _decrypt,
    _encrypt,
    _encrypt_deterministic,
)
from app.db.encryption_key import clear_cached_key, get_phi_encryption_key


# ── Fixtures ─────────────────────────────────────────────────────────────────

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


# ── Non-deterministic encryption ─────────────────────────────────────────────

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
        from app.db.encryption import EncryptedString
        from unittest.mock import MagicMock
        td = EncryptedString()
        dialect = MagicMock()
        assert td.process_bind_param(None, dialect) is None
        assert td.process_result_value(None, dialect) is None

    def test_bind_param_encrypts(self) -> None:
        from app.db.encryption import EncryptedString
        from unittest.mock import MagicMock
        td = EncryptedString()
        dialect = MagicMock()
        result = td.process_bind_param("John", dialect)
        assert result is not None
        assert result != "John"
        assert isinstance(result, str)

    def test_result_value_decrypts(self) -> None:
        from app.db.encryption import EncryptedString
        from unittest.mock import MagicMock
        td = EncryptedString()
        dialect = MagicMock()
        ciphertext = td.process_bind_param("John", dialect)
        plaintext = td.process_result_value(ciphertext, dialect)
        assert plaintext == "John"


# ── Deterministic encryption ─────────────────────────────────────────────────

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
        from app.db.encryption import DeterministicEncryptedString
        from unittest.mock import MagicMock
        td = DeterministicEncryptedString()
        dialect = MagicMock()
        c1 = td.process_bind_param("MRN12345", dialect)
        c2 = td.process_bind_param("MRN12345", dialect)
        assert c1 == c2  # deterministic
        assert c1 != "MRN12345"  # encrypted

    def test_deterministic_null_passthrough(self) -> None:
        from app.db.encryption import DeterministicEncryptedString
        from unittest.mock import MagicMock
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
```

### 2. Create `backend/tests/integration/test_phi_encryption_orm.py`

Integration tests against a real PostgreSQL 15 container. Reuse the `pg_container`, `database_url`, and `apply_migrations` fixtures from `conftest.py` (created in US-006/TASK-008).

```python
"""Integration tests for PHI AES-256-GCM encryption at the ORM layer.

Validates US-007 acceptance criteria against a real PostgreSQL 15 database:
  AC1: PHI columns store ciphertext (not plaintext) in raw SQL
  AC2: ORM model access returns decrypted plaintext transparently
  AC3: Duplicate MRN raises UniqueConstraintViolation (deterministic encryption)
  AC4: Key rotation re-encrypts existing records; ORM decryption still works
"""
from __future__ import annotations

import asyncio
import base64
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.encryption_key import clear_cached_key
from app.db.encryption import _decrypt, _encrypt_deterministic
from app.models.patient import Patient


@pytest.fixture(autouse=True)
def phi_test_key(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Inject a deterministic test key for integration tests."""
    clear_cached_key()
    test_key = os.urandom(32)
    key_b64 = base64.urlsafe_b64encode(test_key).decode()
    monkeypatch.setenv("PHI_ENCRYPTION_KEY", key_b64)
    monkeypatch.delenv("PHI_ENCRYPTION_KEY_SECRET_ID", raising=False)
    yield test_key
    clear_cached_key()


# ── AC1: Ciphertext stored in DB ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_phi_stored_as_ciphertext(
    db_session: AsyncSession,
) -> None:
    """AC1: Direct SQL on `patient` returns ciphertext, not plaintext PHI."""
    patient = Patient(
        first_name="John",
        last_name="Doe",
        date_of_birth="1980-01-15",
        mrn_encrypted="MRN-AC1-001",
    )
    db_session.add(patient)
    await db_session.flush()

    result = await db_session.execute(
        text("SELECT first_name, last_name, date_of_birth, mrn_encrypted "
             "FROM patient WHERE id = :id"),
        {"id": str(patient.id)},
    )
    row = result.fetchone()

    assert row.first_name != "John", "first_name must be ciphertext in DB"
    assert row.last_name != "Doe", "last_name must be ciphertext in DB"
    assert row.date_of_birth != "1980-01-15", "date_of_birth must be ciphertext in DB"
    assert row.mrn_encrypted != "MRN-AC1-001", "mrn_encrypted must be ciphertext in DB"

    # Ciphertext must be valid base64url (smoke check format)
    decoded = base64.urlsafe_b64decode(row.first_name + "==")
    assert len(decoded) > 12 + 16, "Ciphertext too short to contain nonce + tag"


# ── AC2: Transparent ORM decryption ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_orm_decrypts_transparently(
    db_session: AsyncSession,
) -> None:
    """AC2: ORM access to PHI columns returns plaintext without explicit decrypt."""
    patient = Patient(
        first_name="Jane",
        last_name="Smith",
        date_of_birth="1992-06-30",
        phone="+1-555-123-4567",
        email="jane.smith@example.com",
        mrn_encrypted="MRN-AC2-001",
    )
    db_session.add(patient)
    await db_session.commit()

    # Reload from DB to exercise process_result_value
    await db_session.refresh(patient)

    assert patient.first_name == "Jane"
    assert patient.last_name == "Smith"
    assert patient.date_of_birth == "1992-06-30"
    assert patient.phone == "+1-555-123-4567"
    assert patient.email == "jane.smith@example.com"
    assert patient.mrn_encrypted == "MRN-AC2-001"


# ── AC3: MRN unique constraint ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mrn_unique_constraint_violation(
    db_session: AsyncSession,
) -> None:
    """AC3: Inserting two patients with the same MRN raises IntegrityError."""
    p1 = Patient(
        first_name="Alice",
        last_name="Brown",
        date_of_birth="1975-03-20",
        mrn_encrypted="MRN-DUPE-001",
    )
    db_session.add(p1)
    await db_session.flush()

    p2 = Patient(
        first_name="Bob",
        last_name="Jones",
        date_of_birth="1980-07-10",
        mrn_encrypted="MRN-DUPE-001",  # Same MRN
    )
    db_session.add(p2)

    with pytest.raises(IntegrityError, match="unique"):
        await db_session.flush()


# ── AC4: Key rotation / re-encryption ────────────────────────────────────────

@pytest.mark.asyncio
async def test_key_rotation_reencryption(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4: After re-encrypting with a new key, ORM decryption still works.

    This test simulates the re-encryption script (TASK-007) inline:
    1. Insert a patient with key_v1
    2. Switch to key_v2
    3. Re-encrypt the row using key_v2
    4. Verify ORM access returns plaintext with key_v2
    """
    # ── Step 1: insert with key_v1 ──────────────────────────────────────────
    key_v1 = os.urandom(32)
    monkeypatch.setenv("PHI_ENCRYPTION_KEY", base64.urlsafe_b64encode(key_v1).decode())
    clear_cached_key()

    patient = Patient(
        first_name="Rotation",
        last_name="Test",
        date_of_birth="1990-12-01",
        mrn_encrypted="MRN-ROTATE-001",
    )
    db_session.add(patient)
    await db_session.commit()
    patient_id = patient.id

    # ── Step 2: switch to key_v2 ────────────────────────────────────────────
    key_v2 = os.urandom(32)
    monkeypatch.setenv("PHI_ENCRYPTION_KEY", base64.urlsafe_b64encode(key_v2).decode())
    clear_cached_key()

    # ── Step 3: simulate re-encryption ─────────────────────────────────────
    # In production, the TASK-007 script does this for all rows.
    # Here we simulate it inline for one row.
    from app.db.encryption import _encrypt, _encrypt_deterministic

    # Read raw ciphertext with v1 key still queryable via raw SQL
    result = await db_session.execute(
        text("SELECT first_name, last_name, date_of_birth, mrn_encrypted "
             "FROM patient WHERE id = :id"),
        {"id": str(patient_id)},
    )
    raw = result.fetchone()

    # Decrypt with v1, re-encrypt with v2
    from app.db.encryption_key import clear_cached_key as clk
    import app.db.encryption_key as ek

    # Temporarily decrypt with old key
    clk()
    monkeypatch.setenv("PHI_ENCRYPTION_KEY", base64.urlsafe_b64encode(key_v1).decode())
    fn_plain = _decrypt(raw.first_name)
    ln_plain = _decrypt(raw.last_name)
    dob_plain = _decrypt(raw.date_of_birth)
    mrn_plain = _decrypt(raw.mrn_encrypted)

    # Re-encrypt with new key
    clk()
    monkeypatch.setenv("PHI_ENCRYPTION_KEY", base64.urlsafe_b64encode(key_v2).decode())
    await db_session.execute(
        text("UPDATE patient SET "
             "first_name = :fn, last_name = :ln, date_of_birth = :dob, mrn_encrypted = :mrn "
             "WHERE id = :id"),
        {
            "fn": _encrypt(fn_plain),
            "ln": _encrypt(ln_plain),
            "dob": _encrypt(dob_plain),
            "mrn": _encrypt_deterministic(mrn_plain),
            "id": str(patient_id),
        },
    )
    await db_session.commit()

    # ── Step 4: ORM access with key_v2 returns plaintext ───────────────────
    clk()
    result2 = await db_session.execute(
        text("SELECT * FROM patient WHERE id = :id"), {"id": str(patient_id)}
    )
    # Use ORM load path
    await db_session.refresh(patient)
    assert patient.first_name == "Rotation"
    assert patient.last_name == "Test"
    assert patient.mrn_encrypted == "MRN-ROTATE-001"
    print("Key rotation + re-encryption test passed")
```

### 3. Ensure Tests Run in `backend/pyproject.toml` or `pytest.ini`

Add the test directories to pytest collection:

```ini
# pytest.ini (or [tool.pytest.ini_options] in pyproject.toml)
testpaths = ["tests"]
asyncio_mode = "auto"
```

---

## Validation

```bash
cd backend

# Unit tests (no Docker required)
pytest tests/unit/test_encryption.py -v

# Integration tests (requires Docker for testcontainers)
pytest tests/integration/test_phi_encryption_orm.py -v

# Coverage check (≥80% required per TR-020)
pytest tests/ --cov=app/db/encryption --cov=app/db/encryption_key \
  --cov-report=term-missing --cov-fail-under=80
```

Expected output: all tests pass, coverage ≥ 80%.

---

## Files Touched

| File | Action |
|---|---|
| `backend/tests/unit/test_encryption.py` | Create — pure unit tests for encryption primitives |
| `backend/tests/integration/test_phi_encryption_orm.py` | Create — ORM integration tests against PostgreSQL |
| `backend/pytest.ini` or `backend/pyproject.toml` | Confirm `asyncio_mode = "auto"` is set |

---

## Definition of Done Checklist

- [ ] `test_phi_stored_as_ciphertext` passes: raw SQL returns ciphertext, not plaintext
- [ ] `test_orm_decrypts_transparently` passes: ORM access returns plaintext without explicit decrypt
- [ ] `test_mrn_unique_constraint_violation` passes: duplicate MRN raises `IntegrityError`
- [ ] `test_key_rotation_reencryption` passes: re-encrypted row decrypts correctly with new key
- [ ] Non-deterministic test: two encryptions of same value produce different ciphertexts
- [ ] Tamper detection test: modified ciphertext raises `InvalidTag`
- [ ] Unit test coverage for `app/db/encryption.py` and `app/db/encryption_key.py` ≥ 80%
- [ ] All tests pass in CI (Cloud Build) without manual intervention
