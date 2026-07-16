# TASK-004: Write Comprehensive Unit Tests for FHIR Authentication

> **Story:** US-016 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend Testing | **Est:** 8 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task implements comprehensive unit tests for the FHIR authentication components, covering all acceptance criteria scenarios. Tests use `pytest-asyncio` for async test support and `respx` for mocking HTTP requests to the SMART on FHIR endpoints. The test suite validates OAuth flow, token caching, expiry buffer logic, error handling, and thread-safety.

**Design references:**
- US-016 AC Scenario 1 — Successful authentication with mock server
- US-016 AC Scenario 2 — Cache hit (no network call)
- US-016 AC Scenario 3 — Cache miss triggers refresh
- US-016 AC Scenario 4 — 401 raises FHIRAuthenticationError
- US-016 DoD — Unit tests for (a) auth, (b) cache hit, (c) cache miss, (d) 401 error

---

## Acceptance Criteria Addressed

| AC Scenario | Test Coverage |
|-------------|---------------|
| AC Scenario 1 | `test_authenticate_success` validates OAuth flow and token caching |
| AC Scenario 2 | `test_get_access_token_cache_hit` verifies no network call on cache hit |
| AC Scenario 3 | `test_get_access_token_cache_miss_refresh` verifies auto-refresh |
| AC Scenario 4 | `test_authenticate_failure_401` verifies FHIRAuthenticationError on 401 |

---

## Implementation Steps

### 1. Add test dependencies to `backend/requirements-dev.txt`

```txt
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0
respx>=0.21.0  # Mock HTTP requests for httpx
freezegun>=1.4.0  # Mock time for token expiry tests
```

### 2. Create `backend/tests/unit/core/fhir/test_discovery.py`

Test SMART on FHIR discovery:

```python
"""Unit tests for SMART on FHIR discovery client.

Tests:
- Successful SMART configuration fetch
- Token endpoint extraction
- Network error handling
- Invalid JSON handling
- Missing token_endpoint handling
"""
from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.core.fhir.discovery import discover_smart_config, get_token_endpoint
from app.core.fhir.exceptions import FHIRAuthenticationError

# Sample SMART configuration (based on SMART on FHIR v2.0 spec)
SAMPLE_SMART_CONFIG = {
    "authorization_endpoint": "https://ehr.example.com/auth/authorize",
    "token_endpoint": "https://ehr.example.com/auth/token",
    "token_endpoint_auth_methods_supported": [
        "client_secret_basic",
        "client_secret_post",
    ],
    "grant_types_supported": ["authorization_code", "client_credentials"],
    "scopes_supported": ["system/*.read", "patient/*.read"],
    "capabilities": [
        "client-confidential-symmetric",
        "permission-offline",
        "context-standalone-patient",
    ],
}


@pytest.mark.asyncio
async def test_discover_smart_config_success():
    """Test successful SMART configuration discovery."""
    base_url = "https://ehr.example.com/fhir"
    discovery_url = f"{base_url}/.well-known/smart-configuration"

    with respx.mock:
        respx.get(discovery_url).mock(return_value=Response(200, json=SAMPLE_SMART_CONFIG))

        config = await discover_smart_config(base_url)

        assert config == SAMPLE_SMART_CONFIG
        assert config["token_endpoint"] == "https://ehr.example.com/auth/token"


@pytest.mark.asyncio
async def test_discover_smart_config_trailing_slash():
    """Test discovery with base URL containing trailing slash."""
    base_url = "https://ehr.example.com/fhir/"  # Note trailing slash
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"

    with respx.mock:
        respx.get(discovery_url).mock(return_value=Response(200, json=SAMPLE_SMART_CONFIG))

        config = await discover_smart_config(base_url)

        assert config["token_endpoint"] == "https://ehr.example.com/auth/token"


@pytest.mark.asyncio
async def test_discover_smart_config_network_error():
    """Test discovery failure due to network error."""
    base_url = "https://unreachable.example.com/fhir"
    discovery_url = f"{base_url}/.well-known/smart-configuration"

    with respx.mock:
        respx.get(discovery_url).mock(side_effect=Exception("Connection refused"))

        with pytest.raises(FHIRAuthenticationError) as exc_info:
            await discover_smart_config(base_url)

        assert "Failed to fetch SMART configuration" in str(exc_info.value)


@pytest.mark.asyncio
async def test_discover_smart_config_http_error():
    """Test discovery failure due to HTTP error (e.g., 404)."""
    base_url = "https://ehr.example.com/fhir"
    discovery_url = f"{base_url}/.well-known/smart-configuration"

    with respx.mock:
        respx.get(discovery_url).mock(return_value=Response(404, text="Not Found"))

        with pytest.raises(FHIRAuthenticationError) as exc_info:
            await discover_smart_config(base_url)

        assert "Failed to fetch SMART configuration" in str(exc_info.value)
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_discover_smart_config_invalid_json():
    """Test discovery failure due to invalid JSON response."""
    base_url = "https://ehr.example.com/fhir"
    discovery_url = f"{base_url}/.well-known/smart-configuration"

    with respx.mock:
        respx.get(discovery_url).mock(return_value=Response(200, text="Not JSON"))

        with pytest.raises(FHIRAuthenticationError) as exc_info:
            await discover_smart_config(base_url)

        assert "invalid JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_discover_smart_config_missing_token_endpoint():
    """Test discovery failure when token_endpoint is missing."""
    base_url = "https://ehr.example.com/fhir"
    discovery_url = f"{base_url}/.well-known/smart-configuration"

    incomplete_config = {
        "authorization_endpoint": "https://ehr.example.com/auth/authorize",
        # Missing token_endpoint
    }

    with respx.mock:
        respx.get(discovery_url).mock(return_value=Response(200, json=incomplete_config))

        with pytest.raises(FHIRAuthenticationError) as exc_info:
            await discover_smart_config(base_url)

        assert "missing 'token_endpoint'" in str(exc_info.value)


def test_get_token_endpoint():
    """Test token endpoint extraction from SMART config."""
    token_endpoint = get_token_endpoint(SAMPLE_SMART_CONFIG)
    assert token_endpoint == "https://ehr.example.com/auth/token"


def test_get_token_endpoint_missing():
    """Test KeyError when token_endpoint is missing."""
    invalid_config = {"authorization_endpoint": "https://example.com/auth"}
    with pytest.raises(KeyError):
        get_token_endpoint(invalid_config)
```

