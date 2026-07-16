---
id: TASK-001
title: "Refactor Circuit Breaker to Module-Level Singleton with State Persistence"
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

# TASK-001: Refactor Circuit Breaker to Module-Level Singleton with State Persistence

> **Story:** US-018 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend | **Est:** 6 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-017 TASK-002 implemented a basic `CircuitBreaker` class that is instantiated per `FHIRClient` instance. However, US-018 Technical Notes specify:

> *"Circuit breaker state persisted in module-level singleton (per Cloud Run instance)"*

This task refactors the circuit breaker to use a **module-level singleton** so that all FHIR API calls within a single Cloud Run instance share the same circuit breaker state. This prevents cascading failures across multiple agent tasks within the same container.

**Design references:**
- US-018 AC Scenario 2 — Circuit opens after 10 failures in 60s
- US-018 AC Scenario 3 — Half-open probe after 120s cooldown
- US-018 Technical Notes — Module-level singleton per instance

---

## Acceptance Criteria Addressed

- AC Scenario 2: Circuit breaker opens after 10 consecutive failures within 60s
- AC Scenario 3: Circuit breaker transitions to HALF_OPEN after 120s, sends probe request
- Technical Note: Circuit breaker state persisted in module-level singleton

---

## Implementation Steps

### 1. Refactor `backend/app/core/fhir/circuit_breaker.py` to Module-Level Singleton

Replace the existing `CircuitBreaker` class with a singleton pattern:

