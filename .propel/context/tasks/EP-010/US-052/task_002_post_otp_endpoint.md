---
id: TASK-002
title: "POST /api/v1/auth/patient/otp — Generate OTP, Hash & Store in Redis, Trigger Twilio"
user_story: US-052
epic: EP-010
sprint: 2
layer: Backend / API
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-052/TASK-001, US-001, US-064]
---

# TASK-002: POST /api/v1/auth/patient/otp — Generate OTP, Hash & Store in Redis, Trigger Twilio

> **Story:** US-052 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements `POST /api/v1/auth/patient/otp` — the first step in the OTP
passwordless authentication flow. The patient's SMS link contains a signed `portal_token`
(decoded in TASK-001). When the patient lands on the portal page, the Angular frontend
automatically fires this endpoint to request an OTP.

### Endpoint behaviour

```
POST /api/v1/auth/patient/otp
Body: { "portal_token": "<signed_jwt>" }

1. Decode portal_token → extract patient_id, encounter_id (TASK-001)
2. Check Redis key otp_attempts:{portal_token} — block if value ≥ 5 → 429
3. Generate OTP: secrets.randbelow(1_000_000), zero-padded to 6 digits
4. Hash OTP: bcrypt(otp, rounds=12)
5. Store hash in Redis: SET otp:{portal_token} <hash> EX 600
6. Increment Redis counter: INCR otp_attempts:{portal_token}; EXPIRE … 3600 (only on first increment)
7. Call Notification Service: POST /internal/notify/otp {patient_id, otp}
8. Return HTTP 200 {"message": "OTP sent. Check your SMS."}
```

**Rate limit rule (US-052 AC Scenario 2):**

- Key: `otp_attempts:{portal_token}` (TTL = 3600 s = 1 hour)
- Block at **count ≥ 5 before** OTP generation
- Response on block: `429 Too Many Requests` with `Retry-After: <seconds_until_key_expiry>`
- No OTP generated, no Redis OTP key written, no Twilio call made

**OTP TTL (US-052 AC Scenario 3):**

- Redis key `otp:{portal_token}` TTL = 600 s (10 minutes)
- OTP stored as bcrypt hash, NOT plaintext

**Design references:**

- US-052 Technical Notes — OTP generation, bcrypt storage, rate limiting key names
- design.md §3.1 Notification Service — OTP delivery via Twilio Verify
- design.md §3.3 — middleware stack
- design.md §10.1 — PHI: patient phone number MUST NOT appear in any log

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 2 | Rate limit: 5th attempt allowed; 6th blocked with 429 + `Retry-After` header |
| Scenario 3 | OTP stored with TTL=600 s; verify endpoint (TASK-003) returns 401 after expiry |

---

## Implementation Steps

### 1. Create module structure

```bash
mkdir -p api-gateway/app/routers/auth
touch api-gateway/app/routers/auth/patient_otp.py
touch api-gateway/app/services/otp_service.py
touch api-gateway/app/services/__init__.py
```

### 2. Implement `api-gateway/app/services/otp_service.py`

