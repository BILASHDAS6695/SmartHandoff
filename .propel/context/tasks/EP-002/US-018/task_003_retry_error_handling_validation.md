---
id: TASK-003
title: "Validate and Enhance Retry Logic with Selective Error Handling"
user_story: US-018
epic: EP-002
sprint: 1
layer: Backend
estimate: 6h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-017/TASK-002]
---

# TASK-003: Validate and Enhance Retry Logic with Selective Error Handling

> **Story:** US-018 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend | **Est:** 6 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-018 Technical Notes specify:

> *"Retry should NOT retry on 4xx responses (client errors) — only on 5xx, network timeouts, and connection errors"*

US-017 TASK-002 implemented basic retry logic in `FHIRClient._fetch_with_retry()`, but this task validates and enhances that logic to ensure:
1. **Selective retry:** Only transient errors (5xx, timeouts, connection failures) are retried
2. **No retry on 4xx:** Client errors (400, 404, 401) raise immediately without retry
3. **Exponential backoff:** Exactly 3 attempts with delays [1s, 2s, 4s]
4. **Structured logging:** Retry attempts and exhaustion logged with context

**Design references:**
- US-018 AC Scenario 1 — Retry succeeds after one transient failure (HTTP 503)
- US-018 Technical Notes — Selective retry logic
- AIR-011 — Exponential backoff retry (3 attempts: 1s/2s/4s)

---

## Acceptance Criteria Addressed

- AC Scenario 1: FHIR server returns HTTP 503 on first attempt; second attempt succeeds after 1s retry
- Technical Note: Retry should NOT retry on 4xx responses

---

## Implementation Steps

### 1. Add Custom Exceptions to `backend/app/core/fhir/exceptions.py`

Create exception hierarchy for FHIR client errors:

```python
"""FHIR client exceptions.

Design refs:
    US-016 — FHIRAuthenticationError (OAuth 2.0 failures)
    US-018 TASK-003 — FHIRClientError (4xx responses), FHIRServerError (5xx)
"""
from __future__ import annotations


class FHIRAuthenticationError(Exception):
    """Raised when FHIR OAuth 2.0 authentication fails.
    
    US-016: Raised on 401/403 from token endpoint or discovery failures.
    """
    pass


class FHIRClientError(Exception):
    """Raised when FHIR API returns 4xx client error (no retry).
    
    US-018: Indicates invalid request, resource not found, or auth failure.
    These errors are NOT retried as they won't succeed on subsequent attempts.
    
    Attributes:
        status_code: HTTP status code (400, 404, 403, etc.)
        url: FHIR endpoint URL that failed
        response_body: Response body (if available)
    """
    
    def __init__(
        self,
        message: str,
        status_code: int,
        url: str,
        response_body: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.response_body = response_body


class FHIRServerError(Exception):
    """Raised when FHIR API returns 5xx server error (retryable).
    
    US-018: Indicates transient server failure. Retry with exponential backoff.
    
    Attributes:
        status_code: HTTP status code (500, 503, etc.)
        url: FHIR endpoint URL that failed
        attempts: Number of retry attempts made
    """
    
    def __init__(
        self,
        message: str,
        status_code: int,
        url: str,
        attempts: int,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.attempts = attempts


class FHIRNetworkError(Exception):
    """Raised when FHIR API call fails due to network issues (retryable).
    
    US-018: Timeouts, connection refused, DNS failures. Retry with backoff.
    
    Attributes:
        url: FHIR endpoint URL that failed
        attempts: Number of retry attempts made
        original_error: Original httpx exception
    """
    
    def __init__(
        self,
        message: str,
        url: str,
        attempts: int,
        original_error: Exception,
    ):
        super().__init__(message)
        self.url = url
        self.attempts = attempts
        self.original_error = original_error
```

---

### 2. Enhance `_fetch_with_retry()` in `backend/app/core/fhir/client.py`

Replace existing retry logic with selective error handling:

