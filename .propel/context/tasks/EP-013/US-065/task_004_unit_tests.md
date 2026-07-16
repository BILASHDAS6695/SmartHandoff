---
id: TASK-004
title: "Unit Tests — OTP Rate Limit, Expiry, Failed Attempts & Successful Verification"
user_story: US-065
epic: EP-013
sprint: 2
layer: Backend / Tests
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-065/TASK-001, US-065/TASK-002, US-065/TASK-003]
---

# TASK-004: Unit Tests — OTP Rate Limit, Expiry, Failed Attempts & Successful Verification

> **Story:** US-065 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Tests | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-065 DoD explicitly requires unit tests covering: rate limit enforcement, OTP expiry, failed attempt accumulation, and successful verification. All external dependencies (Redis, Twilio, `validate_portal_token`) are mocked using `pytest` + `unittest.mock` — no real network calls during CI.

Test file locations follow the project convention established in US-057/US-059:
- `backend/tests/unit/routers/test_auth_patient_otp.py`
- `backend/tests/unit/routers/test_auth_patient_verify.py`
- `backend/tests/unit/core/auth/test_otp_helpers.py`

---

## Acceptance Criteria Addressed

| US-065 DoD Item | Coverage |
|---|---|
| Unit tests: rate limit | `test_auth_patient_otp.py::test_rate_limit_exceeded` |
| Unit tests: expiry | `test_auth_patient_verify.py::test_otp_expired` |
| Unit tests: failed attempts | `test_auth_patient_verify.py::test_wrong_otp_increments_failures`, `test_third_failure_invalidates_otp` |
| Unit tests: successful verification | `test_auth_patient_verify.py::test_successful_verification_returns_jwt` |

---

## Implementation Steps

### 1. Create `backend/tests/unit/core/auth/test_otp_helpers.py`

```python
"""Unit tests for otp_helpers key derivation and bcrypt functions."""

import pytest
from unittest.mock import patch

# Patch settings before import to satisfy OTP_PHONE_SALT requirement
with patch("app.core.config.settings") as mock_settings:
    mock_settings.OTP_PHONE_SALT = "test-salt"
    from app.core.auth.otp_helpers import (
        otp_redis_key,
        rate_limit_redis_key,
        failures_redis_key,
        hash_otp,
        verify_otp,
    )


class TestKeyDerivation:
    def test_otp_key_prefix(self):
        assert otp_redis_key("token-abc").startswith("otp:")

    def test_rate_limit_key_prefix(self):
        assert rate_limit_redis_key("+12345678901").startswith("otp_rate:")

    def test_failures_key_prefix(self):
        assert failures_redis_key("token-abc").startswith("otp_failures:")

    def test_otp_key_does_not_contain_plaintext_token(self):
        token = "my-secret-portal-token"
        assert token not in otp_redis_key(token)

    def test_rate_limit_key_does_not_contain_phone(self):
        phone = "+12345678901"
        assert phone not in rate_limit_redis_key(phone)

    def test_different_tokens_produce_different_otp_keys(self):
        assert otp_redis_key("token-A") != otp_redis_key("token-B")

    def test_same_token_produces_stable_key(self):
        assert otp_redis_key("stable-token") == otp_redis_key("stable-token")


class TestBcryptHelpers:
    def test_hash_otp_returns_bcrypt_string(self):
        h = hash_otp("123456")
        assert h.startswith("$2b$")

    def test_verify_otp_correct_code(self):
        h = hash_otp("654321")
        assert verify_otp("654321", h) is True

    def test_verify_otp_wrong_code(self):
        h = hash_otp("111111")
        assert verify_otp("999999", h) is False

    def test_different_calls_produce_different_hashes(self):
        # bcrypt uses random salt — same OTP should yield different hashes
        assert hash_otp("123456") != hash_otp("123456")
```

### 2. Create `backend/tests/unit/routers/test_auth_patient_otp.py`

