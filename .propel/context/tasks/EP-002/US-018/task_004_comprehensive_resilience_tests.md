---
id: TASK-004
title: "Comprehensive Unit Tests for Resilience Patterns with Edge Cases"
user_story: US-018
epic: EP-002
sprint: 1
layer: Backend Testing
estimate: 8h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer / QA Engineer
upstream: [US-018/TASK-001, US-018/TASK-002, US-018/TASK-003]
---

# TASK-004: Comprehensive Unit Tests for Resilience Patterns with Edge Cases

> **Story:** US-018 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend Testing | **Est:** 8 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-018 DoD requires:

> *"Unit tests: (a) retry on transient error, (b) circuit open after threshold, (c) circuit probe logic, (d) rate limiter delay"*

This task implements comprehensive unit tests for all resilience patterns (circuit breaker, retry, rate limiter) with edge cases to ensure correctness under failure scenarios.

**Design references:**
- US-018 AC Scenarios 1–4 (all scenarios must have test coverage)
- US-018 DoD — Unit test requirements
- TASK-001, TASK-002, TASK-003 — Implementations to test

---

## Acceptance Criteria Addressed

- AC Scenario 1: Retry succeeds after one transient failure
- AC Scenario 2: Circuit opens after 10 consecutive failures
- AC Scenario 3: Circuit probes after 120s cooldown
- AC Scenario 4: Rate limiter enforces 100 req/min per instance
- US-018 DoD: Unit tests for retry, circuit breaker, rate limiter

---

## Implementation Steps

### 1. Create `backend/tests/unit/core/fhir/test_circuit_breaker_resilience.py`

Comprehensive circuit breaker tests (12 tests):