```python
"""OTP generation, hashing, and Redis management for patient auth (US-052).

Design refs:
    US-052 Technical Notes — bcrypt hash, secrets.randbelow, Redis key names
    US-052 AC Scenario 2 — rate limit: block at otp_attempts >= 5
    US-052 AC Scenario 3 — OTP TTL = 600 s (10 minutes)
"""
from __future__ import annotations

import logging
import secrets

import bcrypt
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

_OTP_TTL_SECONDS = 600          # 10 minutes — AC Scenario 3
_RATE_LIMIT_TTL_SECONDS = 3600  # 1 hour — AC Scenario 2
_RATE_LIMIT_MAX_ATTEMPTS = 5    # block on the 6th attempt


def _otp_key(portal_token: str) -> str:
    return f"otp:{portal_token}"


def _attempts_key(portal_token: str) -> str:
    return f"otp_attempts:{portal_token}"


def generate_otp() -> str:
    """Return a cryptographically random 6-digit OTP, zero-padded.

    Uses secrets.randbelow(1_000_000) per US-052 Technical Notes.
    """
    return str(secrets.randbelow(1_000_000)).zfill(6)


def hash_otp(otp: str) -> bytes:
    """Hash OTP with bcrypt (12 rounds).

    NEVER stored as plaintext in Redis per US-052 Technical Notes.
    """
    return bcrypt.hashpw(otp.encode(), bcrypt.gensalt(rounds=12))


async def get_remaining_attempts(
    redis: aioredis.Redis,
    portal_token: str,
) -> int:
    """Return how many OTP attempts remain (max 5) for this portal token."""
    current = await redis.get(_attempts_key(portal_token))
    used = int(current) if current else 0
    return max(0, _RATE_LIMIT_MAX_ATTEMPTS - used)


async def is_rate_limited(
    redis: aioredis.Redis,
    portal_token: str,
) -> tuple[bool, int]:
    """Check if the portal token has hit the OTP request rate limit.

    Returns:
        (is_blocked, retry_after_seconds)
        retry_after_seconds is 0 when not blocked.
    """
    current = await redis.get(_attempts_key(portal_token))
    count = int(current) if current else 0

    if count >= _RATE_LIMIT_MAX_ATTEMPTS:
        ttl = await redis.ttl(_attempts_key(portal_token))
        retry_after = max(ttl, 0)
        log.warning(
            "otp_rate_limit_hit",
            extra={"attempt_count": count},
            # portal_token deliberately excluded from logs (encodes patient data)
        )
        return True, retry_after

    return False, 0


async def store_otp_hash(
    redis: aioredis.Redis,
    portal_token: str,
    otp_hash: bytes,
) -> None:
    """Store bcrypt-hashed OTP in Redis with 10-minute TTL.

    Key: otp:{portal_token}
    TTL: 600 s (AC Scenario 3)
    """
    await redis.set(
        _otp_key(portal_token),
        otp_hash,
        ex=_OTP_TTL_SECONDS,
    )


async def increment_attempt_counter(
    redis: aioredis.Redis,
    portal_token: str,
) -> None:
    """Increment the OTP attempt counter with 1-hour TTL.

    Uses SET NX to set TTL only on the first increment so the window
    does not reset on each new OTP request.
    """
    key = _attempts_key(portal_token)
    pipe = redis.pipeline()
    pipe.incr(key)
    # EXPIRE with NX flag — only set expiry if key has no TTL yet (first increment)
    pipe.expire(key, _RATE_LIMIT_TTL_SECONDS, nx=True)
    await pipe.execute()
```

### 3. Implement `api-gateway/app/routers/auth/patient_otp.py`

