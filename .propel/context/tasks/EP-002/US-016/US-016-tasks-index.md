# US-016 Implementation Tasks — SMART on FHIR OAuth 2.0 Client with Token Cache

> **Epic:** EP-002 — EHR / FHIR Integration | **Sprint:** 1 | **Story Points:** 5  
> **Status:** Draft | **Date:** 2026-07-16

---

## Task Breakdown Summary

| Task ID | Title | Layer | Effort | Dependencies |
|---------|-------|-------|--------|--------------|
| TASK-001 | Setup FHIR Auth Module Structure, Custom Exceptions, and SMART on FHIR Discovery Client | Backend | 8 h | US-005 |
| TASK-002 | Implement Thread-Safe TokenCache Dataclass with Expiry Buffer Logic | Backend | 8 h | TASK-001 |
| TASK-003 | Implement FHIRAuthClient with OAuth 2.0 Client Credentials Flow | Backend | 16 h | TASK-001, TASK-002, US-005 |
| TASK-004 | Write Comprehensive Unit Tests for FHIR Authentication | Backend Testing | 8 h | TASK-001, TASK-002, TASK-003 |

**Total:** 40 hours = 5 story points ✓

---

## Task Descriptions

### TASK-001: Setup FHIR Auth Module Structure, Custom Exceptions, and SMART on FHIR Discovery Client
**Effort:** 8 h | **File:** [task_001_fhir_auth_module_structure_discovery.md](task_001_fhir_auth_module_structure_discovery.md)

**Scope:**
- Create `backend/app/core/fhir/` module structure
- Implement `FHIRAuthenticationError` exception class
- Implement `discover_smart_config()` to fetch `.well-known/smart-configuration`
- Implement `get_token_endpoint()` helper function
- Logging at CRITICAL level for all failures (no PHI)

**Acceptance Criteria Addressed:**
- AC Scenario 1 (discovery for token endpoint)
- AC Scenario 4 (FHIRAuthenticationError exception)

**Files Created:**
- `backend/app/core/fhir/__init__.py`
- `backend/app/core/fhir/exceptions.py`
- `backend/app/core/fhir/discovery.py`

---

### TASK-002: Implement Thread-Safe TokenCache Dataclass with Expiry Buffer Logic
**Effort:** 8 h | **File:** [task_002_token_cache_thread_safe.md](task_002_token_cache_thread_safe.md)

**Scope:**
- Implement `TokenCacheEntry` dataclass with `access_token` and `expires_at`
- Implement `TokenCache` class with `asyncio.Lock` for thread-safety
- Implement `get_token()`, `set_token()`, `clear()`, `is_expired()` methods
- Apply 60-second expiry buffer in `set_token()`

**Acceptance Criteria Addressed:**
- AC Scenario 2 (cached token reused)
- AC Scenario 3 (token refreshed before 60s buffer)

**Files Created:**
- `backend/app/core/fhir/token_cache.py`

**Files Modified:**
- `backend/app/core/fhir/__init__.py` (exports)

---

### TASK-003: Implement FHIRAuthClient with OAuth 2.0 Client Credentials Flow
**Effort:** 16 h | **File:** [task_003_fhir_auth_client_oauth2_flow.md](task_003_fhir_auth_client_oauth2_flow.md)

**Scope:**
- Add FHIR credentials to `Settings` in `backend/app/core/config.py`
- Implement `FHIRAuthClient` class with `httpx.AsyncClient`
- Implement `authenticate()` for OAuth 2.0 client_credentials grant
- Implement `get_access_token()` with cache check and auto-refresh
- Implement `invalidate_token()` to clear cache
- Implement `close()` for resource cleanup
- Load credentials from environment (Secret Manager via US-005)

**Acceptance Criteria Addressed:**
- AC Scenario 1 (OAuth flow authenticates)
- AC Scenario 2 (cache hit, no network call)
- AC Scenario 3 (cache miss triggers refresh)
- AC Scenario 4 (401 raises FHIRAuthenticationError with logging)

**Files Created:**
- `backend/app/core/fhir/auth.py`

**Files Modified:**
- `backend/app/core/config.py` (FHIR credentials in Settings)
- `backend/app/core/fhir/__init__.py` (exports)
- `backend/requirements.txt` (httpx if needed)

---

### TASK-004: Write Comprehensive Unit Tests for FHIR Authentication
**Effort:** 8 h | **File:** [task_004_unit_tests_fhir_auth.md](task_004_unit_tests_fhir_auth.md)

**Scope:**
- Create test suite for SMART discovery (8 tests)
- Create test suite for TokenCache with time mocking (8 tests)
- Create test suite for FHIRAuthClient OAuth flow (10 tests)
- Mock HTTP requests with `respx` (no real network calls)
- Mock time with `freezegun` for expiry tests
- Validate thread-safety with concurrent access tests
- Achieve ≥90% code coverage for `app.core.fhir`

**Acceptance Criteria Addressed:**
- AC Scenario 1 (test successful auth)
- AC Scenario 2 (test cache hit)
- AC Scenario 3 (test cache miss refresh)
- AC Scenario 4 (test 401 raises exception)

**Files Created:**
- `backend/tests/unit/core/fhir/__init__.py`
- `backend/tests/unit/core/fhir/test_discovery.py`
- `backend/tests/unit/core/fhir/test_token_cache.py`
- `backend/tests/unit/core/fhir/test_auth.py`

**Files Modified:**
- `backend/requirements-dev.txt` (test dependencies)

---

## Acceptance Criteria Coverage Matrix