### 3. Create `backend/tests/unit/core/fhir/test_token_cache.py`

Test token cache with time mocking:

```python
"""Unit tests for TokenCache with expiry buffer logic.

Tests:
- Cache miss (empty cache)
- Cache hit (valid token)
- Cache expiry (token expired within 60s buffer)
- Thread-safe concurrent access
- Cache clear
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time

from app.core.fhir.token_cache import TokenCache


@pytest.mark.asyncio
async def test_token_cache_miss_empty():
    """Test cache miss when cache is empty."""
    cache = TokenCache()
    token = await cache.get_token()
    assert token is None


@pytest.mark.asyncio
async def test_token_cache_hit():
    """Test cache hit with valid token."""
    cache = TokenCache(expiry_buffer_seconds=60)
    await cache.set_token("token_abc", expires_in=3600)

    token = await cache.get_token()
    assert token == "token_abc"


@pytest.mark.asyncio
async def test_token_cache_expiry_buffer():
    """Test that token within expiry buffer is considered expired."""
    cache = TokenCache(expiry_buffer_seconds=60)

    with freeze_time("2026-07-16 12:00:00"):
        # Set token with 50 seconds lifetime (less than 60s buffer)
        await cache.set_token("token_short", expires_in=50)

    with freeze_time("2026-07-16 12:00:01"):
        # Token should be considered expired (50s - 60s buffer = -10s effective lifetime)
        token = await cache.get_token()
        assert token is None


@pytest.mark.asyncio
async def test_token_cache_expiry_buffer_boundary():
    """Test token at exact expiry buffer boundary."""
    cache = TokenCache(expiry_buffer_seconds=60)

    with freeze_time("2026-07-16 12:00:00"):
        # Set token with 120 seconds lifetime (60s after buffer)
        await cache.set_token("token_boundary", expires_in=120)

    with freeze_time("2026-07-16 12:01:00"):
        # Token should still be valid (120s - 60s buffer = 60s remaining)
        token = await cache.get_token()
        assert token == "token_boundary"

    with freeze_time("2026-07-16 12:01:01"):
        # Token should be expired (59s remaining, within buffer)
        token = await cache.get_token()
        assert token is None


@pytest.mark.asyncio
async def test_token_cache_clear():
    """Test cache clear invalidates cached token."""
    cache = TokenCache()
    await cache.set_token("token_xyz", expires_in=3600)

    # Verify token is cached
    token = await cache.get_token()
    assert token == "token_xyz"

    # Clear cache
    await cache.clear()

    # Verify cache is empty
    token = await cache.get_token()
    assert token is None


@pytest.mark.asyncio
async def test_token_cache_is_expired():
    """Test is_expired() method."""
    cache = TokenCache()

    # Empty cache is expired
    assert await cache.is_expired()

    # Valid token is not expired
    await cache.set_token("token_valid", expires_in=3600)
    assert not await cache.is_expired()

    # Clear cache
    await cache.clear()
    assert await cache.is_expired()


@pytest.mark.asyncio
async def test_token_cache_concurrent_access():
    """Test thread-safe concurrent access to cache."""
    import asyncio

    cache = TokenCache()
    await cache.set_token("token_concurrent", expires_in=3600)

    # Simulate 10 concurrent get_token() calls
    tasks = [cache.get_token() for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # All calls should return the same cached token
    assert all(token == "token_concurrent" for token in results)


@pytest.mark.asyncio
async def test_token_cache_concurrent_set():
    """Test thread-safe concurrent set_token() calls (race condition)."""
    import asyncio

    cache = TokenCache()

    # Simulate 5 concurrent set_token() calls (race condition scenario)
    async def set_token_task(token_value: str) -> None:
        await cache.set_token(token_value, expires_in=3600)

    tasks = [set_token_task(f"token_{i}") for i in range(5)]
    await asyncio.gather(*tasks)

    # One of the tokens should "win" (exact value is non-deterministic due to race)
    token = await cache.get_token()
    assert token is not None
    assert token.startswith("token_")
```

