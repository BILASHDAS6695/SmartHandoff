---
id: TASK-001
title: "Add `cryptography` Dependency and Create `encryption.py` Module Skeleton"
user_story: US-007
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-006/TASK-001]
---

# TASK-001: Add `cryptography` Dependency and Create `encryption.py` Module Skeleton

> **Story:** US-007 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 1 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-007 requires AES-256-GCM field-level encryption using the `cryptography` library (not `Fernet` — per Technical Notes, AES-256-GCM is the mandated algorithm under BR-020 and 45 CFR §164.312). Before any TypeDecorator or key management code can be written, the library must be pinned in `requirements.txt` and a skeleton module created so all subsequent tasks (TASK-002 through TASK-004) have a stable home.

The US-006 tasks (TASK-003, TASK-005) already reference a stub `app/db/encryption.py` with `# TODO(US-007)` placeholders on the TypeDecorator imports. This task replaces that stub with a real module scaffold that TASK-002–004 will flesh out.

---

## Acceptance Criteria Addressed

| US-007 AC | Requirement |
|---|---|
| **DoD** | `cryptography` library pinned; `EncryptedString` and `DeterministicEncryptedString` TypeDecorators present in `app/db/encryption.py` — this task creates the file skeleton |

---

## Implementation Steps

### 1. Pin `cryptography` in `backend/requirements.txt`

Add the following entry to `backend/requirements.txt`. Use a minimum version pin to guarantee GCM support and avoid known CVEs:

```
cryptography>=42.0.0
```

> **Security note:** `cryptography>=42` eliminates CVEs present in earlier 41.x builds (OpenSSL binding). Do not use an unpinned version — Artifact Registry scanning (TR-019) will flag it.

### 2. Remove the `# TODO(US-007)` Stub from `app/db/encryption.py`

The US-006 tasks may have created a stub at `backend/app/db/encryption.py` with placeholder content. If it exists, replace its entire contents with the skeleton below. If the file does not yet exist, create it.

```python
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

Wire format (both variants):
    base64url( nonce(12 bytes) || aesgcm_output(plaintext_len + 16 bytes) )

    AESGCM.encrypt() appends the 16-byte authentication tag automatically.
    On decrypt, AESGCM.decrypt() verifies the tag and raises InvalidTag if
    the ciphertext has been tampered with.

Usage:
    from app.db.encryption import EncryptedString, DeterministicEncryptedString

    class Patient(Base):
        first_name: Mapped[str] = mapped_column(EncryptedString(256))
        mrn_encrypted: Mapped[str] = mapped_column(
            DeterministicEncryptedString(256), unique=True
        )
"""
from __future__ import annotations

# ── Key management ────────────────────────────────────────────────────────────
# See: app/db/encryption_key.py (implemented in TASK-002)
from app.db.encryption_key import get_phi_encryption_key  # noqa: F401 (re-export)

# ── TypeDecorators ────────────────────────────────────────────────────────────
# See: TASK-003 (EncryptedString) and TASK-004 (DeterministicEncryptedString)
# Placeholders below are replaced in those tasks.

__all__ = [
    "EncryptedString",
    "DeterministicEncryptedString",
    "get_phi_encryption_key",
]


class EncryptedString:  # type: ignore[no-redef]
    """Placeholder — implemented in TASK-003."""
    _task = "TASK-003"


class DeterministicEncryptedString:  # type: ignore[no-redef]
    """Placeholder — implemented in TASK-004."""
    _task = "TASK-004"
```

### 3. Create `backend/app/db/encryption_key.py` Skeleton

Key loading logic lives in a separate module so it can be tested and mocked independently:

```python
"""PHI encryption key loading from GCP Secret Manager.

Implemented in US-007 TASK-002. This skeleton exists so that
encryption.py can import `get_phi_encryption_key` before TASK-002 is complete.
"""
from __future__ import annotations


def get_phi_encryption_key() -> bytes:  # pragma: no cover
    """Return the 32-byte AES-256 key. Implemented in TASK-002."""
    raise NotImplementedError("Implemented in TASK-002")
```

### 4. Verify No Hardcoded Key Material

Run a grep to confirm no test key, hex literal, or base64 secret has been committed:

```bash
grep -rn "ENCRYPTION_KEY\|AES_KEY\|phi_key\|secret_key" backend/app/db/ \
  | grep -v "get_phi_encryption_key\|#"
```

Expected output: **no matches**.

---

## Validation

```bash
cd backend
pip install -r requirements.txt
python -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; print('AESGCM OK')"
python -c "from app.db.encryption import EncryptedString, DeterministicEncryptedString; print('Import OK')"
```

Both commands must exit with code 0.

---

## Files Touched

| File | Action |
|---|---|
| `backend/requirements.txt` | Add `cryptography>=42.0.0` |
| `backend/app/db/encryption.py` | Create (or overwrite stub) with module skeleton |
| `backend/app/db/encryption_key.py` | Create with stub `get_phi_encryption_key()` |

---

## Definition of Done Checklist

- [ ] `cryptography>=42.0.0` present in `backend/requirements.txt`
- [ ] `backend/app/db/encryption.py` exists with correct module docstring and `__all__`
- [ ] `backend/app/db/encryption_key.py` exists with `get_phi_encryption_key()` stub
- [ ] No hardcoded key material in any committed file
- [ ] `pip install -r requirements.txt` succeeds in CI
