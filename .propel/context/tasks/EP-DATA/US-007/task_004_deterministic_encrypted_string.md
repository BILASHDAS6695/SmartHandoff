---
id: TASK-004
title: "Implement `DeterministicEncryptedString` SQLAlchemy TypeDecorator (MRN / HMAC-Derived Nonce)"
user_story: US-007
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-002, TASK-003]
---

# TASK-004: Implement `DeterministicEncryptedString` SQLAlchemy TypeDecorator (MRN / HMAC-Derived Nonce)

> **Story:** US-007 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

`mrn` (Medical Record Number) is the patient's unique identifier and is used as a deduplication key (DR-020). Storing it with non-deterministic encryption means two `"MRN12345"` values produce different ciphertexts, making a PostgreSQL `UNIQUE` constraint on the encrypted column impossible.

**Deterministic encryption** solves this by deriving the nonce from the plaintext itself:

```
nonce = HMAC-SHA256(encryption_key, plaintext_utf8)[:12]
```

Because `HMAC-SHA256(k, "MRN12345")` always returns the same 32-byte value, the first 12 bytes (nonce) are also always the same, so `AESGCM.encrypt(nonce, "MRN12345", …)` always returns the same ciphertext. This enables the `UNIQUE` index.

### Security trade-off

Deterministic encryption leaks whether two patients share the same MRN (equality-visible). It does **not** leak the plaintext value. This is an acceptable trade-off for the MRN field specifically, per ADR-007.

**Never use `DeterministicEncryptedString` for fields that require semantic privacy beyond equality (e.g., `first_name`, `last_name`, `dob`)** — use `EncryptedString` for those.

---

## Acceptance Criteria Addressed

| US-007 AC | Requirement |
|---|---|
| **Scenario 3** | Duplicate MRN raises `UniqueConstraintViolation` — only possible because deterministic encryption ensures same plaintext → same ciphertext |
| **DoD** | `DeterministicEncryptedString` uses `HMAC-SHA256`-derived nonce |

---

## Implementation Steps

### 1. Implement `DeterministicEncryptedString` in `backend/app/db/encryption.py`

Add the following class **after** the `EncryptedString` class. Reuse `_decrypt`, `_NONCE_BYTES`, `_TAG_BYTES`, and `AESGCM` already defined in TASK-003. Do not duplicate those definitions.

```python
import hashlib
import hmac


class DeterministicEncryptedString(TypeDecorator[str]):
    """Deterministic AES-256-GCM encrypted VARCHAR column for MRN deduplication.

    Same plaintext always produces the same ciphertext because the 96-bit
    nonce is derived from HMAC-SHA256(key, plaintext)[:12].

    This enables a PostgreSQL UNIQUE constraint on the encrypted column,
    satisfying DR-020 (MRN deduplication without exposing plaintext MRNs).

    ⚠ Security note: Use ONLY for `patient.mrn_encrypted`. For all other
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
```

### 2. Add `_encrypt_deterministic` to `__all__`

Update the `__all__` list in `encryption.py` to include the new helper (needed by TASK-007 re-encryption script):

```python
__all__ = [
    "EncryptedString",
    "DeterministicEncryptedString",
    "get_phi_encryption_key",
    "_encrypt",
    "_encrypt_deterministic",
    "_decrypt",
    "_NONCE_BYTES",
    "_TAG_BYTES",
]
```

### 3. Remove the TASK-001 Placeholder

The `DeterministicEncryptedString` placeholder class created in TASK-001 must be fully removed. The implementation above replaces it.

---

## Cryptographic Design Notes

| Property | Value | Rationale |
|---|---|---|
| Nonce derivation | `HMAC-SHA256(key, plaintext)[:12]` | Deterministic; collision-resistant (HMAC is a PRF); identical to nonce size used by AESGCM |
| Why HMAC with key? | Prevents rainbow-table attacks on nonce derivation | An attacker who knows the plaintext cannot precompute the nonce without the key |
| Why not a static nonce? | Static nonce (e.g. `bytes(12)`) is vulnerable to block-level analysis | HMAC-derived nonce varies per plaintext value |
| Decryption path | Identical to `EncryptedString._decrypt` | Wire format is the same; nonce always occupies first 12 bytes |
| Uniqueness guarantee | `UNIQUE` constraint on `patient.mrn_encrypted` at DB level (Alembic migration) | ORM-level uniqueness alone is insufficient |

---

## Validation

```bash
cd backend
PHI_ENCRYPTION_KEY=$(python -c \
  "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())") \
python -c "
from app.db.encryption_key import clear_cached_key
clear_cached_key()

from app.db.encryption import _encrypt_deterministic, _decrypt

# Same plaintext must produce identical ciphertexts (deterministic)
c1 = _encrypt_deterministic(b'MRN12345')
c2 = _encrypt_deterministic(b'MRN12345')
assert c1 == c2, 'Deterministic encryption produced different ciphertexts!'

# Different plaintexts must produce different ciphertexts
c3 = _encrypt_deterministic(b'MRN99999')
assert c1 != c3, 'Different MRNs produced same ciphertext!'

# Decryption must return original plaintext
assert _decrypt(c1) == b'MRN12345'
assert _decrypt(c3) == b'MRN99999'

# Non-deterministic EncryptedString must still be non-deterministic
from app.db.encryption import _encrypt
nd1 = _encrypt(b'MRN12345')
nd2 = _encrypt(b'MRN12345')
assert nd1 != nd2, 'EncryptedString should be non-deterministic!'

print('DeterministicEncryptedString validated')
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/db/encryption.py` | Replace `DeterministicEncryptedString` placeholder; add `_encrypt_deterministic`; update `__all__` |

---

## Definition of Done Checklist

- [ ] `DeterministicEncryptedString(TypeDecorator)` implemented with `process_bind_param` and `process_result_value`
- [ ] Nonce derived from `HMAC-SHA256(key, plaintext)[:12]` — not `os.urandom()`
- [ ] Same plaintext always produces identical ciphertext (deterministic property verified in tests)
- [ ] Decryption reuses the same `_decrypt` helper as `EncryptedString` (no duplicated logic)
- [ ] `DeterministicEncryptedString` intended for MRN only — usage guidance in docstring
- [ ] TASK-001 placeholder class removed
- [ ] `_encrypt_deterministic` added to `__all__`