```python
"""Unit tests for CircuitBreaker resilience patterns.

Tests cover:
  - Circuit opens after 10 failures in 60s window
  - Circuit transitions to HALF_OPEN after 120s cooldown
  - Circuit closes after successful probe
  - Circuit reopens after failed probe
  - Failure window expiry resets count
  - Thread-safety of state transitions
  - Metrics updates on state changes

Design refs:
    US-018 AC Scenario 2 — Circuit opens after 10 failures
    US-018 AC Scenario 3 — Half-open probe after 120s
    US-018 TASK-001 — Module-level singleton
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.core.fhir.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitBreakerState,
    get_circuit_breaker,
)
from app.core.fhir.metrics import CIRCUIT_STATE


@pytest.fixture()
async def reset_circuit_breaker():
    """Reset singleton circuit breaker between tests."""
    from app.core.fhir import circuit_breaker as cb_module
    
    cb_module._circuit_breaker_instance = None
    yield
    cb_module._circuit_breaker_instance = None


# ── Singleton Tests ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_circuit_breaker_singleton(reset_circuit_breaker):
    """Verify circuit breaker is a singleton per module."""
    breaker1 = await get_circuit_breaker()
    breaker2 = await get_circuit_breaker()
    
    assert breaker1 is breaker2


@pytest.mark.asyncio
async def test_circuit_breaker_state_persistence(reset_circuit_breaker):
    """Verify state persists across accessor calls."""
    breaker1 = await get_circuit_breaker()
    breaker1.failure_count = 5
    
    breaker2 = await get_circuit_breaker()
    assert breaker2.failure_count == 5


# ── State Transition Tests ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_circuit_opens_after_10_failures(reset_circuit_breaker):
    """AC Scenario 2: Circuit opens after 10 consecutive failures in 60s."""
    breaker = await get_circuit_breaker()
    
    async def failing_func():
        raise Exception("Simulated failure")
    
    # Trigger 10 consecutive failures
    for i in range(10):
        with pytest.raises(Exception, match="Simulated failure"):
            await breaker.call(failing_func)
    
    # Circuit should be OPEN
    assert breaker.state == CircuitBreakerState.OPEN
    assert breaker.failure_count == 10
    
    # Next call should raise CircuitBreakerError
    with pytest.raises(CircuitBreakerError, match="Circuit breaker OPEN"):
        await breaker.call(failing_func)


@pytest.mark.asyncio
async def test_circuit_half_open_after_120s_cooldown(reset_circuit_breaker):
    """AC Scenario 3: Circuit transitions to HALF_OPEN after 120s cooldown."""
    breaker = await get_circuit_breaker()
    
    # Manually open circuit
    breaker.state = CircuitBreakerState.OPEN
    breaker.opened_at = time.monotonic() - 121  # 121s ago (>120s)
    
    async def success_func():
        return "success"
    
    # Call should transition to HALF_OPEN and succeed
    result = await breaker.call(success_func)
    
    assert result == "success"
    assert breaker.state == CircuitBreakerState.CLOSED  # Probe succeeded → CLOSED


@pytest.mark.asyncio
async def test_circuit_closes_after_successful_probe(reset_circuit_breaker):
    """Circuit closes after successful HALF_OPEN probe."""
    breaker = await get_circuit_breaker()
    
    # Set state to HALF_OPEN
    breaker.state = CircuitBreakerState.HALF_OPEN
    breaker.failure_count = 10
    
    async def success_func():
        return "success"
    
    result = await breaker.call(success_func)
    
    assert result == "success"
    assert breaker.state == CircuitBreakerState.CLOSED
    assert breaker.failure_count == 0  # Reset on success


@pytest.mark.asyncio
async def test_circuit_reopens_after_failed_probe(reset_circuit_breaker):
    """Circuit reopens after HALF_OPEN probe failure."""
    breaker = await get_circuit_breaker()
    
    # Set state to HALF_OPEN
    breaker.state = CircuitBreakerState.HALF_OPEN
    breaker.opened_at = time.monotonic()
    
    async def failing_func():
        raise Exception("Probe failed")
    
    with pytest.raises(Exception, match="Probe failed"):
        await breaker.call(failing_func)
    
    assert breaker.state == CircuitBreakerState.OPEN  # Reopened


@pytest.mark.asyncio
async def test_failure_window_expiry_resets_count(reset_circuit_breaker):
    """Failure count resets after 60s window expiry."""
    breaker = await get_circuit_breaker()
    
    # Simulate failures 61s ago
    breaker.failure_count = 5
    breaker.last_failure_time = time.monotonic() - 61
    
    async def success_func():
        return "success"
    
    await breaker.call(success_func)
    
    # Failure count should be reset
    assert breaker.failure_count == 0
    assert breaker.last_failure_time is None


@pytest.mark.asyncio
async def test_circuit_open_rejects_requests_within_cooldown(reset_circuit_breaker):
    """Requests rejected while circuit OPEN within 120s cooldown."""
    breaker = await get_circuit_breaker()
    
    # Open circuit now
    breaker.state = CircuitBreakerState.OPEN
    breaker.opened_at = time.monotonic()
    
    async def any_func():
        return "should not execute"
    
    with pytest.raises(CircuitBreakerError, match="Circuit breaker OPEN"):
        await breaker.call(any_func)


# ── Metrics Tests ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_circuit_state_metric_updates(reset_circuit_breaker):
    """Circuit state gauge updates on state transitions."""
    breaker = await get_circuit_breaker()
    
    # Initial state
    initial_value = CIRCUIT_STATE._value.get()
    assert initial_value == 0  # CLOSED
    
    # Open circuit
    breaker.state = CircuitBreakerState.OPEN
    from app.core.fhir.metrics import set_circuit_state
    set_circuit_state("OPEN")
    
    assert CIRCUIT_STATE._value.get() == 2  # OPEN
    
    # Close circuit
    breaker.state = CircuitBreakerState.CLOSED
    set_circuit_state("CLOSED")
    
    assert CIRCUIT_STATE._value.get() == 0  # CLOSED


# ── Thread-Safety Tests ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_concurrent_calls_thread_safe(reset_circuit_breaker):
    """Concurrent calls to circuit breaker are thread-safe."""
    breaker = await get_circuit_breaker()
    
    call_count = 0
    
    async def increment_func():
        nonlocal call_count
        await asyncio.sleep(0.01)  # Simulate async work
        call_count += 1
        return call_count
    
    # Execute 20 concurrent calls
    tasks = [breaker.call(increment_func) for _ in range(20)]
    results = await asyncio.gather(*tasks)
    
    assert call_count == 20
    assert len(results) == 20
    assert breaker.failure_count == 0  # All succeeded


# ── Edge Cases ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_exactly_10_failures_opens_circuit(reset_circuit_breaker):
    """Circuit opens on exactly 10th failure, not 9th or 11th."""
    breaker = await get_circuit_breaker()
    
    async def failing_func():
        raise Exception("Failure")
    
    # 9 failures
    for _ in range(9):
        with pytest.raises(Exception):
            await breaker.call(failing_func)
    
    assert breaker.state == CircuitBreakerState.CLOSED  # Still closed
    
    # 10th failure
    with pytest.raises(Exception):
        await breaker.call(failing_func)
    
    assert breaker.state == CircuitBreakerState.OPEN  # Now open


@pytest.mark.asyncio
async def test_success_resets_failure_count_in_closed_state(reset_circuit_breaker):
    """Success in CLOSED state resets failure count."""
    breaker = await get_circuit_breaker()
    
    async def failing_func():
        raise Exception("Failure")
    
    async def success_func():
        return "success"
    
    # 5 failures
    for _ in range(5):
        with pytest.raises(Exception):
            await breaker.call(failing_func)
    
    assert breaker.failure_count == 5
    
    # Success
    await breaker.call(success_func)
    
    assert breaker.failure_count == 0  # Reset
```