```python
"""Circuit breaker pattern for FHIR API resilience (module-level singleton).

Design refs:
    US-018 AC Scenario 2 — Circuit opens after 10 failures in 60s
    US-018 AC Scenario 3 — Half-open probe after 120s
    US-018 Technical Notes — Module-level singleton per Cloud Run instance

The circuit breaker state is shared across all FHIRClient instances within
a single Cloud Run container. This prevents cascading failures when the EHR
is degraded.

Circuit breaker state machine:
    CLOSED ──(10 failures in 60s)──> OPEN
       ↑                                │
       │                                │ (120s cooldown)
       │                                ↓
       └──(probe succeeds)────── HALF_OPEN
                                        │
                    (probe fails) ──────┘
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Failing — reject requests
    HALF_OPEN = "HALF_OPEN"  # Probing — allow 1 test request


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""

    pass


class CircuitBreaker:
    """Circuit breaker for async functions (singleton per module).

    Tracks failure rate and opens circuit if threshold exceeded.
    State is shared across all FHIRClient instances in this Cloud Run container.

    Attributes:
        failure_threshold: Number of consecutive failures before opening (default: 10)
        timeout: Seconds to wait in OPEN state before HALF_OPEN probe (default: 120)
        window: Time window (seconds) for counting failures (default: 60)
    """

    def __init__(
        self,
        failure_threshold: int = 10,
        timeout: int = 120,
        window: int = 60,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Max consecutive failures before opening
            timeout: Cooldown period in OPEN state (seconds)
            window: Time window for counting failures (seconds)
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.window = window
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def _reset_if_window_expired(self) -> None:
        """Reset failure count if time window expired."""
        if self.last_failure_time:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed > self.window:
                logger.info(
                    "Circuit breaker failure window expired — resetting count",
                    extra={
                        "event": "circuit_breaker_window_reset",
                        "elapsed_seconds": elapsed,
                        "window_seconds": self.window,
                        "previous_failure_count": self.failure_count,
                    },
                )
                self.failure_count = 0
                self.last_failure_time = None

    async def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection.

        Args:
            func: Async function to call
            *args: Function positional arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result if circuit closed or half-open probe succeeds

        Raises:
            CircuitBreakerError: If circuit is open
            Original exception: If function call fails
        """
        async with self._lock:
            await self._reset_if_window_expired()

            # OPEN state — reject requests until timeout
            if self.state == CircuitBreakerState.OPEN:
                elapsed = time.monotonic() - self.opened_at
                if elapsed < self.timeout:
                    logger.warning(
                        "Circuit breaker OPEN — rejecting request",
                        extra={
                            "event": "circuit_breaker_reject",
                            "state": self.state.value,
                            "elapsed_seconds": round(elapsed, 2),
                            "cooldown_remaining": round(self.timeout - elapsed, 2),
                            "failure_count": self.failure_count,
                        },
                    )
                    raise CircuitBreakerError(
                        f"Circuit breaker OPEN. Retry in {self.timeout - elapsed:.0f}s"
                    )
                else:
                    # Timeout expired — transition to HALF_OPEN for probe
                    self.state = CircuitBreakerState.HALF_OPEN
                    logger.info(
                        "Circuit breaker transitioning to HALF_OPEN for probe",
                        extra={
                            "event": "circuit_breaker_half_open",
                            "cooldown_elapsed": round(elapsed, 2),
                        },
                    )

        # CLOSED or HALF_OPEN — attempt call
        try:
            result = await func(*args, **kwargs)

            # Success — reset failure count
            async with self._lock:
                if self.state == CircuitBreakerState.HALF_OPEN:
                    self.state = CircuitBreakerState.CLOSED
                    logger.info(
                        "Circuit breaker probe succeeded — CLOSING",
                        extra={
                            "event": "circuit_breaker_close",
                            "previous_failure_count": self.failure_count,
                        },
                    )
                self.failure_count = 0
                self.last_failure_time = None

            return result

        except Exception as exc:
            # Failure — increment count and possibly open circuit
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.monotonic()

                if self.state == CircuitBreakerState.HALF_OPEN:
                    # Probe failed — reopen circuit
                    self.state = CircuitBreakerState.OPEN
                    self.opened_at = time.monotonic()
                    logger.critical(
                        "Circuit breaker probe FAILED — REOPENING",
                        extra={
                            "event": "circuit_breaker_reopen",
                            "failure_count": self.failure_count,
                            "error": str(exc),
                        },
                    )
                elif self.failure_count >= self.failure_threshold:
                    # Threshold exceeded — open circuit
                    self.state = CircuitBreakerState.OPEN
                    self.opened_at = time.monotonic()
                    logger.critical(
                        "Circuit breaker OPENED due to failure threshold",
                        extra={
                            "event": "circuit_breaker_open",
                            "failure_count": self.failure_count,
                            "threshold": self.failure_threshold,
                            "error": str(exc),
                        },
                    )
                else:
                    logger.warning(
                        "Circuit breaker failure recorded",
                        extra={
                            "event": "circuit_breaker_failure",
                            "failure_count": self.failure_count,
                            "threshold": self.failure_threshold,
                            "state": self.state.value,
                            "error": str(exc),
                        },
                    )

            raise


# ── Module-level singleton instance ──────────────────────────────────────────
# Shared across all FHIRClient instances within this Cloud Run container.
_circuit_breaker_instance: CircuitBreaker | None = None
_instance_lock = asyncio.Lock()


async def get_circuit_breaker() -> CircuitBreaker:
    """Get the module-level singleton circuit breaker instance.

    Returns:
        CircuitBreaker singleton instance

    Thread-safe lazy initialization on first access.
    """
    global _circuit_breaker_instance
    async with _instance_lock:
        if _circuit_breaker_instance is None:
            _circuit_breaker_instance = CircuitBreaker(
                failure_threshold=10,
                timeout=120,
                window=60,
            )
            logger.info(
                "Circuit breaker singleton initialized",
                extra={
                    "event": "circuit_breaker_init",
                    "failure_threshold": 10,
                    "timeout": 120,
                    "window": 60,
                },
            )
        return _circuit_breaker_instance


def circuit_breaker(func: Callable) -> Callable:
    """Decorator to apply circuit breaker to async functions.

    Uses the module-level singleton circuit breaker instance.

    Usage:
        @circuit_breaker
        async def fetch_fhir_resource(url: str):
            ...
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        breaker = await get_circuit_breaker()
        return await breaker.call(func, *args, **kwargs)

    return wrapper
```

---

### 2. Update `backend/app/core/fhir/client.py` to Use Singleton Circuit Breaker

Modify the `FHIRClient` class to use the singleton circuit breaker decorator:

**Before (US-017 pattern — per-instance breaker):**
```python
class FHIRClient:
    def __init__(self):
        self._circuit_breaker = CircuitBreaker(...)
        ...
```

**After (US-018 pattern — module singleton):**
```python
from app.core.fhir.circuit_breaker import circuit_breaker

class FHIRClient:
    def __init__(self):
        # No per-instance circuit breaker — uses module singleton via decorator
        ...

    @circuit_breaker
    async def _fetch_with_retry(self, url: str, params: dict | None = None) -> dict:
        """Fetch FHIR resource with retry logic (circuit breaker applied)."""
        ...
```