```python
import time
from typing import Any

import httpx

from app.core.fhir.exceptions import (
    FHIRClientError,
    FHIRNetworkError,
    FHIRServerError,
)
from app.core.fhir.metrics import increment_retry_outcome, observe_fetch_duration

logger = logging.getLogger(__name__)


class FHIRClient:
    async def _fetch_with_retry(
        self, url: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Fetch FHIR resource with exponential backoff retry.

        Retry policy:
        - 3 attempts total with delays: [1s, 2s, 4s]
        - Retry on: 5xx status codes, network timeouts, connection errors
        - NO retry on: 4xx status codes (client errors)

        Args:
            url: FHIR resource URL (absolute)
            params: Query parameters (optional)

        Returns:
            Parsed JSON response body

        Raises:
            FHIRClientError: On 4xx status (no retry)
            FHIRServerError: On 5xx status after exhausted retries
            FHIRNetworkError: On network failure after exhausted retries
            CircuitBreakerError: If circuit breaker is open

        Design refs:
            US-018 AC Scenario 1 — Retry succeeds after 503
            US-018 Technical Notes — Selective retry (no 4xx retry)
            AIR-011 — Exponential backoff: [1s, 2s, 4s]
        """
        max_attempts = 3
        backoff_delays = [1.0, 2.0, 4.0]
        
        # Get OAuth token
        token = await self._auth_client.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        }
        
        last_exception: Exception | None = None
        
        for attempt in range(max_attempts):
            try:
                start_time = time.monotonic()
                
                # Make HTTP request
                response = await self._http_client.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=30.0,
                )
                
                # Record fetch duration
                duration = time.monotonic() - start_time
                resource_type = self._extract_resource_type(url)
                observe_fetch_duration(resource_type, duration)
                
                # ── Success (2xx/3xx) ────────────────────────────────────────
                if response.status_code < 400:
                    if attempt == 0:
                        increment_retry_outcome("no_retry_needed")
                    else:
                        increment_retry_outcome("success")
                        logger.info(
                            "FHIR fetch succeeded after retry",
                            extra={
                                "event": "fhir_retry_success",
                                "url": url,
                                "attempt": attempt + 1,
                                "status_code": response.status_code,
                            },
                        )
                    return response.json()
                
                # ── Client Error (4xx) — NO RETRY ─────────────────────────────
                elif 400 <= response.status_code < 500:
                    increment_retry_outcome("no_retry_needed")
                    logger.error(
                        "FHIR client error (no retry)",
                        extra={
                            "event": "fhir_client_error",
                            "url": url,
                            "status_code": response.status_code,
                            "response_body": response.text[:500],
                        },
                    )
                    raise FHIRClientError(
                        message=(
                            f"FHIR API client error: {response.status_code} "
                            f"{response.reason_phrase}"
                        ),
                        status_code=response.status_code,
                        url=url,
                        response_body=response.text,
                    )
                
                # ── Server Error (5xx) — RETRY ────────────────────────────────
                else:
                    last_exception = FHIRServerError(
                        message=(
                            f"FHIR API server error: {response.status_code} "
                            f"{response.reason_phrase}"
                        ),
                        status_code=response.status_code,
                        url=url,
                        attempts=attempt + 1,
                    )
                    
                    if attempt == max_attempts - 1:
                        # Exhausted retries
                        increment_retry_outcome("exhausted")
                        logger.error(
                            "FHIR fetch failed after exhausted retries",
                            extra={
                                "event": "fhir_retry_exhausted",
                                "url": url,
                                "attempts": max_attempts,
                                "status_code": response.status_code,
                            },
                        )
                        raise last_exception
                    
                    # Retry with backoff
                    delay = backoff_delays[attempt]
                    logger.warning(
                        "FHIR server error, retrying with backoff",
                        extra={
                            "event": "fhir_retry_attempt",
                            "url": url,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "status_code": response.status_code,
                            "backoff_seconds": delay,
                        },
                    )
                    await asyncio.sleep(delay)
            
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.NetworkError,
            ) as exc:
                # ── Network Error — RETRY ─────────────────────────────────────
                last_exception = FHIRNetworkError(
                    message=f"FHIR API network error: {type(exc).__name__}",
                    url=url,
                    attempts=attempt + 1,
                    original_error=exc,
                )
                
                if attempt == max_attempts - 1:
                    # Exhausted retries
                    increment_retry_outcome("exhausted")
                    logger.error(
                        "FHIR network error after exhausted retries",
                        extra={
                            "event": "fhir_retry_exhausted",
                            "url": url,
                            "attempts": max_attempts,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    raise last_exception from exc
                
                # Retry with backoff
                delay = backoff_delays[attempt]
                logger.warning(
                    "FHIR network error, retrying with backoff",
                    extra={
                        "event": "fhir_retry_attempt",
                        "url": url,
                        "attempt": attempt + 1,
                        "max_attempts": max_attempts,
                        "error_type": type(exc).__name__,
                        "backoff_seconds": delay,
                    },
                )
                await asyncio.sleep(delay)
        
        # Should never reach here (safety fallback)
        increment_retry_outcome("exhausted")
        raise last_exception or FHIRServerError(
            "FHIR fetch failed (unknown reason)", 500, url, max_attempts
        )
    
    @staticmethod
    def _extract_resource_type(url: str) -> str:
        """Extract FHIR resource type from URL for metrics.
        
        Examples:
            https://ehr.example.com/fhir/Patient/123 → Patient
            https://ehr.example.com/fhir/Encounter?patient=123 → Encounter
        """
        parts = url.rstrip("/").split("/")
        for i, part in enumerate(parts):
            if part in {
                "Patient",
                "Encounter",
                "MedicationStatement",
                "MedicationAdministration",
                "MedicationRequest",
                "AllergyIntolerance",
                "Condition",
            }:
                return part
        return "unknown"
```

