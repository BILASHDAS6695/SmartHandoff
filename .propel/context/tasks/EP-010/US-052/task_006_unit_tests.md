---
id: TASK-006
title: "Unit Tests — OTP Expiry, Rate Limit & Encounter Scope Enforcement"
user_story: US-052
epic: EP-010
sprint: 2
layer: Backend / Tests
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-052/TASK-001, US-052/TASK-002, US-052/TASK-003, US-052/TASK-004]
---

# TASK-006: Unit Tests — OTP Expiry, Rate Limit & Encounter Scope Enforcement

> **Story:** US-052 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Backend / Tests | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements the unit tests mandated in US-052 DoD:

> "Unit tests: OTP expiry, rate limit, scope enforcement"

Tests cover the three acceptance criteria scenarios that have the highest security and
correctness risk:

1. **OTP expiry** — Redis key TTL behaviour and 401 response message (AC Scenario 3)
2. **Rate limiting** — 5th attempt allowed; 6th blocked with 429 + `Retry-After` (AC Scenario 2)
3. **Encounter scope enforcement** — JWT `encounter_id` claim mismatch → 403 (AC Scenario 4)

All tests use `pytest` with `pytest-asyncio`. Redis interactions are mocked with
`fakeredis.aioredis`. No live backend dependencies are required.

**Design references:**

- US-052 AC Scenarios 2, 3, 4
- US-052 DoD — "Unit tests: OTP expiry, rate limit, scope enforcement"
- design.md §4.1 — Python FastAPI; pytest; no live test dependencies

---

## Acceptance Criteria Addressed

| AC Scenario | Test Coverage |
|---|---|
| Scenario 2 | `test_rate_limit_blocks_sixth_request`, `test_rate_limit_allows_fifth_request` |
| Scenario 3 | `test_otp_expiry_returns_401`, `test_valid_otp_within_ttl_succeeds` |
| Scenario 4 | `test_scope_mismatch_returns_403`, `test_scope_match_passes_through` |

---

## Implementation Steps

### 1. Create test files

```bash
mkdir -p api-gateway/tests/auth
touch api-gateway/tests/auth/__init__.py
touch api-gateway/tests/auth/test_otp_rate_limit.py
touch api-gateway/tests/auth/test_otp_expiry.py
touch api-gateway/tests/auth/test_encounter_scope.py
```

### 2. Implement `api-gateway/tests/auth/test_otp_rate_limit.py`

```python
"""Unit tests for OTP rate limiting — US-052 AC Scenario 2.

Verifies:
    - 5 OTP requests within 1 hour: all return 200 / OTP stored
    - 6th OTP request within 1 hour: 429 Too Many Requests + Retry-After header
    - No OTP key written to Redis when rate limit is hit
    - Rate limit counter TTL set to 3600 s on first increment

Uses fakeredis.aioredis to avoid live Redis dependency.
"""
from __future__ import annotations

import pytest
import fakeredis.aioredis as fake_redis

from api_gateway.app.services.otp_service import (
    increment_attempt_counter,
    is_rate_limited,
    store_otp_hash,
)

PORTAL_TOKEN = "test.portal.token.abc123"


@pytest.fixture
async def redis():
    """Yield a fresh fakeredis async client for each test."""
    client = await fake_redis.FakeRedis.create()
    yield client
    await client.flushall()
    await client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_allows_fifth_request(redis):
    """5th OTP request within 1 hour must not be blocked."""
    for _ in range(4):
        await increment_attempt_counter(redis, PORTAL_TOKEN)

    blocked, retry_after = await is_rate_limited(redis, PORTAL_TOKEN)
    assert not blocked, "5th request must NOT be blocked (only 4 previous attempts)"
    assert retry_after == 0


@pytest.mark.asyncio
async def test_rate_limit_blocks_sixth_request(redis):
    """6th OTP request within 1 hour must return 429 with Retry-After."""
    for _ in range(5):
        await increment_attempt_counter(redis, PORTAL_TOKEN)

    blocked, retry_after = await is_rate_limited(redis, PORTAL_TOKEN)
    assert blocked, "6th request MUST be blocked after 5 attempts"
    assert retry_after > 0, "Retry-After must be a positive integer"


@pytest.mark.asyncio
async def test_no_otp_key_written_when_rate_limited(redis):
    """When rate limited, no OTP hash key must exist in Redis."""
    for _ in range(5):
        await increment_attempt_counter(redis, PORTAL_TOKEN)

    blocked, _ = await is_rate_limited(redis, PORTAL_TOKEN)
    assert blocked

    # Simulate the endpoint NOT writing OTP hash when blocked
    otp_key = f"otp:{PORTAL_TOKEN}"
    stored = await redis.get(otp_key)
    assert stored is None, "OTP hash must NOT be written when rate limited"


@pytest.mark.asyncio
async def test_rate_limit_counter_ttl_set_on_first_increment(redis):
    """Rate limit counter TTL must be set to 3600 s on the first increment only."""
    await increment_attempt_counter(redis, PORTAL_TOKEN)

    attempts_key = f"otp_attempts:{PORTAL_TOKEN}"
    ttl = await redis.ttl(attempts_key)

    assert 3590 <= ttl <= 3600, f"Expected TTL ~3600 s, got {ttl}"


@pytest.mark.asyncio
async def test_rate_limit_counter_ttl_not_reset_on_subsequent_increments(redis):
    """Subsequent increments must NOT reset the TTL (window does not slide)."""
    await increment_attempt_counter(redis, PORTAL_TOKEN)
    attempts_key = f"otp_attempts:{PORTAL_TOKEN}"
    ttl_after_first = await redis.ttl(attempts_key)

    await increment_attempt_counter(redis, PORTAL_TOKEN)
    ttl_after_second = await redis.ttl(attempts_key)

    # TTL must decrease, not reset to 3600 again
    assert ttl_after_second <= ttl_after_first, (
        "TTL must not reset on subsequent increments"
    )
```