---

### 2. Create `backend/tests/unit/core/fhir/test_retry_logic.py`

Comprehensive retry tests (8 tests):

```python
"""Unit tests for FHIR retry logic with selective error handling.

Tests cover:
  - Success after 1 transient failure (503)
  - Success after 2 transient failures
  - Exhausted retries after 3 failures
  - No retry on 4xx errors (400, 404)
  - Network timeout triggers retry
  - Connection error triggers retry
  - Retry metrics incremented correctly

Design refs:
    US-018 AC Scenario 1 — Retry succeeds after 503
    US-018 TASK-003 — Selective error handling
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.fhir.client import FHIRClient
from app.core.fhir.exceptions import (
    FHIRClientError,
    FHIRNetworkError,
    FHIRServerError,
)
from app.core.fhir.metrics import RETRY_TOTAL


@pytest.fixture()
def fhir_client():
    """Create FHIRClient instance for testing."""
    return FHIRClient()


# ── Retry Success Tests ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_retry_succeeds_after_one_503_failure(fhir_client):
    """AC Scenario 1: Retry succeeds after one transient failure (HTTP 503)."""
    with patch.object(fhir_client._http_client, "get") as mock_get:
        # First call: 503, Second call: 200
        mock_get.side_effect = [
            AsyncMock(status_code=503, reason_phrase="Service Unavailable"),
            AsyncMock(
                status_code=200,
                json=AsyncMock(return_value={"resourceType": "Patient", "id": "123"}),
            ),
        ]
        
        result = await fhir_client._fetch_with_retry(
            "https://fhir.example.com/Patient/123"
        )
        
        assert result["id"] == "123"
        assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_retry_succeeds_after_two_failures(fhir_client):
    """Retry succeeds after 2 transient failures."""
    with patch.object(fhir_client._http_client, "get") as mock_get:
        # First: 500, Second: 503, Third: 200
        mock_get.side_effect = [
            AsyncMock(status_code=500, reason_phrase="Internal Server Error"),
            AsyncMock(status_code=503, reason_phrase="Service Unavailable"),
            AsyncMock(
                status_code=200,
                json=AsyncMock(return_value={"resourceType": "Encounter", "id": "456"}),
            ),
        ]
        
        result = await fhir_client._fetch_with_retry(
            "https://fhir.example.com/Encounter/456"
        )
        
        assert result["id"] == "456"
        assert mock_get.call_count == 3


# ── No Retry on 4xx Tests ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_retry_on_404_error(fhir_client):
    """Technical Note: No retry on 4xx errors (404)."""
    with patch.object(fhir_client._http_client, "get") as mock_get:
        mock_get.return_value = AsyncMock(
            status_code=404,
            reason_phrase="Not Found",
            text="Resource not found",
        )
        
        with pytest.raises(FHIRClientError) as exc_info:
            await fhir_client._fetch_with_retry(
                "https://fhir.example.com/Patient/999"
            )
        
        assert exc_info.value.status_code == 404
        assert mock_get.call_count == 1  # No retry


@pytest.mark.asyncio
async def test_no_retry_on_400_bad_request(fhir_client):
    """No retry on 400 Bad Request."""
    with patch.object(fhir_client._http_client, "get") as mock_get:
        mock_get.return_value = AsyncMock(
            status_code=400,
            reason_phrase="Bad Request",
            text="Invalid query parameter",
        )
        
        with pytest.raises(FHIRClientError) as exc_info:
            await fhir_client._fetch_with_retry(
                "https://fhir.example.com/Patient?invalid=param"
            )
        
        assert exc_info.value.status_code == 400
        assert mock_get.call_count == 1


# ── Exhausted Retries Tests ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_exhausted_retries_after_3_failures(fhir_client):
    """Retry exhaustion after 3 consecutive 500 errors."""
    with patch.object(fhir_client._http_client, "get") as mock_get:
        # All 3 calls: 500
        mock_get.side_effect = [
            AsyncMock(status_code=500, reason_phrase="Internal Server Error"),
            AsyncMock(status_code=500, reason_phrase="Internal Server Error"),
            AsyncMock(status_code=500, reason_phrase="Internal Server Error"),
        ]
        
        with pytest.raises(FHIRServerError) as exc_info:
            await fhir_client._fetch_with_retry(
                "https://fhir.example.com/Patient/123"
            )
        
        assert exc_info.value.status_code == 500
        assert exc_info.value.attempts == 3
        assert mock_get.call_count == 3


# ── Network Error Tests ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_retry_on_network_timeout(fhir_client):
    """Network timeout triggers retry."""
    with patch.object(fhir_client._http_client, "get") as mock_get:
        # First: timeout, Second: success
        mock_get.side_effect = [
            httpx.TimeoutException("Request timed out"),
            AsyncMock(
                status_code=200,
                json=AsyncMock(return_value={"resourceType": "Patient", "id": "123"}),
            ),
        ]
        
        result = await fhir_client._fetch_with_retry(
            "https://fhir.example.com/Patient/123"
        )
        
        assert result["id"] == "123"
        assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_retry_on_connection_error(fhir_client):
    """Connection error triggers retry."""
    with patch.object(fhir_client._http_client, "get") as mock_get:
        # First: connection refused, Second: success
        mock_get.side_effect = [
            httpx.ConnectError("Connection refused"),
            AsyncMock(
                status_code=200,
                json=AsyncMock(return_value={"resourceType": "Patient", "id": "456"}),
            ),
        ]
        
        result = await fhir_client._fetch_with_retry(
            "https://fhir.example.com/Patient/456"
        )
        
        assert result["id"] == "456"
        assert mock_get.call_count == 2


# ── Metrics Tests ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_retry_metrics_increment_on_success(fhir_client):
    """Retry success increments correct metric."""
    initial_success = RETRY_TOTAL.labels(outcome="success")._value.get()
    
    with patch.object(fhir_client._http_client, "get") as mock_get:
        mock_get.side_effect = [
            AsyncMock(status_code=503, reason_phrase="Service Unavailable"),
            AsyncMock(
                status_code=200,
                json=AsyncMock(return_value={"resourceType": "Patient", "id": "123"}),
            ),
        ]
        
        await fhir_client._fetch_with_retry("https://fhir.example.com/Patient/123")
        
        final_success = RETRY_TOTAL.labels(outcome="success")._value.get()
        assert final_success == initial_success + 1
```