---

### 3. Update `backend/app/core/fhir/__init__.py` Exports

Export new exceptions:

```python
from app.core.fhir.exceptions import (
    FHIRAuthenticationError,
    FHIRClientError,
    FHIRNetworkError,
    FHIRServerError,
)

__all__ = [
    # ... existing exports
    "FHIRClientError",
    "FHIRNetworkError",
    "FHIRServerError",
]
```

---

## Validation

### Unit Testing (TASK-004 will implement)

```python
# Preview of test cases (implemented in TASK-004)

async def test_retry_succeeds_after_503():
    """AC Scenario 1: Retry succeeds after one transient failure."""
    # Mock: First call returns 503, second call returns 200
    # Assert: Result is successful, retry metric incremented

async def test_no_retry_on_404():
    """Technical Note: No retry on 4xx errors."""
    # Mock: Call returns 404
    # Assert: FHIRClientError raised immediately, no retry attempts

async def test_exhausted_retries_on_500():
    """Retry exhaustion scenario."""
    # Mock: All 3 calls return 500
    # Assert: FHIRServerError raised after 3 attempts (1s+2s+4s delays)

async def test_network_timeout_retry():
    """Network timeout triggers retry."""
    # Mock: First call times out, second succeeds
    # Assert: Result successful after 1s backoff
```

### Manual Testing

