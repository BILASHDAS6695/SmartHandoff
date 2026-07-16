---
id: TASK-001
title: "Create `app/core/auth/otp_helpers.py` — Phone Hash & Redis Key Utilities"
user_story: US-065
epic: EP-013
sprint: 2
layer: Backend / Core
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-001/Redis, US-064/Twilio credentials]
---

# TASK-001: Create `app/core/auth/otp_helpers.py` — Phone Hash & Redis Key Utilities

> **Story:** US-065 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Core | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-065 requires that phone numbers are **never stored in plaintext** inside Redis keys. All Redis keys must be derived from a salted SHA-256 hash of the phone number or portal token. This module is the single source of truth for all OTP-related key derivation and bcrypt operations, consumed by TASK-002 (request endpoint) and TASK-003 (verify endpoint).

Key derivation rules from the Technical Notes:

| Purpose | Redis key format |
|---|---|
| OTP hash storage | `otp:{SHA-256(portal_token)}` |
| Rate limit counter | `otp_rate:{SHA-256(phone_number + salt)}` |
| Failed attempt counter | `otp_failures:{otp_key}` where `otp_key = SHA-256(portal_token)` |

The salt for phone hashing is sourced from GCP Secret Manager (`OTP_PHONE_SALT`) via the existing `app/core/secrets.py` pattern (established in US-064).

---

## Acceptance Criteria Addressed

| US-065 DoD Item | Requirement |
|---|---|
| **OTP hash** | `bcrypt(otp, rounds=10)` stored in Redis — NOT plaintext |
| **Rate limit key** | Redis key `otp_rate:{phone_hash}` — hash phone number, don't store plaintext |
| **OTP key** | `otp:{SHA-256(portal_token)}` — links OTP to portal token, not phone |

---

## Implementation Steps

### 1. Create `backend/app/core/auth/otp_helpers.py`

```python
"""
OTP cryptographic helpers for US-065.

All Redis key derivation and bcrypt operations are centralised here to
ensure phone numbers and portal tokens are NEVER stored as plaintext
Redis keys (SEC-003, AIR-043).
"""

import hashlib
import hmac

import bcrypt

from app.core.config import settings  # exposes OTP_PHONE_SALT from Secret Manager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BCRYPT_ROUNDS: int = 10
OTP_TTL_SECONDS: int = 600          # 10 minutes (AIR-043)
RATE_LIMIT_TTL_SECONDS: int = 3600  # 1 hour window (AC Scenario 2)
RATE_LIMIT_MAX: int = 5             # max OTP requests per phone per hour
MAX_FAILED_ATTEMPTS: int = 3        # OTP invalidated after 3 failures (AC Scenario 3)


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def _sha256_hex(value: str, salt: str = "") -> str:
    """Return the lowercase hex SHA-256 digest of ``value + salt``.

    Uses ``hmac.compare_digest``-safe constant-time construction is not
    required here because the output is used only as a Redis key suffix,
    not as a secret comparison target.
    """
    raw = (value + salt).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def otp_redis_key(portal_token: str) -> str:
    """Redis key for the bcrypt OTP hash.  Never contains plaintext token.

    Pattern: ``otp:{SHA-256(portal_token)}``
    """
    return f"otp:{_sha256_hex(portal_token)}"


def rate_limit_redis_key(phone_number: str) -> str:
    """Redis key for the per-phone OTP rate limit counter.

    Pattern: ``otp_rate:{SHA-256(phone_number + OTP_PHONE_SALT)}``
    The salt prevents phone enumeration from a Redis key dump.
    """
    return f"otp_rate:{_sha256_hex(phone_number, settings.OTP_PHONE_SALT)}"


def failures_redis_key(portal_token: str) -> str:
    """Redis key for the failed-attempt counter tied to an OTP session.

    Pattern: ``otp_failures:{SHA-256(portal_token)}``
    Reuses the same digest as ``otp_redis_key`` for key locality.
    """
    return f"otp_failures:{_sha256_hex(portal_token)}"


# ---------------------------------------------------------------------------
# bcrypt operations
# ---------------------------------------------------------------------------

def hash_otp(otp_code: str) -> str:
    """Return a bcrypt hash of ``otp_code`` (rounds=10).

    The returned string is safe to store in Redis; it is NOT the OTP itself.
    """
    return bcrypt.hashpw(
        otp_code.encode("utf-8"),
        bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
    ).decode("utf-8")


def verify_otp(otp_code: str, otp_hash: str) -> bool:
    """Return True if ``otp_code`` matches the stored ``otp_hash``.

    Uses ``bcrypt.checkpw`` which is constant-time against the stored hash.
    """
    return bcrypt.checkpw(
        otp_code.encode("utf-8"),
        otp_hash.encode("utf-8"),
    )
```

### 2. Expose `OTP_PHONE_SALT` in `app/core/config.py`

Add the setting so that `settings.OTP_PHONE_SALT` is populated from the environment / Secret Manager:

```python
# In app/core/config.py — Settings class
OTP_PHONE_SALT: str  # Required; sourced from Secret Manager via env injection
```

The value is provisioned in GCP Secret Manager under the name `smarthandoff-otp-phone-salt` (same naming convention as other US-064 secrets).

### 3. Ensure `bcrypt` is in `requirements.txt`

```
bcrypt>=4.0.0
```

---

## Validation

```bash
# Smoke test — run from backend/
python -c "
from app.core.auth.otp_helpers import (
    otp_redis_key, rate_limit_redis_key, failures_redis_key,
    hash_otp, verify_otp,
)
import os; os.environ['OTP_PHONE_SALT'] = 'test-salt'

token = 'portal-token-abc123'
phone = '+12345678901'

k1 = otp_redis_key(token)
k2 = rate_limit_redis_key(phone)
k3 = failures_redis_key(token)

assert k1.startswith('otp:'), f'Bad key: {k1}'
assert k2.startswith('otp_rate:'), f'Bad key: {k2}'
assert k3.startswith('otp_failures:'), f'Bad key: {k3}'
# Key must not contain plaintext token or phone
assert token not in k1 and phone not in k2

h = hash_otp('123456')
assert verify_otp('123456', h)
assert not verify_otp('999999', h)
print('All assertions passed.')
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/core/auth/otp_helpers.py` | Create |
| `backend/app/core/config.py` | Add `OTP_PHONE_SALT` field |
| `backend/requirements.txt` | Add `bcrypt>=4.0.0` |

---

## Definition of Done Checklist

- [ ] `otp_helpers.py` created with all three key-derivation functions and both bcrypt functions
- [ ] Phone number salt loaded from `settings.OTP_PHONE_SALT` (Secret Manager — not hardcoded)
- [ ] `bcrypt>=4.0.0` in `requirements.txt`
- [ ] Smoke test passes without assertion errors
- [ ] No plaintext phone or token values appear in any Redis key
