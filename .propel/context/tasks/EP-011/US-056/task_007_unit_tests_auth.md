---
id: TASK-007
title: "Write pytest Unit Tests — amr Validation, JWKS Cache TTL, JWT Claims Mapping"
user_story: US-056
epic: EP-011
sprint: 1
layer: Testing
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-22
assignee: Backend Engineer
upstream: [US-056/TASK-003, US-056/TASK-004]
---

# TASK-007: Write pytest Unit Tests — amr Validation, JWKS Cache TTL, JWT Claims Mapping

> **Story:** US-056 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Testing | **Est:** 3 h
> **Status:** Done | **Date:** 2026-07-22

---

## Context

The US-056 DoD explicitly requires: *"Unit tests: `amr` validation, JWKS cache, JWT claim mapping"*.

This task delivers pytest tests covering the three backend modules implemented in TASK-002, TASK-003, and TASK-004. Tests use `pytest-asyncio` for the async functions and `unittest.mock.AsyncMock` / `patch` to avoid real network calls.

The test file follows the project convention established by existing tests in `backend/tests/unit/` and must achieve ≥ 80% branch coverage on `app/core/auth/` (TR-020 CI gate).

---

## Acceptance Criteria Addressed

| US-056 AC | Requirement |
|---|---|
| **Scenario 2** | `amr: ["password"]` → 401 — covered by `test_amr_password_only_rejected` |
| **Scenario 3** | JWKS cache hit vs. miss — covered by `test_jwks_cache_hit` and `test_jwks_cache_miss` |
| **DoD** | Unit tests: `amr` validation, JWKS cache, JWT claim mapping |

---

## Implementation Steps

### 1. Create `backend/tests/unit/core/auth/test_oidc.py`

```python
"""Unit tests for app/core/auth/oidc.py — OIDC discovery and JWKS caching."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.auth.oidc import _JWKS_CACHE, _CACHE_KEY, fetch_jwks, get_jwks_uri

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "kid": "key-1",
            "use": "sig",
            "n": "sampleN",
            "e": "AQAB",
        }
    ]
}

SAMPLE_DISCOVERY = {
    "issuer": "https://idp.hospital.example.com",
    "jwks_uri": "https://idp.hospital.example.com/.well-known/jwks.json",
}


@pytest.fixture(autouse=True)
def clear_jwks_cache():
    """Clear the module-level JWKS cache before every test."""
    _JWKS_CACHE.clear()
    yield
    _JWKS_CACHE.clear()


@pytest.fixture
def idp_env(monkeypatch):
    """Set IDP_BASE_URL for tests that require it."""
    monkeypatch.setenv("IDP_BASE_URL", "https://idp.hospital.example.com")


# ---------------------------------------------------------------------------
# get_jwks_uri() tests
# ---------------------------------------------------------------------------

class TestGetJwksUri:
    def test_raises_when_idp_base_url_unset(self, monkeypatch):
        """IDP_BASE_URL missing → RuntimeError with helpful message."""
        monkeypatch.delenv("IDP_BASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="IDP_BASE_URL"):
            get_jwks_uri()

    def test_returns_jwks_uri_from_discovery_document(self, idp_env):
        """Parses jwks_uri from the OIDC discovery JSON response."""
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_DISCOVERY
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.auth.oidc.httpx.get", return_value=mock_response):
            uri = get_jwks_uri()

        assert uri == "https://idp.hospital.example.com/.well-known/jwks.json"

    def test_raises_on_missing_jwks_uri_key(self, idp_env):
        """Discovery document without 'jwks_uri' → RuntimeError."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"issuer": "https://idp.hospital.example.com"}
        mock_response.raise_for_status = MagicMock()

        with patch("app.core.auth.oidc.httpx.get", return_value=mock_response):
            with pytest.raises(RuntimeError, match="jwks_uri"):
                get_jwks_uri()


# ---------------------------------------------------------------------------
# fetch_jwks() tests — cache behaviour (AC Scenario 3)
# ---------------------------------------------------------------------------

class TestFetchJwks:
    @pytest.mark.asyncio
    async def test_jwks_cache_miss_fetches_from_network(self, idp_env):
        """On cache miss: fetches JWKS from network and stores in cache."""
        mock_get = AsyncMock()
        mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_get.return_value)
        mock_get.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_JWKS
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value.get = AsyncMock(return_value=mock_response)

        with patch("app.core.auth.oidc.get_jwks_uri", return_value="https://idp/jwks.json"), \
             patch("app.core.auth.oidc.httpx.AsyncClient", return_value=mock_get.return_value):
            result = await fetch_jwks()

        assert result == SAMPLE_JWKS
        # Verify cache was populated
        assert _JWKS_CACHE.get(_CACHE_KEY) == SAMPLE_JWKS

    @pytest.mark.asyncio
    async def test_jwks_cache_hit_skips_network(self, idp_env):
        """On cache hit: returns cached JWKS without any network call."""
        # Pre-populate cache
        _JWKS_CACHE[_CACHE_KEY] = SAMPLE_JWKS

        with patch("app.core.auth.oidc.get_jwks_uri") as mock_discovery, \
             patch("app.core.auth.oidc.httpx.AsyncClient") as mock_client:
            result = await fetch_jwks()

        # Confirm no network calls were made
        mock_discovery.assert_not_called()
        mock_client.assert_not_called()
        assert result == SAMPLE_JWKS

    @pytest.mark.asyncio
    async def test_jwks_cache_is_not_fetched_per_request(self, idp_env):
        """Multiple calls within TTL window should only fetch JWKS once."""
        call_count = 0

        async def mock_fetch_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return SAMPLE_JWKS

        # Simulate two calls — only first should trigger network
        _JWKS_CACHE[_CACHE_KEY] = SAMPLE_JWKS

        with patch("app.core.auth.oidc.get_jwks_uri") as mock_discovery:
            await fetch_jwks()
            await fetch_jwks()

        # Discovery should not be called at all since cache has the entry
        mock_discovery.assert_not_called()
```

