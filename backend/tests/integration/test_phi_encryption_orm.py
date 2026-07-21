"""Integration tests for PHI AES-256-GCM encryption at the ORM layer.

Validates US-007 acceptance criteria against a real PostgreSQL 15 database:
  AC1: PHI columns store ciphertext (not plaintext) in raw SQL
  AC2: ORM model access returns decrypted plaintext transparently
  AC3: Duplicate MRN raises IntegrityError (deterministic encryption)
  AC4: Key rotation re-encrypts existing records; ORM decryption still works
"""
from __future__ import annotations

import base64
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.encryption import _decrypt, _encrypt, _encrypt_deterministic
from app.db.encryption_key import clear_cached_key
from app.models.patient import Patient


@pytest.fixture(autouse=True)
def phi_test_key(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Inject a fresh random 32-byte test key for each integration test."""
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
        text(
            "SELECT first_name, last_name, date_of_birth, mrn_encrypted "
            "FROM patient WHERE id = :id"
        ),
        {"id": str(patient.id)},
    )
    row = result.fetchone()

    assert row.first_name != "John", "first_name must be ciphertext in DB"
    assert row.last_name != "Doe", "last_name must be ciphertext in DB"
    assert row.date_of_birth != "1980-01-15", "date_of_birth must be ciphertext in DB"
    assert row.mrn_encrypted != "MRN-AC1-001", "mrn_encrypted must be ciphertext in DB"

    # Ciphertext must be valid base64url with nonce+tag overhead
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

    # Reload from DB to exercise process_result_value path
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
        mrn_encrypted="MRN-DUPE-001",  # Same MRN — must fail
    )
    db_session.add(p2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── AC4: Key rotation / re-encryption ────────────────────────────────────────

@pytest.mark.asyncio
async def test_key_rotation_reencryption(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4: After re-encrypting with a new key, ORM decryption still works.

    Simulates the TASK-007 re-encryption script inline for a single row:
    1. Insert a patient encrypted with key_v1
    2. Switch to key_v2
    3. Decrypt each PHI column with key_v1, re-encrypt with key_v2
    4. Verify ORM refresh returns correct plaintext with key_v2
    """
    # ── Step 1: insert with key_v1 ───────────────────────────────────────────
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

    # ── Step 2: read raw ciphertext encrypted with v1 ────────────────────────
    result = await db_session.execute(
        text(
            "SELECT first_name, last_name, date_of_birth, mrn_encrypted "
            "FROM patient WHERE id = :id"
        ),
        {"id": str(patient_id)},
    )
    raw = result.fetchone()

    # ── Step 3: decrypt with v1, re-encrypt with v2 ──────────────────────────
    # Decrypt using old key (v1 is still cached after commit)
    fn_plain = _decrypt(raw.first_name)
    ln_plain = _decrypt(raw.last_name)
    dob_plain = _decrypt(raw.date_of_birth)
    mrn_plain = _decrypt(raw.mrn_encrypted)

    # Switch to key_v2
    key_v2 = os.urandom(32)
    monkeypatch.setenv("PHI_ENCRYPTION_KEY", base64.urlsafe_b64encode(key_v2).decode())
    clear_cached_key()

    # Re-encrypt with v2
    await db_session.execute(
        text(
            "UPDATE patient SET "
            "first_name = :fn, last_name = :ln, "
            "date_of_birth = :dob, mrn_encrypted = :mrn "
            "WHERE id = :id"
        ),
        {
            "fn": _encrypt(fn_plain),
            "ln": _encrypt(ln_plain),
            "dob": _encrypt(dob_plain),
            "mrn": _encrypt_deterministic(mrn_plain),
            "id": str(patient_id),
        },
    )
    await db_session.commit()

    # ── Step 4: ORM refresh with key_v2 returns plaintext ────────────────────
    # Expire the cached ORM state so refresh hits the DB
    db_session.expire(patient)
    await db_session.refresh(patient)

    assert patient.first_name == "Rotation"
    assert patient.last_name == "Test"
    assert patient.date_of_birth == "1990-12-01"
    assert patient.mrn_encrypted == "MRN-ROTATE-001"