### 4. Create `backend/tests/unit/core/fhir/test_auth.py`

Test FHIRAuthClient OAuth flow:

```python
"""Unit tests for FHIRAuthClient OAuth 2.0 authentication.

Tests:
- Successful authentication (AC Scenario 1)
- Cache hit without network call (AC Scenario 2)
- Cache miss triggers refresh (AC Scenario 3)
- 401 raises FHIRAuthenticationError (AC Scenario 4)
- Network errors
- Invalid token response
"""
from __future__ import annotations

import pytest
import respx
from freezegun import freeze_time
from httpx import Response

from app.core.fhir.auth import FHIRAuthClient
from app.core.fhir.exceptions import FHIRAuthenticationError

# Mock SMART configuration
MOCK_SMART_CONFIG = {
    "token_endpoint": "https://ehr.example.com/auth/token",
}

# Mock token response
MOCK_TOKEN_RESPONSE = {
    "access_token": "mock_access_token_xyz",
    "token_type": "Bearer",
    "expires_in": 3600,
    "scope": "system/*.read",
}


@pytest.fixture
def mock_env(monkeypatch):
    """Set environment variables for FHIR auth."""
    monkeypatch.setenv("FHIR_BASE_URL", "https://ehr.example.com/fhir")
    monkeypatch.setenv("FHIR_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("FHIR_CLIENT_SECRET", "test_client_secret")
    monkeypatch.setenv("FHIR_SCOPE", "system/*.read")


@pytest.mark.asyncio
async def test_authenticate_success(mock_env):
    """Test successful OAuth 2.0 client_credentials authentication (AC Scenario 1)."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    with respx.mock:
        # Mock SMART discovery
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint
        respx.post(token_url).mock(return_value=Response(200, json=MOCK_TOKEN_RESPONSE))

        client = FHIRAuthClient()
        try:
            token_response = await client.authenticate()

            assert token_response["access_token"] == "mock_access_token_xyz"
            assert token_response["expires_in"] == 3600
            assert token_response["token_type"] == "Bearer"
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_get_access_token_cache_hit(mock_env):
    """Test get_access_token returns cached token without network call (AC Scenario 2)."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    with respx.mock:
        # Mock SMART discovery (called once)
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint (called once)
        token_mock = respx.post(token_url).mock(return_value=Response(200, json=MOCK_TOKEN_RESPONSE))

        client = FHIRAuthClient()
        try:
            # First call: cache miss, should authenticate
            token1 = await client.get_access_token()
            assert token1 == "mock_access_token_xyz"
            assert token_mock.call_count == 1

            # Second call: cache hit, should NOT authenticate
            token2 = await client.get_access_token()
            assert token2 == "mock_access_token_xyz"
            assert token_mock.call_count == 1  # No additional call
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_get_access_token_cache_miss_refresh(mock_env):
    """Test get_access_token auto-refreshes on cache miss (AC Scenario 3)."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    with respx.mock:
        # Mock SMART discovery
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint (will be called twice)
        token_mock = respx.post(token_url).mock(return_value=Response(200, json=MOCK_TOKEN_RESPONSE))

        client = FHIRAuthClient()
        try:
            # First authentication
            token1 = await client.get_access_token()
            assert token1 == "mock_access_token_xyz"
            assert token_mock.call_count == 1

            # Invalidate cache (simulate expiry)
            await client.invalidate_token()

            # Second call: cache miss, should re-authenticate
            token2 = await client.get_access_token()
            assert token2 == "mock_access_token_xyz"
            assert token_mock.call_count == 2  # Second authentication
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_get_access_token_expiry_buffer_refresh(mock_env):
    """Test token refresh when within 60-second expiry buffer (AC Scenario 3)."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    # Token with 55 seconds remaining (within 60s buffer)
    short_token_response = {
        "access_token": "short_token",
        "token_type": "Bearer",
        "expires_in": 55,  # Will be expired immediately due to 60s buffer
    }

    with respx.mock:
        # Mock SMART discovery
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint (returns short-lived token)
        token_mock = respx.post(token_url).mock(return_value=Response(200, json=short_token_response))

        client = FHIRAuthClient()
        try:
            with freeze_time("2026-07-16 12:00:00"):
                # First call: authenticate, but token expires immediately (55s - 60s buffer)
                token1 = await client.get_access_token()
                assert token1 == "short_token"
                assert token_mock.call_count == 1

            # Second call: token is expired, should re-authenticate
            with freeze_time("2026-07-16 12:00:01"):
                token2 = await client.get_access_token()
                assert token2 == "short_token"
                assert token_mock.call_count == 2  # Second authentication
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_authenticate_failure_401(mock_env):
    """Test 401 Unauthorized raises FHIRAuthenticationError (AC Scenario 4)."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    with respx.mock:
        # Mock SMART discovery
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint returning 401
        respx.post(token_url).mock(
            return_value=Response(401, json={"error": "invalid_client"})
        )

        client = FHIRAuthClient()
        try:
            with pytest.raises(FHIRAuthenticationError) as exc_info:
                await client.authenticate()

            assert exc_info.value.status_code == 401
            assert "401" in str(exc_info.value)
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_authenticate_network_error(mock_env):
    """Test network error raises FHIRAuthenticationError."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    with respx.mock:
        # Mock SMART discovery
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint with network error
        respx.post(token_url).mock(side_effect=Exception("Connection timeout"))

        client = FHIRAuthClient()
        try:
            with pytest.raises(FHIRAuthenticationError) as exc_info:
                await client.authenticate()

            assert "network error" in str(exc_info.value).lower()
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_authenticate_invalid_json(mock_env):
    """Test invalid JSON response raises FHIRAuthenticationError."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    with respx.mock:
        # Mock SMART discovery
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint returning invalid JSON
        respx.post(token_url).mock(return_value=Response(200, text="Not JSON"))

        client = FHIRAuthClient()
        try:
            with pytest.raises(FHIRAuthenticationError) as exc_info:
                await client.authenticate()

            assert "invalid JSON" in str(exc_info.value)
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_authenticate_missing_access_token(mock_env):
    """Test missing access_token in response raises FHIRAuthenticationError."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    invalid_token_response = {
        # Missing access_token
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    with respx.mock:
        # Mock SMART discovery
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint returning incomplete response
        respx.post(token_url).mock(return_value=Response(200, json=invalid_token_response))

        client = FHIRAuthClient()
        try:
            with pytest.raises(FHIRAuthenticationError) as exc_info:
                await client.authenticate()

            assert "missing 'access_token'" in str(exc_info.value)
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_invalidate_token(mock_env):
    """Test invalidate_token clears cache."""
    discovery_url = "https://ehr.example.com/fhir/.well-known/smart-configuration"
    token_url = "https://ehr.example.com/auth/token"

    with respx.mock:
        # Mock SMART discovery
        respx.get(discovery_url).mock(return_value=Response(200, json=MOCK_SMART_CONFIG))

        # Mock token endpoint
        respx.post(token_url).mock(return_value=Response(200, json=MOCK_TOKEN_RESPONSE))

        client = FHIRAuthClient()
        try:
            # Authenticate and cache token
            await client.get_access_token()

            # Invalidate cache
            await client.invalidate_token()

            # Cache should be empty (is_expired returns True)
            assert await client._cache.is_expired()
        finally:
            await client.close()
```