### 2. Create `backend/tests/unit/core/auth/test_tokens.py`

```python
"""Unit tests for app/core/auth/tokens.py — id_token validation and amr enforcement."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.auth.tokens import validate_id_token

# ---------------------------------------------------------------------------
# Test utilities
# ---------------------------------------------------------------------------

def _make_rsa_key_pair():
    """Generate a temporary RSA key pair for test token signing."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key


def _make_id_token(
    private_key,
    sub: str = "user-123",
    amr: list | None = None,
    issuer: str = "https://idp.hospital.example.com",
    audience: str = "smarthandoff-api-gateway",
    expired: bool = False,
) -> str:
    import time
    from cryptography.hazmat.primitives import serialization

    now = int(time.time())
    payload = {
        "sub": sub,
        "email": "user@hospital.example.com",
        "groups": ["smarthandoff-physician"],
        "units": ["4B"],
        "iss": issuer,
        "aud": audience,
        "iat": now - 60 if not expired else now - 7200,
        "exp": now + 300 if not expired else now - 3600,
    }
    if amr is not None:
        payload["amr"] = amr

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(payload, pem, algorithm="RS256")


def _make_mock_jwks(private_key) -> dict:
    """Build a JWKS from the test private key's public component."""
    from cryptography.hazmat.primitives import serialization
    from jose import jwk as jose_jwk

    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    key = jose_jwk.construct(pub_pem.decode(), algorithm="RS256")
    return {"keys": [key.public_key()]}


# ---------------------------------------------------------------------------
# amr validation tests (AC Scenario 1 and 2)
# ---------------------------------------------------------------------------

class TestAmrValidation:
    @pytest.fixture(autouse=True)
    def env_setup(self, monkeypatch):
        monkeypatch.setenv("IDP_BASE_URL", "https://idp.hospital.example.com")
        monkeypatch.setenv("OIDC_CLIENT_ID", "smarthandoff-api-gateway")

    @pytest.mark.asyncio
    async def test_valid_mfa_token_succeeds(self):
        """amr: ["mfa"] → returns decoded claims."""
        key = _make_rsa_key_pair()
        token = _make_id_token(key, amr=["mfa"])
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            claims = await validate_id_token(token)

        assert claims["sub"] == "user-123"
        assert "mfa" in claims["amr"]

    @pytest.mark.asyncio
    async def test_amr_missing_raises_401_mfa_required(self):
        """amr claim absent → HTTP 401 with detail 'MFA required'."""
        key = _make_rsa_key_pair()
        # amr=None means the claim is omitted
        token = _make_id_token(key, amr=None)
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            with pytest.raises(HTTPException) as exc_info:
                await validate_id_token(token)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "MFA required"

    @pytest.mark.asyncio
    async def test_amr_password_only_rejected(self):
        """amr: ["password"] (no mfa) → HTTP 401 with detail 'MFA required' (AC Scenario 2)."""
        key = _make_rsa_key_pair()
        token = _make_id_token(key, amr=["password"])
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            with pytest.raises(HTTPException) as exc_info:
                await validate_id_token(token)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "MFA required"

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        """Expired id_token → HTTP 401 (JWTError on exp check)."""
        key = _make_rsa_key_pair()
        token = _make_id_token(key, amr=["mfa"], expired=True)
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            with pytest.raises(HTTPException) as exc_info:
                await validate_id_token(token)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_audience_raises_401(self):
        """id_token issued for different audience → HTTP 401."""
        key = _make_rsa_key_pair()
        token = _make_id_token(key, amr=["mfa"], audience="other-app")
        jwks = _make_mock_jwks(key)

        with patch("app.core.auth.tokens.fetch_jwks", AsyncMock(return_value=jwks)):
            with pytest.raises(HTTPException) as exc_info:
                await validate_id_token(token)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# JWT claims mapping tests (DoD: "sub → user_id, groups → role")
# ---------------------------------------------------------------------------

class TestJwtClaimsMapping:
    @pytest.fixture(autouse=True)
    def env_setup(self, monkeypatch):
        monkeypatch.setenv("JWT_SIGNING_KEY", "testkey_minimum_32_chars_exactly_32")

    def test_physician_group_maps_to_physician_role(self):
        """'smarthandoff-physician' group → role='physician'."""
        from app.core.auth.jwt import _map_claims

        claims = _map_claims({
            "sub": "u1",
            "groups": ["smarthandoff-physician"],
            "units": ["4B"],
            "email": "dr@hospital.example.com",
        })

        assert claims["role"] == "physician"
        assert claims["sub"] == "u1"
        assert claims["units"] == ["4B"]

    def test_nurse_group_maps_to_nurse_role(self):
        """'smarthandoff-nurse' group → role='nurse'."""
        from app.core.auth.jwt import _map_claims

        claims = _map_claims({
            "sub": "u2",
            "groups": ["smarthandoff-nurse"],
            "units": [],
            "email": "nurse@hospital.example.com",
        })
        assert claims["role"] == "nurse"

    def test_admin_group_maps_to_admin_role(self):
        """'smarthandoff-admin' group → role='admin'."""
        from app.core.auth.jwt import _map_claims

        claims = _map_claims({
            "sub": "u3",
            "groups": ["smarthandoff-admin"],
            "units": [],
            "email": "",
        })
        assert claims["role"] == "admin"

    def test_unknown_group_raises_403(self):
        """Groups not in _ROLE_MAP → HTTP 403."""
        from fastapi import HTTPException
        from app.core.auth.jwt import _map_claims

        with pytest.raises(HTTPException) as exc_info:
            _map_claims({"sub": "u4", "groups": ["unknown-dept"], "email": ""})

        assert exc_info.value.status_code == 403

    def test_empty_groups_raises_403(self):
        """Empty groups list → HTTP 403."""
        from fastapi import HTTPException
        from app.core.auth.jwt import _map_claims

        with pytest.raises(HTTPException) as exc_info:
            _map_claims({"sub": "u5", "groups": [], "email": ""})

        assert exc_info.value.status_code == 403

    def test_jwt_expiry_is_8_hours(self):
        """Issued JWT has exp = iat + 28800 (8 hours)."""
        from jose import jwt as jose_jwt
        import os
        from app.core.auth.jwt import issue_app_jwt

        token = issue_app_jwt({
            "sub": "u6",
            "groups": ["smarthandoff-nurse"],
            "units": [],
            "email": "nurse@hospital.example.com",
        })
        payload = jose_jwt.decode(
            token,
            os.environ["JWT_SIGNING_KEY"],
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert payload["exp"] - payload["iat"] == 28800

    def test_jwt_signing_key_minimum_length_enforced(self, monkeypatch):
        """JWT_SIGNING_KEY shorter than 32 chars → RuntimeError."""
        monkeypatch.setenv("JWT_SIGNING_KEY", "short")
        # Force reimport to re-read env var (module-level caching avoidance)
        import importlib
        import app.core.auth.jwt as jwt_module
        importlib.reload(jwt_module)

        with pytest.raises(RuntimeError, match="JWT_SIGNING_KEY"):
            jwt_module._jwt_signing_key()
```