```python
# Test script: test_retry_logic_manual.py
import asyncio
from unittest.mock import AsyncMock, patch

from app.core.fhir.client import FHIRClient
from app.core.fhir.exceptions import FHIRClientError, FHIRServerError

async def test_503_retry():
    """Test retry on HTTP 503."""
    client = FHIRClient()
    
    with patch.object(client._http_client, "get") as mock_get:
        # First call: 503, Second call: 200
        mock_get.side_effect = [
            AsyncMock(status_code=503, reason_phrase="Service Unavailable"),
            AsyncMock(
                status_code=200,
                json=AsyncMock(return_value={"resourceType": "Patient", "id": "123"}),
            ),
        ]
        
        result = await client._fetch_with_retry("https://fhir.example.com/Patient/123")
        
        assert result["id"] == "123"
        assert mock_get.call_count == 2
        print("✓ Retry on 503 succeeded")

async def test_404_no_retry():
    """Test NO retry on HTTP 404."""
    client = FHIRClient()
    
    with patch.object(client._http_client, "get") as mock_get:
        mock_get.return_value = AsyncMock(
            status_code=404,
            reason_phrase="Not Found",
            text="Resource not found",
        )
        
        try:
            await client._fetch_with_retry("https://fhir.example.com/Patient/999")
            assert False, "Should have raised FHIRClientError"
        except FHIRClientError as exc:
            assert exc.status_code == 404
            assert mock_get.call_count == 1  # No retry
            print("✓ No retry on 404 confirmed")

asyncio.run(test_503_retry())
asyncio.run(test_404_no_retry())
```

---

## Code Review Checklist

- [ ] Retry logic attempts exactly 3 times with delays [1s, 2s, 4s]
- [ ] 4xx status codes raise `FHIRClientError` immediately (no retry)
- [ ] 5xx status codes trigger retry with exponential backoff
- [ ] Network errors (timeout, connection failure) trigger retry
- [ ] Retry success logged at INFO level with attempt count
- [ ] Retry exhaustion logged at ERROR level
- [ ] Custom exceptions include structured attributes (status_code, url, attempts)
- [ ] Metrics incremented correctly for all retry outcomes
- [ ] No infinite retry loops (max 3 attempts enforced)
- [ ] OAuth token included in Authorization header

---

## Definition of Done Checklist

- [ ] `FHIRClientError`, `FHIRServerError`, `FHIRNetworkError` added to `exceptions.py`
- [ ] `_fetch_with_retry()` implements selective retry logic
- [ ] 4xx responses raise `FHIRClientError` without retry
- [ ] 5xx responses retry 3 times with [1s, 2s, 4s] backoff
- [ ] Network errors retry 3 times with [1s, 2s, 4s] backoff
- [ ] Retry attempts and exhaustion logged with structured extra fields
- [ ] Metrics incremented for all outcomes (success, exhausted, no_retry_needed)
- [ ] Manual validation confirms retry behavior
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-017 TASK-002 | Task | Provides base `_fetch_with_retry()` implementation |
| US-018 TASK-002 | Task | Metrics module must exist for instrumentation |

---

## Technical Notes

- **Why no 4xx retry?** Client errors (invalid request, auth failure) won't succeed on retry — retry wastes time and resources
- **Backoff timing:** [1s, 2s, 4s] matches US-018 AC exactly; total 7s max delay for 3 attempts
- **Thread safety:** Retry logic is per-call, no shared state (except singleton circuit breaker)
- **Logging:** Structured logging with `extra` dict enables log-based alerting in Cloud Monitoring

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Retry logic not applied to all fetch methods | All fetch methods call `_fetch_with_retry()` (validated in TASK-004) |
| Incorrect exception propagation | Comprehensive exception tests (TASK-004) |
| Retry on 4xx by mistake | Explicit status code range checks + unit tests |

---

## Retry Decision Tree Reference

```
HTTP Response
    ├─ 2xx/3xx → Success (no retry)
    │            ├─ attempt=0 → increment_retry_outcome("no_retry_needed")
    │            └─ attempt>0 → increment_retry_outcome("success")
    │
    ├─ 4xx → FHIRClientError (NO RETRY)
    │        └─ increment_retry_outcome("no_retry_needed")
    │
    └─ 5xx → Retry [1s, 2s, 4s]
             ├─ attempt<3 → sleep(backoff_delay), retry
             └─ attempt=3 → FHIRServerError, increment_retry_outcome("exhausted")

Network Error (Timeout, ConnectError)
    ├─ attempt<3 → sleep(backoff_delay), retry
    └─ attempt=3 → FHIRNetworkError, increment_retry_outcome("exhausted")
```

---