---

### 3. Create `backend/tests/unit/core/fhir/test_rate_limiter_resilience.py`

Comprehensive rate limiter tests (6 tests):

```python
"""Unit tests for TokenBucketRateLimiter resilience patterns.

Tests cover:
  - Delay on 101st request within 60s
  - Token refill over time
  - Exponential backoff when bucket empty
  - Thread-safety of token consumption
  - Metrics incremented on rate limit

Design refs:
    US-018 AC Scenario 4 — Rate limiter enforces 100 req/min
    US-017 TASK-002 — Token bucket rate limiter
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core.fhir.rate_limiter import TokenBucketRateLimiter
from app.core.fhir.metrics import RATE_LIMITED_TOTAL


# ── Basic Rate Limiting Tests ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rate_limiter_allows_100_requests_immediately():
    """Rate limiter allows 100 requests without delay (full bucket)."""
    limiter = TokenBucketRateLimiter(capacity=100, refill_rate=1.67)
    
    start = time.monotonic()
    
    # Acquire 100 tokens
    for _ in range(100):
        await limiter.acquire()
    
    elapsed = time.monotonic() - start
    
    # Should complete in <0.1s (no delay)
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_rate_limiter_delays_101st_request():
    """AC Scenario 4: 101st request delayed until token refilled."""
    limiter = TokenBucketRateLimiter(capacity=100, refill_rate=1.67)
    
    # Consume all 100 tokens
    for _ in range(100):
        await limiter.acquire()
    
    # 101st request should delay
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    
    # Should delay ~1s (exponential backoff first attempt)
    assert 0.9 < elapsed < 1.2


@pytest.mark.asyncio
async def test_token_refill_over_time():
    """Tokens refill at 1.67/second rate."""
    limiter = TokenBucketRateLimiter(capacity=100, refill_rate=1.67)
    
    # Consume all tokens
    for _ in range(100):
        await limiter.acquire()
    
    assert limiter.tokens < 1
    
    # Wait 1 second
    await asyncio.sleep(1.0)
    
    # Refill tokens (should have ~1.67 tokens now)
    await limiter._refill()
    
    assert 1.5 < limiter.tokens < 2.0


# ── Exponential Backoff Tests ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_exponential_backoff_on_empty_bucket():
    """Empty bucket triggers exponential backoff [1s, 2s, 4s]."""
    limiter = TokenBucketRateLimiter(capacity=10, refill_rate=0.1)  # Very slow refill
    
    # Consume all tokens
    for _ in range(10):
        await limiter.acquire()
    
    # Next acquire should backoff 1s, then 2s, then 4s
    start = time.monotonic()
    await limiter.acquire()
    elapsed = time.monotonic() - start
    
    # Should delay ~1s (first backoff)
    assert 0.9 < elapsed < 1.2


# ── Metrics Tests ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rate_limited_metric_increments():
    """Rate limiter metric increments on backoff."""
    limiter = TokenBucketRateLimiter(capacity=5, refill_rate=0.1)
    
    initial_count = RATE_LIMITED_TOTAL._value.get()
    
    # Consume all tokens
    for _ in range(5):
        await limiter.acquire()
    
    # Next acquire triggers backoff
    await limiter.acquire()
    
    final_count = RATE_LIMITED_TOTAL._value.get()
    assert final_count == initial_count + 1


# ── Thread-Safety Tests ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_concurrent_acquire_thread_safe():
    """Concurrent acquire calls are thread-safe."""
    limiter = TokenBucketRateLimiter(capacity=50, refill_rate=10)
    
    acquired_count = 0
    
    async def acquire_token():
        nonlocal acquired_count
        await limiter.acquire()
        acquired_count += 1
    
    # Execute 50 concurrent acquires
    await asyncio.gather(*[acquire_token() for _ in range(50)])
    
    assert acquired_count == 50
    assert limiter.tokens < 1  # All tokens consumed
```