```python
"""POST /api/v1/auth/patient/otp — OTP request endpoint (US-052).

Generates a 6-digit OTP, stores its bcrypt hash in Redis (TTL=600 s),
enforces rate limiting (max 5 per hour per portal token), and triggers
OTP delivery via the Notification Service.

Design refs:
    US-052 AC Scenario 2 — 429 + Retry-After on 6th request within 1 hour
    US-052 AC Scenario 3 — OTP expires after 10 minutes (Redis TTL=600 s)
    US-052 Technical Notes — bcrypt hash; secrets.randbelow; Redis key names
    design.md §3.3 — middleware stack applied before this handler
    design.md §10.1 — patient phone NOT logged (PHI)
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis

from api_gateway.app.core.auth.portal_token import PortalTokenClaims, decode_portal_token
from api_gateway.app.core.config import settings
from api_gateway.app.core.redis import get_redis
from api_gateway.app.services.otp_service import (
    generate_otp,
    hash_otp,
    increment_attempt_counter,
    is_rate_limited,
    store_otp_hash,
)

router = APIRouter(prefix="/api/v1/auth/patient", tags=["Patient Auth"])
log = logging.getLogger(__name__)


class OtpRequest(BaseModel):
    portal_token: str


class OtpResponse(BaseModel):
    message: str


@router.post(
    "/otp",
    response_model=OtpResponse,
    status_code=status.HTTP_200_OK,
    summary="Request a 6-digit OTP via SMS (patient passwordless auth)",
)
async def request_otp(
    body: OtpRequest,
    response: Response,
    redis: Redis = Depends(get_redis),
) -> OtpResponse:
    """Generate and deliver a one-time password to the patient's registered phone.

    Steps:
        1. Decode & validate portal_token (expiry + signature)
        2. Check rate limit — 429 if >= 5 attempts in the last hour
        3. Generate 6-digit OTP via secrets.randbelow
        4. Hash with bcrypt (12 rounds)
        5. Store hash in Redis (TTL=600 s)
        6. Increment attempt counter (TTL=3600 s, NX)
        7. Trigger Notification Service OTP delivery
        8. Return 200 {"message": "OTP sent. Check your SMS."}

    Security:
        patient_id and phone number are NOT written to any structured log.
        portal_token is NOT written to any log field.
    """
    # Step 1 — validate portal token (raises 401 if expired/invalid)
    claims: PortalTokenClaims = decode_portal_token(body.portal_token)

    # Step 2 — rate limit check (AC Scenario 2)
    blocked, retry_after = await is_rate_limited(redis, body.portal_token)
    if blocked:
        response.headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many OTP requests. Please wait before trying again.",
        )

    # Steps 3 & 4 — generate + hash OTP
    otp = generate_otp()
    otp_hash = hash_otp(otp)

    # Step 5 — store hash in Redis (TTL=600 s)
    await store_otp_hash(redis, body.portal_token, otp_hash)

    # Step 6 — increment attempt counter
    await increment_attempt_counter(redis, body.portal_token)

    # Step 7 — call Notification Service (internal) to send OTP via Twilio
    await _call_notification_service(claims.patient_id, otp)

    log.info(
        "otp_requested",
        extra={"encounter_id": claims.encounter_id},
        # patient_id and otp intentionally excluded from logs
    )

    return OtpResponse(message="OTP sent. Check your SMS.")


async def _call_notification_service(patient_id: str, otp: str) -> None:
    """POST to Notification Service internal endpoint to deliver OTP via Twilio.

    Internal service-to-service call (US-064 — Notification Service).
    Failure is re-raised so the caller receives HTTP 502 and can retry.
    The OTP plaintext is passed only in the internal request body and is
    never written to any log.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(
                f"{settings.NOTIFICATION_SERVICE_INTERNAL_URL}/internal/notify/otp",
                json={"patient_id": patient_id, "otp": otp},
                headers={"X-Internal-Key": settings.INTERNAL_SERVICE_KEY},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.error(
                "otp_notification_service_error",
                extra={"status_code": exc.response.status_code},
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OTP delivery failed. Please try again.",
            ) from exc
        except httpx.RequestError as exc:
            log.error("otp_notification_service_unreachable")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OTP delivery failed. Please try again.",
            ) from exc
```

---

## Validation Checklist

- [ ] `python -m py_compile api-gateway/app/routers/auth/patient_otp.py` — zero errors
- [ ] `python -m py_compile api-gateway/app/services/otp_service.py` — zero errors
- [ ] Valid portal token + first request → HTTP 200 `{"message": "OTP sent. Check your SMS."}`
- [ ] Redis key `otp:{portal_token}` set with TTL ≤ 600 s after successful call
- [ ] Redis key `otp_attempts:{portal_token}` incremented; TTL set to 3600 s on first increment only
- [ ] 5 successful calls: all return 200; 6th call returns 429 with `Retry-After` header
- [ ] Expired portal token → 401 (TASK-001 raises before rate limit check)
- [ ] OTP value does NOT appear in any log entry
- [ ] `patient_id` does NOT appear in any log entry (PHI)
- [ ] Notification Service unavailable → HTTP 502 (no OTP stored — test with mock)

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-052/TASK-001 | Task | `decode_portal_token()` utility |
| US-001 | Story | Redis instance available and `get_redis` dependency wired |
| US-064 | Story | Notification Service `/internal/notify/otp` endpoint |
| `bcrypt` | Package | OTP hashing (install: `pip install bcrypt`) |
| `redis[asyncio]` | Package | Async Redis client |