```python
"""Unit tests for POST /api/v1/auth/patient/otp."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app

VALID_TOKEN = "valid-portal-token"
PHONE = "+12345678901"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_claims():
    claims = MagicMock()
    claims.phone_number = PHONE
    claims.patient_id = "patient-uuid-001"
    return claims


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.incr.return_value = 1
    redis.ttl.return_value = 3600
    return redis


@pytest.fixture
def mock_twilio():
    client = MagicMock()
    verification = MagicMock()
    verification.sid = "VEXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
    verification.status = "pending"
    client.verify.v2.services.return_value.verifications.create.return_value = verification
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOTPRequest:
    @patch("app.routers.auth_patient_otp.validate_portal_token")
    @patch("app.routers.auth_patient_otp.get_redis")
    @patch("app.routers.auth_patient_otp.get_twilio_client")
    def test_valid_request_returns_202(
        self, mock_get_twilio, mock_get_redis, mock_validate, mock_claims, mock_redis, mock_twilio
    ):
        mock_validate.return_value = mock_claims
        mock_get_redis.return_value = mock_redis
        mock_get_twilio.return_value = mock_twilio

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/patient/otp",
                json={"portal_token": VALID_TOKEN},
            )
        assert resp.status_code == 202
        assert resp.json() == {"status": "otp_sent"}

    @patch("app.routers.auth_patient_otp.validate_portal_token")
    @patch("app.routers.auth_patient_otp.get_redis")
    @patch("app.routers.auth_patient_otp.get_twilio_client")
    def test_rate_limit_exceeded_returns_429(
        self, mock_get_twilio, mock_get_redis, mock_validate, mock_claims, mock_redis, mock_twilio
    ):
        """6th request within the window must return 429 with Retry-After header."""
        mock_validate.return_value = mock_claims
        mock_redis.incr.return_value = 6  # Exceeds RATE_LIMIT_MAX=5
        mock_redis.ttl.return_value = 3200
        mock_get_redis.return_value = mock_redis
        mock_get_twilio.return_value = mock_twilio

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/patient/otp",
                json={"portal_token": VALID_TOKEN},
            )

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        # Twilio must NOT be called when rate limit exceeded
        mock_twilio.verify.v2.services.return_value.verifications.create.assert_not_called()

    @patch("app.routers.auth_patient_otp.validate_portal_token")
    @patch("app.routers.auth_patient_otp.get_redis")
    @patch("app.routers.auth_patient_otp.get_twilio_client")
    def test_rate_limit_ttl_set_on_first_request(
        self, mock_get_twilio, mock_get_redis, mock_validate, mock_claims, mock_redis, mock_twilio
    ):
        """TTL must be set when counter is first incremented."""
        mock_validate.return_value = mock_claims
        mock_redis.incr.return_value = 1  # First request
        mock_get_redis.return_value = mock_redis
        mock_get_twilio.return_value = mock_twilio

        with TestClient(app) as client:
            client.post("/api/v1/auth/patient/otp", json={"portal_token": VALID_TOKEN})

        mock_redis.expire.assert_called_once()
        call_args = mock_redis.expire.call_args
        assert call_args[0][1] == 3600  # RATE_LIMIT_TTL_SECONDS
```

### 3. Create `backend/tests/unit/routers/test_auth_patient_verify.py`