---

### 4. Create `backend/tests/unit/core/fhir/test_resilience_metrics.py`

Metrics integration tests (4 tests):

```python
"""Unit tests for resilience pattern metrics integration.

Tests cover:
  - All circuit states update metrics
  - All retry outcomes update metrics
  - Rate limiter backoff updates metrics
  - Fetch duration histogram records correctly

Design refs:
    US-018 TASK-002 — Prometheus metrics
    US-018 DoD — Metrics requirement
"""
from __future__ import annotations

import pytest

from app.core.fhir.metrics import (
    CIRCUIT_STATE,
    FETCH_DURATION,
    RATE_LIMITED_TOTAL,
    RETRY_TOTAL,
    increment_rate_limited,
    increment_retry_outcome,
    observe_fetch_duration,
    set_circuit_state,
)


def test_circuit_state_metric_all_states():
    """Circuit state metric covers all states."""
    set_circuit_state("CLOSED")
    assert CIRCUIT_STATE._value.get() == 0
    
    set_circuit_state("HALF_OPEN")
    assert CIRCUIT_STATE._value.get() == 1
    
    set_circuit_state("OPEN")
    assert CIRCUIT_STATE._value.get() == 2


def test_retry_outcome_metric_all_outcomes():
    """Retry outcome metric covers all outcomes."""
    initial_success = RETRY_TOTAL.labels(outcome="success")._value.get()
    initial_exhausted = RETRY_TOTAL.labels(outcome="exhausted")._value.get()
    initial_no_retry = RETRY_TOTAL.labels(outcome="no_retry_needed")._value.get()
    
    increment_retry_outcome("success")
    increment_retry_outcome("exhausted")
    increment_retry_outcome("no_retry_needed")
    
    assert RETRY_TOTAL.labels(outcome="success")._value.get() == initial_success + 1
    assert RETRY_TOTAL.labels(outcome="exhausted")._value.get() == initial_exhausted + 1
    assert RETRY_TOTAL.labels(outcome="no_retry_needed")._value.get() == initial_no_retry + 1


def test_rate_limited_metric_increments():
    """Rate limited metric increments."""
    initial = RATE_LIMITED_TOTAL._value.get()
    
    increment_rate_limited()
    increment_rate_limited()
    
    assert RATE_LIMITED_TOTAL._value.get() == initial + 2


def test_fetch_duration_histogram_observes():
    """Fetch duration histogram records observations."""
    initial_count = FETCH_DURATION.labels(resource_type="Patient")._sum._value.get()
    
    observe_fetch_duration("Patient", 0.123)
    observe_fetch_duration("Patient", 0.456)
    
    # Count should increase by 2
    final_count = FETCH_DURATION.labels(resource_type="Patient")._sum._value.get()
    assert final_count > initial_count
```