| AC Scenario | TASK-001 | TASK-002 | TASK-003 | TASK-004 |
|-------------|----------|----------|----------|----------|
| AC Scenario 1: Client credentials flow authenticates successfully | ✓ (discovery) | | ✓ | ✓ (test) |
| AC Scenario 2: Cached token reused without re-authentication | | ✓ | ✓ | ✓ (test) |
| AC Scenario 3: Token refreshed before expiry buffer | | ✓ | ✓ | ✓ (test) |
| AC Scenario 4: Authentication failure raises FHIRAuthenticationError | ✓ (exception) | | ✓ | ✓ (test) |

---

## Definition of Done Checklist

### US-016 Overall DoD

- [ ] `FHIRAuthClient` class implemented with `httpx.AsyncClient` for async requests (TASK-003)
- [ ] OAuth 2.0 `client_credentials` grant POST to SMART on FHIR token endpoint (TASK-003)
- [ ] In-memory token cache: `TokenCache` dataclass with `access_token` and `expires_at` fields (TASK-002)
- [ ] Token cache thread-safe via `asyncio.Lock` (prevents simultaneous refresh race) (TASK-002)
- [ ] Client credentials loaded from Secret Manager (not environment variables) (TASK-003)
- [ ] Unit tests: (a) successful auth with mock server, (b) cache hit, (c) cache miss triggers refresh, (d) 401 raises `FHIRAuthenticationError` (TASK-004)
- [ ] Code reviewed and approved (All tasks)

---

## Implementation Order

```
TASK-001 (Foundation: module structure, exceptions, discovery)
    ↓
TASK-002 (Token cache with expiry buffer logic)
    ↓
TASK-003 (FHIRAuthClient OAuth flow — integrates TASK-001 and TASK-002)
    ↓
TASK-004 (Comprehensive unit tests for all components)
```

---

## Technical Notes

### Module Structure
```
backend/app/core/fhir/
├── __init__.py          # Public exports
├── exceptions.py        # FHIRAuthenticationError
├── discovery.py         # SMART on FHIR .well-known discovery
├── token_cache.py       # Thread-safe token cache with expiry buffer
└── auth.py              # FHIRAuthClient OAuth 2.0 flow
```

### Test Structure
```
backend/tests/unit/core/fhir/
├── __init__.py
├── test_discovery.py    # 8 tests for SMART discovery
├── test_token_cache.py  # 8 tests for TokenCache
└── test_auth.py         # 10 tests for FHIRAuthClient
```

### Secret Manager Integration

FHIR credentials are loaded from environment variables (mounted by Cloud Run from Secret Manager per US-005):
- `FHIR_BASE_URL` → `fhir_base_url` secret
- `FHIR_CLIENT_ID` → `fhir_client_id` secret
- `FHIR_CLIENT_SECRET` → `fhir_client_secret` secret
- `FHIR_SCOPE` → default: `system/*.read`

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-005 | Story | Secret Manager infrastructure and FHIR secrets must exist |
| httpx | Package | Async HTTP client (already in tech stack) |
| pytest-asyncio | Package | Async test support |
| respx | Package | HTTP mocking for httpx tests |
| freezegun | Package | Time mocking for expiry tests |

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| EHR SMART discovery endpoint unreachable | Medium | High | Implement exponential backoff retry (deferred to US-017) |
| Token expiry mid-request | Low | High | 60-second expiry buffer ensures tokens refreshed before expiry |
| Race condition on concurrent token refresh | Medium | Medium | `asyncio.Lock` in TokenCache prevents simultaneous refresh |
| FHIR server rotates credentials | Low | High | `invalidate_token()` method allows manual cache clear; monitoring alerts on auth failures |

---

## Future Enhancements (Out of Scope for US-016)

- **Circuit breaker:** Implemented in US-017 (not part of OAuth client)
- **Exponential backoff retry:** Implemented in US-017 (not part of OAuth client)
- **Rate limiting:** Implemented in US-018 (not part of OAuth client)
- **Multiple EHR support:** Requires separate FHIRAuthClient instances per EHR (architecture decision)
- **Asymmetric JWT authentication:** SMART on FHIR v2.0 supports JWT-based client auth (future enhancement)

---

## Validation

### Manual End-to-End Test

After completing all tasks, validate the full OAuth flow:

```bash
# Set test credentials
export FHIR_BASE_URL="https://test-ehr.example.com/fhir"
export FHIR_CLIENT_ID="test_client"
export FHIR_CLIENT_SECRET="test_secret"

# Run Python test script
python -c "
import asyncio
from app.core.fhir.auth import FHIRAuthClient

async def test():
    client = FHIRAuthClient()
    try:
        # First call: cache miss, should authenticate
        token1 = await client.get_access_token()
        print(f'Token 1: {token1[:30]}...')
        
        # Second call: cache hit, no network call
        token2 = await client.get_access_token()
        assert token1 == token2
        print(f'Token 2 (cached): {token2[:30]}...')
        
        print('✓ OAuth flow validated successfully')
    finally:
        await client.close()

asyncio.run(test())
"
```

Expected output:
```
Token 1: eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
Token 2 (cached): eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
✓ OAuth flow validated successfully
```

---

## Questions for Product Owner

1. **EHR SMART configuration:** Do we have a test EHR endpoint with SMART on FHIR v2.0 support for integration testing?
2. **Token lifetime:** What is the expected token lifetime from the EHR (3600s standard, or custom)?
3. **Scope requirements:** Does the EHR require specific resource-level scopes (e.g., `system/Patient.read`) or is `system/*.read` acceptable?
4. **Credential rotation:** What is the expected credential rotation frequency (quarterly, annually)?

---

*Tasks generated on 2026-07-16 from US-016 acceptance criteria by plan-development-tasks workflow.*