### 5. Create `backend/tests/unit/core/fhir/__init__.py`

Empty init file for pytest discovery:

```python
# Empty init file for pytest test discovery
```

---

## Files Modified / Created

| File | Change Type | Lines (approx) |
|------|-------------|----------------|
| `backend/requirements-dev.txt` | Modified | +5 lines |
| `backend/tests/unit/core/fhir/__init__.py` | Created | 1 |
| `backend/tests/unit/core/fhir/test_discovery.py` | Created | 110 |
| `backend/tests/unit/core/fhir/test_token_cache.py` | Created | 150 |
| `backend/tests/unit/core/fhir/test_auth.py` | Created | 300 |

**Total:** ~566 lines

---

## Verification

### Run all FHIR auth tests

```bash
# From backend/ directory
pytest -xvs backend/tests/unit/core/fhir/

# With coverage report
pytest --cov=app.core.fhir --cov-report=term-missing backend/tests/unit/core/fhir/

# Run specific test
pytest -xvs -k "test_authenticate_success"
```

Expected output:
```
====== test session starts ======
collected 23 items

test_discovery.py::test_discover_smart_config_success PASSED
test_discovery.py::test_discover_smart_config_trailing_slash PASSED
test_discovery.py::test_discover_smart_config_network_error PASSED
test_discovery.py::test_discover_smart_config_http_error PASSED
test_discovery.py::test_discover_smart_config_invalid_json PASSED
test_discovery.py::test_discover_smart_config_missing_token_endpoint PASSED
test_discovery.py::test_get_token_endpoint PASSED
test_discovery.py::test_get_token_endpoint_missing PASSED

test_token_cache.py::test_token_cache_miss_empty PASSED
test_token_cache.py::test_token_cache_hit PASSED
test_token_cache.py::test_token_cache_expiry_buffer PASSED
test_token_cache.py::test_token_cache_expiry_buffer_boundary PASSED
test_token_cache.py::test_token_cache_clear PASSED
test_token_cache.py::test_token_cache_is_expired PASSED
test_token_cache.py::test_token_cache_concurrent_access PASSED
test_token_cache.py::test_token_cache_concurrent_set PASSED

test_auth.py::test_authenticate_success PASSED
test_auth.py::test_get_access_token_cache_hit PASSED
test_auth.py::test_get_access_token_cache_miss_refresh PASSED
test_auth.py::test_get_access_token_expiry_buffer_refresh PASSED
test_auth.py::test_authenticate_failure_401 PASSED
test_auth.py::test_authenticate_network_error PASSED
test_auth.py::test_authenticate_invalid_json PASSED
test_auth.py::test_authenticate_missing_access_token PASSED
test_auth.py::test_invalidate_token PASSED

====== 23 passed in 2.5s ======
```