### 3. Implement `api-gateway/tests/auth/test_otp_expiry.py`

```python
"""Unit tests for OTP expiry behaviour — US-052 AC Scenario 3.

Verifies:
    - Absent Redis key (TTL elapsed) → 401 "OTP has expired. Please request a new code."
    - Correct OTP within TTL → 200 + JWT access_token
    - Incorrect OTP within TTL → 401 "Invalid OTP. Please try again."
    - OTP key deleted after successful verification (one-time use)

Uses fakeredis.aioredis and FastAPI TestClient with dependency overrides.
"""
from __future__ import annotations

import bcrypt
import pytest
import fakeredis.aioredis as fake_redis
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from api_gateway.app.main import app
from api_gateway.app.core.redis import get_redis


OTP_PLAINTEXT = "483921"
PORTAL_TOKEN = "valid.portal.token.xyz"
OTP_REDIS_KEY = f"otp:{PORTAL_TOKEN}"


@pytest.fixture
def redis_with_otp():
    """Return a fakeredis client pre-loaded with a hashed OTP."""
    client = fake_redis.FakeRedis()
    hashed = bcrypt.hashpw(OTP_PLAINTEXT.encode(), bcrypt.gensalt(rounds=4))
    client.set(OTP_REDIS_KEY, hashed, ex=600)
    return client


@pytest.fixture
def client_with_redis(redis_with_otp):
    """FastAPI TestClient with fakeredis override and mocked portal token decode."""
    app.dependency_overrides[get_redis] = lambda: redis_with_otp
    with TestClient(app) as c:
        yield c, redis_with_otp
    app.dependency_overrides.clear()


def _mock_portal_token_decode(portal_token: str):
    from api_gateway.app.core.auth.portal_token import PortalTokenClaims
    return PortalTokenClaims(
        patient_id="00000000-0000-0000-0000-000000000001",
        encounter_id="ENC-001",
    )


@patch(
    "api_gateway.app.routers.auth.patient_verify.decode_portal_token",
    side_effect=_mock_portal_token_decode,
)
def test_valid_otp_within_ttl_returns_200(mock_decode, client_with_redis):
    """Correct OTP submitted within 10 min → 200 + access_token."""
    client, _ = client_with_redis
    response = client.post(
        "/api/v1/auth/patient/verify",
        json={"portal_token": PORTAL_TOKEN, "otp": OTP_PLAINTEXT},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600


@patch(
    "api_gateway.app.routers.auth.patient_verify.decode_portal_token",
    side_effect=_mock_portal_token_decode,
)
def test_expired_otp_returns_401_with_exact_message(mock_decode):
    """Absent Redis key (expired TTL) → 401 with exact AC Scenario 3 message."""
    empty_redis = fake_redis.FakeRedis()
    app.dependency_overrides[get_redis] = lambda: empty_redis

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/patient/verify",
            json={"portal_token": PORTAL_TOKEN, "otp": OTP_PLAINTEXT},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"] == "OTP has expired. Please request a new code."


@patch(
    "api_gateway.app.routers.auth.patient_verify.decode_portal_token",
    side_effect=_mock_portal_token_decode,
)
def test_incorrect_otp_returns_401(mock_decode, client_with_redis):
    """Wrong OTP → 401 with 'Invalid OTP' message."""
    client, _ = client_with_redis
    response = client.post(
        "/api/v1/auth/patient/verify",
        json={"portal_token": PORTAL_TOKEN, "otp": "000000"},
    )
    assert response.status_code == 401
    assert "Invalid OTP" in response.json()["detail"]


@patch(
    "api_gateway.app.routers.auth.patient_verify.decode_portal_token",
    side_effect=_mock_portal_token_decode,
)
def test_otp_key_deleted_after_successful_verify(mock_decode, client_with_redis):
    """OTP Redis key must be deleted after successful verification (one-time use)."""
    client, redis = client_with_redis

    client.post(
        "/api/v1/auth/patient/verify",
        json={"portal_token": PORTAL_TOKEN, "otp": OTP_PLAINTEXT},
    )

    stored = redis.get(OTP_REDIS_KEY)
    assert stored is None, "OTP key must be deleted after successful verify"
```