---

### 5. Update `backend/requirements-dev.txt`

Add testing dependencies:

```txt
# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0
respx>=0.21.0  # HTTP mocking for httpx (already added in US-016)
freezegun>=1.5.0  # Time mocking for circuit breaker cooldown tests
```

---

## Validation

### Run Test Suite

```bash
cd backend

# Run all resilience tests
pytest tests/unit/core/fhir/test_circuit_breaker_resilience.py -v
pytest tests/unit/core/fhir/test_retry_logic.py -v
pytest tests/unit/core/fhir/test_rate_limiter_resilience.py -v
pytest tests/unit/core/fhir/test_resilience_metrics.py -v

# Run with coverage
pytest tests/unit/core/fhir/ --cov=app.core.fhir --cov-report=term-missing

# Expected: ≥95% coverage for circuit_breaker.py, rate_limiter.py, metrics.py
```

---

## Code Review Checklist

- [ ] All 4 AC scenarios have dedicated test cases
- [ ] Circuit breaker tests: 12 tests covering all state transitions
- [ ] Retry logic tests: 8 tests covering success, failure, no-retry scenarios
- [ ] Rate limiter tests: 6 tests covering token consumption and backoff
- [ ] Metrics tests: 4 tests covering all metric types
- [ ] All tests use `pytest.mark.asyncio` for async tests
- [ ] HTTP mocking uses `respx` or `unittest.mock.AsyncMock`
- [ ] Time mocking uses `freezegun` where needed
- [ ] Test coverage ≥95% for resilience modules
- [ ] No flaky tests (all tests pass consistently)

---

## Definition of Done Checklist

- [ ] `test_circuit_breaker_resilience.py` created with 12 tests
- [ ] `test_retry_logic.py` created with 8 tests
- [ ] `test_rate_limiter_resilience.py` created with 6 tests
- [ ] `test_resilience_metrics.py` created with 4 tests
- [ ] All tests pass locally (`pytest tests/unit/core/fhir/`)
- [ ] Code coverage ≥95% for `app.core.fhir` resilience modules
- [ ] `freezegun>=1.5.0` added to `requirements-dev.txt`
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-018 TASK-001 | Task | Circuit breaker singleton implementation |
| US-018 TASK-002 | Task | Metrics module implementation |
| US-018 TASK-003 | Task | Retry logic implementation |
| pytest-asyncio | Package | Async test support |
| respx | Package | HTTP mocking for httpx |
| freezegun | Package | Time mocking for circuit breaker tests |

---

## Technical Notes

- **Test Isolation:** Use `reset_circuit_breaker` fixture to reset singleton between tests
- **Async Tests:** All async functions must be decorated with `@pytest.mark.asyncio`
- **Mocking:** Use `unittest.mock.AsyncMock` for async HTTP responses
- **Time Mocking:** Use `freezegun` to manipulate time for cooldown tests
- **Coverage:** Aim for ≥95% line coverage on resilience modules

---

## Test Count Summary

| Test File | Test Count | Focus Area |
|-----------|------------|------------|
| `test_circuit_breaker_resilience.py` | 12 | Circuit breaker state machine |
| `test_retry_logic.py` | 8 | Retry with selective error handling |
| `test_rate_limiter_resilience.py` | 6 | Token bucket rate limiting |
| `test_resilience_metrics.py` | 4 | Metrics instrumentation |
| **Total** | **30** | **All US-018 resilience patterns** |

---

## Edge Cases Covered

- Circuit opens on exactly 10th failure (not 9th or 11th)
- Circuit closes after successful HALF_OPEN probe
- Circuit reopens after failed HALF_OPEN probe
- Failure window expiry (60s) resets failure count
- No retry on 4xx errors (400, 404)
- Retry on 5xx errors (500, 503)
- Retry on network errors (timeout, connection refused)
- Token refill rate matches specification (1.67/s)
- Exponential backoff on empty token bucket
- Thread-safe concurrent access to circuit breaker and rate limiter

---