Ensure all FHIR fetch methods use the `@circuit_breaker` decorator indirectly through `_fetch_with_retry`.

---

### 3. Update `backend/app/core/fhir/__init__.py` Exports

Export the singleton accessor and state enum:

```python
"""FHIR authentication and API client.

Provides SMART on FHIR OAuth 2.0 authentication with token caching,
Pydantic wrapper models for FHIR R4 resources, and async resource fetch methods.
"""
from app.core.fhir.auth import FHIRAuthClient
from app.core.fhir.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitBreakerState,
    circuit_breaker,
    get_circuit_breaker,
)
# ... other imports

__all__ = [
    "FHIRAuthClient",
    "CircuitBreaker",
    "CircuitBreakerError",
    "CircuitBreakerState",
    "circuit_breaker",
    "get_circuit_breaker",
    # ... other exports
]
```

---

## Validation

### Manual Testing

```python
# Test script: test_circuit_breaker_singleton.py
import asyncio
from app.core.fhir.circuit_breaker import get_circuit_breaker, CircuitBreakerState

async def test_singleton():
    """Verify circuit breaker is a singleton."""
    breaker1 = await get_circuit_breaker()
    breaker2 = await get_circuit_breaker()
    
    assert breaker1 is breaker2, "Circuit breaker should be singleton"
    assert breaker1.state == CircuitBreakerState.CLOSED
    print("✓ Circuit breaker singleton verified")

async def test_state_persistence():
    """Verify state persists across accessor calls."""
    breaker = await get_circuit_breaker()
    
    # Simulate failure
    breaker.failure_count = 5
    
    # Get instance again — should have same state
    breaker2 = await get_circuit_breaker()
    assert breaker2.failure_count == 5, "State should persist"
    print("✓ State persistence verified")

asyncio.run(test_singleton())
asyncio.run(test_state_persistence())
```

### Integration Test

```bash
# Start backend server
cd backend
uvicorn app.main:app --reload

# Trigger 10 consecutive FHIR failures to open circuit
# (requires mock FHIR server returning 503)

# Verify circuit opens and logs CRITICAL message
grep "circuit_breaker_open" logs/app.log
```

---

## Code Review Checklist

- [ ] Circuit breaker state is module-level singleton (not per-instance)
- [ ] `asyncio.Lock` protects state transitions for thread-safety
- [ ] OPEN → HALF_OPEN transition occurs after 120s cooldown
- [ ] HALF_OPEN probe success closes circuit (CLOSED)
- [ ] HALF_OPEN probe failure reopens circuit (OPEN)
- [ ] Failure window (60s) resets count if expired
- [ ] All state transitions logged at INFO or CRITICAL level
- [ ] `CircuitBreakerError` includes remaining cooldown time
- [ ] No race conditions in concurrent access scenarios
- [ ] Singleton pattern uses lazy initialization (not module import-time)

---

## Definition of Done Checklist

- [ ] `CircuitBreaker` refactored to module-level singleton in `circuit_breaker.py`
- [ ] `get_circuit_breaker()` accessor function with lazy initialization
- [ ] `@circuit_breaker` decorator uses singleton instance
- [ ] `FHIRClient` uses `@circuit_breaker` decorator (not per-instance breaker)
- [ ] State transitions logged with structured extra fields
- [ ] Manual validation confirms singleton behavior
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-017 TASK-002 | Task | Provides base CircuitBreaker implementation to refactor |

---

## Technical Notes

- **Why singleton?** Multiple agent tasks in the same Cloud Run container should share circuit state to prevent hammering the EHR during degradation
- **Thread safety:** `asyncio.Lock` ensures state transitions are atomic across concurrent coroutines
- **Lazy init:** Singleton created on first `get_circuit_breaker()` call, not module import (cleaner for testing)
- **State reset:** Failure window expiry (60s) resets count to allow recovery without waiting full 120s cooldown

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Race conditions in state updates | Comprehensive lock coverage + unit tests (TASK-004) |
| Singleton not shared across instances | Document that singleton is per-Cloud Run *container*, not global |
| Testing difficulty with global state | Provide `_reset_for_testing()` method (not exported) |

---