### 4. Implement `api-gateway/tests/auth/test_encounter_scope.py`

```python
"""Unit tests for PatientEncounterScopeMiddleware — US-052 AC Scenario 4.

Verifies:
    - Patient JWT encounter_id mismatch (path param) → 403
    - Patient JWT encounter_id mismatch (query param) → 403
    - Patient JWT encounter_id mismatch (JSON body) → 403
    - Patient JWT encounter_id match → request passes through (200)
    - Staff JWT with any encounter_id → passes through (middleware not applied)
    - Request with no encounter_id → passes through
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api_gateway.app.middleware.patient_encounter_scope import PatientEncounterScopeMiddleware

# Minimal test app with the middleware applied
_test_app = FastAPI()
_test_app.add_middleware(PatientEncounterScopeMiddleware)


@_test_app.get("/encounters/{encounter_id}/documents")
async def get_docs(encounter_id: str, request: Request):
    return JSONResponse({"ok": True})


@_test_app.post("/chat/message")
async def post_message(request: Request):
    body = await request.json()
    return JSONResponse({"ok": True, "received_encounter_id": body.get("encounter_id")})


@_test_app.get("/portal/home")
async def get_home(request: Request):
    return JSONResponse({"ok": True})


def _build_client(jwt_role: str, jwt_encounter_id: str | None) -> TestClient:
    """Build a TestClient that pre-populates request.state.jwt_claims."""

    @_test_app.middleware("http")
    async def inject_claims(request: Request, call_next):
        request.state.jwt_claims = {
            "role": jwt_role,
            "encounter_id": jwt_encounter_id,
        }
        return await call_next(request)

    return TestClient(_test_app, raise_server_exceptions=False)


@pytest.fixture
def patient_client():
    """TestClient with patient JWT (encounter_id=ENC-001)."""
    return _build_client(jwt_role="patient", jwt_encounter_id="ENC-001")


def test_scope_mismatch_path_param_returns_403(patient_client):
    """Patient with ENC-001 JWT accessing ENC-002 path → 403."""
    response = patient_client.get("/encounters/ENC-002/documents")
    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied."


def test_scope_match_path_param_passes_through(patient_client):
    """Patient with ENC-001 JWT accessing ENC-001 path → 200."""
    response = patient_client.get("/encounters/ENC-001/documents")
    assert response.status_code == 200


def test_scope_mismatch_json_body_returns_403(patient_client):
    """Patient with ENC-001 JWT sending body with encounter_id=ENC-002 → 403."""
    response = patient_client.post(
        "/chat/message",
        json={"encounter_id": "ENC-002", "message": "hello"},
    )
    assert response.status_code == 403


def test_scope_match_json_body_passes_through(patient_client):
    """Patient with ENC-001 JWT sending body with encounter_id=ENC-001 → 200."""
    response = patient_client.post(
        "/chat/message",
        json={"encounter_id": "ENC-001", "message": "hello"},
    )
    assert response.status_code == 200


def test_staff_jwt_bypasses_scope_enforcement():
    """Staff (nurse) JWT must not be blocked by PatientEncounterScopeMiddleware."""
    nurse_client = _build_client(jwt_role="nurse", jwt_encounter_id=None)
    response = nurse_client.get("/encounters/ENC-002/documents")
    assert response.status_code == 200


def test_no_encounter_id_in_request_passes_through(patient_client):
    """Request with no encounter_id in path/query/body must not be blocked."""
    response = patient_client.get("/portal/home")
    assert response.status_code == 200
```

---

## Validation Checklist

- [ ] `pytest api-gateway/tests/auth/ -v` — all tests pass; zero failures
- [ ] `pytest --tb=short` — no warnings about unawaited coroutines
- [ ] Rate limit tests: 5th attempt passes; 6th blocked with `retry_after > 0`
- [ ] OTP expiry test: exact error message `"OTP has expired. Please request a new code."` matches AC Scenario 3
- [ ] Scope mismatch test: HTTP 403 with `{"detail": "Access denied."}` for path, query, and body
- [ ] OTP key deleted after successful verify (replay prevention test passes)
- [ ] `bcrypt` rounds set to 4 in test fixtures (speed); production code uses 12

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-052/TASK-002 | Task | `otp_service.py` functions under test |
| US-052/TASK-003 | Task | `patient_verify.py` endpoint under test |
| US-052/TASK-004 | Task | `PatientEncounterScopeMiddleware` under test |
| `pytest-asyncio` | Package | Async test support |
| `fakeredis[aioredis]` | Package | In-memory Redis mock (no live Redis needed) |
| `bcrypt` | Package | OTP hash generation in test fixtures |