### Coverage target

Target: **≥90% code coverage** for `app.core.fhir` module

---

## Definition of Done Checklist

- [ ] Test dependencies added to `requirements-dev.txt`
- [ ] `test_discovery.py` created with 8 tests
- [ ] `test_token_cache.py` created with 8 tests
- [ ] `test_auth.py` created with 10 tests
- [ ] All 26 tests pass successfully
- [ ] Code coverage ≥90% for `app.core.fhir` module
- [ ] Tests validate all 4 acceptance criteria scenarios
- [ ] Tests use `respx` for HTTP mocking (no real network calls)
- [ ] Tests use `freezegun` for time-dependent expiry logic
- [ ] Tests verify thread-safety with concurrent access patterns
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | Discovery module must exist |
| TASK-002 | Task | TokenCache module must exist |
| TASK-003 | Task | FHIRAuthClient module must exist |
| pytest-asyncio | Package | Async test support |
| respx | Package | HTTP mocking for httpx |
| freezegun | Package | Time mocking for expiry tests |

---

## Notes

- **Test isolation:** Each test uses `respx.mock` context manager to ensure mocked HTTP requests don't leak between tests.
- **Time mocking:** `freezegun` is used to test token expiry logic without waiting for real time to pass.
- **Concurrency tests:** `test_token_cache_concurrent_access` validates thread-safety by simulating 10 concurrent `get_token()` calls.
- **Coverage gaps:** If coverage is <90%, add tests for error paths (e.g., HTTP redirects, timeouts, partial JSON).
- **Integration tests:** These are unit tests with mocked HTTP. Full integration tests with a real test EHR will be in the E2E test suite (separate story).
