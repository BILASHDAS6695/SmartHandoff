---
id: TASK-003
title: "Implement `EncryptedString` SQLAlchemy TypeDecorator (Non-Deterministic AES-256-GCM)"
user_story: US-007
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Implement `EncryptedString` SQLAlchemy TypeDecorator (Non-Deterministic AES-256-GCM)

> **Story:** US-007 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

`EncryptedString` is the primary SQLAlchemy TypeDecorator used for all PHI fields except `mrn` (which requires deterministic encryption for deduplication). It uses **non-deterministic** AES-256-GCM: a fresh 96-bit nonce is generated from `os.urandom(12)` for every encryption operation, meaning two encryptions of `"John"` will produce two different ciphertexts. This is the correct default for HIPAA-compliant field encryption — determinism only where a unique index demands it.

### Wire format

```
base64url( nonce[12 bytes] || aesgcm_output[plaintext_len + 16 bytes] )
```

`AESGCM.encrypt(nonce, plaintext, aad=None)` returns `ciphertext + 16-byte GCM tag` as a single byte string. The nonce is prepended and the entire payload is base64url-encoded before storage. On decrypt, the nonce is extracted by slicing the first 12 bytes of the decoded payload.

### Column sizing

For a VARCHAR column with `length=L`:
- Base64url overhead: `ceil((12 + plaintext_len + 16) / 3) * 4` characters
- A 64-character plaintext field (`first_name`, `last_name`) requires `ceil((12 + 64 + 16) / 3) * 4 = 124` chars
- Use `length=256` for all PHI `VARCHAR` columns to provide ample headroom (DR-002)

---

## Acceptance Criteria Addressed

| US-007 AC | Requirement |
|---|---|
| **Scenario 1** | PHI stored as ciphertext — `EncryptedString.process_bind_param` encrypts on every INSERT/UPDATE |
| **Scenario 2** | PHI decrypts transparently — `EncryptedString.process_result_value` decrypts on every SELECT |

---

## Implementation Steps

### 1. Implement `EncryptedString` in `backend/app/db/encryption.py`

Replace the placeholder class from TASK-001 with the full implementation. The `DeterministicEncryptedString` placeholder (from TASK-001) must remain until TASK-004 replaces it.

```python
"""PHI field-level encryption for SQLAlchemy ORM columns.

[Module docstring from TASK-001 remains unchanged — do not replace it.]
"""
from __future__ import annotations

import base64
import os
from typing import Any

from sqlalchemy import String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.db.encryption_key import get_phi_encryption_key


# ── AESGCM import with clear error if cryptography is missing ─────────────────
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
except ImportError as exc:
    raise ImportError(
        "The 'cryptography' package is required for PHI field encryption. "
        "Add 'cryptography>=42.0.0' to requirements.txt."
    ) from exc

_NONCE_BYTES: int = 12   # GCM standard: 96-bit nonce
_TAG_BYTES: int = 16     # GCM authentication tag appended by AESGCM.encrypt()


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
    cache_ok = True  # TypeDecorator is stateless; key loaded via closure

    def __init__(self, length: int = 256, *args: Any, **kwargs: Any) -> None:
        super().__init__(length, *args, **kwargs)

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Encrypt plaintext → ciphertext before writing to the database.

        Called by SQLAlchemy for INSERT and UPDATE operations.
        Returns None unchanged (NULL column semantics preserved).
        """
        if value is None:
            return None
        return _encrypt(value.encode("utf-8"))

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        """Decrypt ciphertext → plaintext after reading from the database.

        Called by SQLAlchemy for SELECT operations.
        Returns None unchanged (NULL column semantics preserved).
        """
        if value is None:
            return None
        return _decrypt(value).decode("utf-8")


def _encrypt(plaintext: bytes) -> str:
    """Encrypt plaintext bytes with AES-256-GCM using a random nonce.

    Returns base64url-encoded: nonce || aesgcm_output
    """
    key = get_phi_encryption_key()
    nonce = os.urandom(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    encrypted = aesgcm.encrypt(nonce, plaintext, associated_data=None)
    # aesgcm.encrypt returns: ciphertext + 16-byte tag (concatenated)
    payload = nonce + encrypted
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decrypt(ciphertext_b64: str) -> bytes:
    """Decrypt a base64url-encoded payload produced by `_encrypt`.

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
```