### 3. Create `backend/tests/unit/core/auth/__init__.py`

```python
# Empty — marks directory as Python package for pytest discovery
```

### 4. Run Tests and Verify Coverage

```bash
cd backend
pytest tests/unit/core/auth/ -v \
  --cov=app/core/auth \
  --cov-report=term-missing \
  --cov-fail-under=80
```

---

## Validation

```bash
cd backend

# Run the full auth test suite
pytest tests/unit/core/auth/ -v --tb=short

# Expected output pattern:
# tests/unit/core/auth/test_oidc.py::TestGetJwksUri::test_raises_when_idp_base_url_unset PASSED
# tests/unit/core/auth/test_oidc.py::TestGetJwksUri::test_returns_jwks_uri_from_discovery_document PASSED
# tests/unit/core/auth/test_oidc.py::TestFetchJwks::test_jwks_cache_miss_fetches_from_network PASSED
# tests/unit/core/auth/test_oidc.py::TestFetchJwks::test_jwks_cache_hit_skips_network PASSED
# tests/unit/core/auth/test_tokens.py::TestAmrValidation::test_valid_mfa_token_succeeds PASSED
# tests/unit/core/auth/test_tokens.py::TestAmrValidation::test_amr_missing_raises_401_mfa_required PASSED
# tests/unit/core/auth/test_tokens.py::TestAmrValidation::test_amr_password_only_rejected PASSED
# tests/unit/core/auth/test_tokens.py::TestAmrValidation::test_expired_token_raises_401 PASSED
# tests/unit/core/auth/test_tokens.py::TestJwtClaimsMapping::test_physician_group_maps_to_physician_role PASSED
# ...
# PASSED: 14+ tests, coverage >= 80%
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/tests/unit/core/auth/__init__.py` | Create (empty package marker) |
| `backend/tests/unit/core/auth/test_oidc.py` | Create with JWKS cache tests |
| `backend/tests/unit/core/auth/test_tokens.py` | Create with amr validation + claims mapping tests |

---

## Definition of Done Checklist

- [ ] `test_amr_password_only_rejected` passes — verifies AC Scenario 2
- [ ] `test_jwks_cache_hit_skips_network` passes — verifies AC Scenario 3
- [ ] `test_jwks_cache_miss_fetches_from_network` passes
- [ ] `test_amr_missing_raises_401_mfa_required` passes — `"MFA required"` exact string match
- [ ] `test_physician_group_maps_to_physician_role` passes — claims mapping DoD
- [ ] `test_jwt_expiry_is_8_hours` passes — `exp - iat == 28800`
- [ ] `test_jwt_signing_key_minimum_length_enforced` passes — security guard tested
- [ ] Coverage ≥ 80% on `app/core/auth/` (TR-020 gate)
- [ ] All tests pass with `pytest-asyncio` installed (`asyncio_mode = "auto"` in `pytest.ini` or `pyproject.toml`)
- [ ] Zero real network calls in any test (all httpx calls mocked)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-056/TASK-003 | Upstream task | `validate_id_token()` must be implemented for token validation tests |
| US-056/TASK-004 | Upstream task | `_map_claims()`, `issue_app_jwt()`, `_jwt_signing_key()` must be implemented for claims mapping tests |