```python
"""Unit tests for POST /api/v1/auth/patient/verify."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app

VALID_TOKEN = "valid-portal-token"
PHONE = "+12345678901"
VERIFICATION_SID = "VEXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"


@pytest.fixture
def mock_claims():
    claims = MagicMock()
    claims.phone_number = PHONE
    claims.patient_id = "patient-uuid-001"
    return claims


@pytest.fixture
def mock_redis_with_sid():
    """Redis has an active OTP session (SID present, no failures yet)."""
    redis = AsyncMock()
    redis.get.side_effect = lambda key: (
        VERIFICATION_SID.encode() if "otp:" in key and "failures" not in key and "rate" not in key
        else None
    )
    redis.incr.return_value = 1
    redis.expire = AsyncMock()
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def mock_twilio_approved():
    client = MagicMock()
    check = MagicMock()
    check.status = "approved"
    client.verify.v2.services.return_value.verification_checks.create.return_value = check
    return client


@pytest.fixture
def mock_twilio_rejected():
    client = MagicMock()
    check = MagicMock()
    check.status = "pending"  # Twilio returns "pending" for wrong code
    client.verify.v2.services.return_value.verification_checks.create.return_value = check
    return client


class TestOTPVerify:
    @patch("app.routers.auth_patient_verify.validate_portal_token")
    @patch("app.routers.auth_patient_verify.get_redis")
    @patch("app.routers.auth_patient_verify.get_twilio_client")
    @patch("app.routers.auth_patient_verify.create_access_token", return_value="jwt-token")
    def test_successful_verification_returns_jwt(
        self, mock_jwt, mock_get_twilio, mock_get_redis, mock_validate,
        mock_claims, mock_redis_with_sid, mock_twilio_approved
    ):
        mock_validate.return_value = mock_claims
        mock_get_redis.return_value = mock_redis_with_sid
        mock_get_twilio.return_value = mock_twilio_approved

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/patient/verify",
                json={"portal_token": VALID_TOKEN, "otp_code": "000000"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "jwt-token"
        assert body["token_type"] == "bearer"
        # Redis cleanup: otp: and otp_failures: keys deleted
        mock_redis_with_sid.delete.assert_called_once()

    @patch("app.routers.auth_patient_verify.validate_portal_token")
    @patch("app.routers.auth_patient_verify.get_redis")
    @patch("app.routers.auth_patient_verify.get_twilio_client")
    def test_otp_expired_when_redis_key_absent(
        self, mock_get_twilio, mock_get_redis, mock_validate,
        mock_claims, mock_twilio_approved
    ):
        """Missing Redis key (TTL elapsed) must return 401 otp_expired."""
        mock_validate.return_value = mock_claims
        redis = AsyncMock()
        redis.get.return_value = None  # Key expired
        mock_get_redis.return_value = redis
        mock_get_twilio.return_value = mock_twilio_approved

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/patient/verify",
                json={"portal_token": VALID_TOKEN, "otp_code": "000000"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"]["error"] == "otp_expired"

    @patch("app.routers.auth_patient_verify.validate_portal_token")
    @patch("app.routers.auth_patient_verify.get_redis")
    @patch("app.routers.auth_patient_verify.get_twilio_client")
    def test_wrong_otp_increments_failures_and_returns_attempts_remaining(
        self, mock_get_twilio, mock_get_redis, mock_validate,
        mock_claims, mock_redis_with_sid, mock_twilio_rejected
    ):
        mock_validate.return_value = mock_claims
        mock_redis_with_sid.get.side_effect = [
            VERIFICATION_SID.encode(),  # otp: key present
            b"0",                        # failures: 0
        ]
        mock_redis_with_sid.incr.return_value = 1  # After increment: 1 failure
        mock_get_redis.return_value = mock_redis_with_sid
        mock_get_twilio.return_value = mock_twilio_rejected

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/patient/verify",
                json={"portal_token": VALID_TOKEN, "otp_code": "999999"},
            )

        assert resp.status_code == 401
        body = resp.json()["detail"]
        assert body["error"] == "invalid_otp"
        assert body["attempts_remaining"] == 2  # MAX_FAILED_ATTEMPTS(3) - 1

    @patch("app.routers.auth_patient_verify.validate_portal_token")
    @patch("app.routers.auth_patient_verify.get_redis")
    @patch("app.routers.auth_patient_verify.get_twilio_client")
    def test_third_failure_invalidates_otp(
        self, mock_get_twilio, mock_get_redis, mock_validate,
        mock_claims, mock_redis_with_sid, mock_twilio_rejected
    ):
        """After 3 failures the OTP keys must be deleted and 0 attempts remain."""
        mock_validate.return_value = mock_claims
        mock_redis_with_sid.get.side_effect = [
            VERIFICATION_SID.encode(),  # otp: key
            b"2",                        # failures already at 2
        ]
        mock_redis_with_sid.incr.return_value = 3  # 3rd failure
        mock_get_redis.return_value = mock_redis_with_sid
        mock_get_twilio.return_value = mock_twilio_rejected

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/patient/verify",
                json={"portal_token": VALID_TOKEN, "otp_code": "999999"},
            )

        assert resp.status_code == 401
        body = resp.json()["detail"]
        assert body["error"] == "invalid_otp"
        assert body["attempts_remaining"] == 0
        # Both keys must be deleted
        mock_redis_with_sid.delete.assert_called_once()
```

---

## Validation

```bash
# Run all US-065 unit tests
cd backend
pytest tests/unit/core/auth/test_otp_helpers.py \
       tests/unit/routers/test_auth_patient_otp.py \
       tests/unit/routers/test_auth_patient_verify.py \
       -v --tb=short

# Expected: all tests PASSED, 0 failures
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/tests/unit/core/auth/test_otp_helpers.py` | Create |
| `backend/tests/unit/routers/test_auth_patient_otp.py` | Create |
| `backend/tests/unit/routers/test_auth_patient_verify.py` | Create |

---

## Definition of Done Checklist

- [ ] All test files created; `pytest` collects without import errors
- [ ] `test_rate_limit_exceeded_returns_429` passes — Twilio not called on 6th request
- [ ] `test_otp_expired_when_redis_key_absent` passes — `401 otp_expired` returned
- [ ] `test_wrong_otp_increments_failures_and_returns_attempts_remaining` passes — counter increments, `attempts_remaining` decrements
- [ ] `test_third_failure_invalidates_otp` passes — keys deleted, `attempts_remaining: 0`
- [ ] `test_successful_verification_returns_jwt` passes — JWT returned, Redis keys cleaned up
- [ ] No real Redis or Twilio calls in tests (all mocked)
- [ ] Test coverage for `otp_helpers.py` ≥ 90 %