### 2. Expose `_encrypt` and `_decrypt` as Internal Helpers

Both `_encrypt` and `_decrypt` are module-private (`_` prefix) but must be importable by TASK-004 (`DeterministicEncryptedString` reuses `_decrypt` and the AESGCM constants). They are also referenced by the re-encryption script in TASK-007.

No changes needed — defining them in `encryption.py` at module scope is sufficient.

### 3. Update `__all__` in `encryption.py`

Ensure `__all__` includes the internal helpers for TASK-004 and TASK-007 access:

```python
__all__ = [
    "EncryptedString",
    "DeterministicEncryptedString",  # Placeholder until TASK-004
    "get_phi_encryption_key",
    "_encrypt",   # Used by re-encryption script (TASK-007)
    "_decrypt",   # Used by re-encryption script (TASK-007)
    "_NONCE_BYTES",
    "_TAG_BYTES",
]
```

---

## Cryptographic Design Notes

| Property | Value | Rationale |
|---|---|---|
| Algorithm | AES-256-GCM | Mandated by BR-020 / 45 CFR §164.312 |
| Key size | 256 bits (32 bytes) | Required for AES-256 |
| Nonce size | 96 bits (12 bytes) | GCM standard recommendation; avoids counter wrap with 32-byte random key |
| Nonce generation | `os.urandom(12)` | Cryptographically secure random bytes |
| Authentication | 16-byte GCM tag (automatic) | Detects tampering; `InvalidTag` raised on mismatch |
| Plaintext encoding | UTF-8 before encryption | All PHI fields are text strings |
| Storage encoding | base64url | URL-safe; PostgreSQL VARCHAR compatible |
| NULL handling | `None → None` | Preserves optional column semantics |

---

## Validation

```bash
cd backend
PHI_ENCRYPTION_KEY=$(python -c \
  "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())") \
python -c "
from app.db.encryption_key import clear_cached_key
clear_cached_key()

from app.db.encryption import _encrypt, _decrypt

# Encrypt the same value twice — must produce different ciphertexts (non-deterministic)
c1 = _encrypt(b'John')
c2 = _encrypt(b'John')
assert c1 != c2, 'Same plaintext produced same ciphertext — nonce reuse!'

# Decrypt both — must return original plaintext
assert _decrypt(c1) == b'John'
assert _decrypt(c2) == b'John'

# Test authentication tag verification
import base64
raw = base64.urlsafe_b64decode(c1 + '==')
tampered = base64.urlsafe_b64encode(raw[:-1] + bytes([raw[-1] ^ 0xFF])).decode()
try:
    _decrypt(tampered)
    assert False, 'Should have raised InvalidTag'
except Exception as e:
    print(f'Tamper detection OK: {type(e).__name__}')

print('EncryptedString logic validated')
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/db/encryption.py` | Replace `EncryptedString` placeholder with full TypeDecorator implementation; add `_encrypt`, `_decrypt` helpers |

---

## Definition of Done Checklist

- [ ] `EncryptedString(TypeDecorator)` implemented with `process_bind_param` and `process_result_value`
- [ ] Fresh `os.urandom(12)` nonce per encryption call (verified in test: two encryptions of same value produce different ciphertexts)
- [ ] Decryption raises `cryptography.exceptions.InvalidTag` on tampered ciphertext
- [ ] `NULL` (None) values pass through unchanged
- [ ] `_encrypt` / `_decrypt` module-private helpers defined for reuse by TASK-004 and TASK-007
- [ ] `cache_ok = True` set on TypeDecorator
- [ ] No key bytes or plaintext in any log statement
