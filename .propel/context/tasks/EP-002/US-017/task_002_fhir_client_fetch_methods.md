# TASK-002: Implement FHIRClient with Async Resource Fetch Methods and Rate Limiting

> **Story:** US-017 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend | **Est:** 12 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task implements the `FHIRClient` class that orchestrates async FHIR R4 resource fetching with authentication, retry logic, circuit breaker, and rate limiting. The client integrates `FHIRAuthClient` from US-016 for OAuth 2.0 authentication and returns validated Pydantic models from TASK-001.

**Design references:**
- US-017 AC Scenario 1 — Fetch methods return typed Pydantic models
- AIR-011 — Exponential backoff retry (3 attempts: 1s/2s/4s) + circuit breaker
- AIR-013 — Token bucket rate limiter (100 req/min per agent instance)
- US-017 Technical Notes — Parse FHIR Bundle responses

---

## Acceptance Criteria Addressed

- AC Scenario 1: Patient fetched by MRN returns typed `PatientModel`
- AIR-011: Retry and circuit breaker for transient FHIR API failures
- AIR-013: Rate limiting to prevent FHIR server overload

---

## Implementation Steps

### 1. Create `backend/app/core/fhir/rate_limiter.py`

Implement token bucket rate limiter decorator:

```python
"""Token bucket rate limiter for FHIR API calls.

Design refs:
    AIR-013 — 100 FHIR req/min per agent instance
    US-017 Technical Notes — Rate limiter as decorator
"""
from __future__ import annotations

import asyncio
import logging
import time
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """Token bucket rate limiter for async functions.

    Attributes:
        capacity: Maximum number of tokens (requests) in bucket
        refill_rate: Tokens added per second
        tokens: Current number of available tokens
        last_refill: Timestamp of last token refill
    """

    def __init__(self, capacity: int = 100, refill_rate: float = 1.67) -> None:
        """Initialize token bucket.

        Args:
            capacity: Maximum bucket capacity (default: 100 requests)
            refill_rate: Tokens per second (default: 1.67 = 100/min)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now

    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens from bucket (blocking if insufficient).

        Args:
            tokens: Number of tokens to acquire (default: 1)

        Blocks until enough tokens are available, then consumes them.
        Uses exponential backoff if bucket empty.
        """
        async with self._lock:
            attempt = 0
            backoff_delays = [1, 2, 4]  # Exponential backoff

            while self.tokens < tokens:
                await self._refill()

                if self.tokens >= tokens:
                    break

                # Bucket empty — exponential backoff
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                logger.warning(
                    "Rate limit reached, backing off",
                    extra={
                        "event": "rate_limit_backoff",
                        "attempt": attempt + 1,
                        "delay_seconds": delay,
                        "current_tokens": self.tokens,
                    },
                )
                await asyncio.sleep(delay)
                attempt += 1

            # Consume tokens
            self.tokens -= tokens


def rate_limited(limiter: TokenBucketRateLimiter) -> Callable:
    """Decorator to apply rate limiting to async functions.

    Args:
        limiter: TokenBucketRateLimiter instance

    Usage:
        limiter = TokenBucketRateLimiter(capacity=100, refill_rate=1.67)

        @rate_limited(limiter)
        async def fetch_fhir_resource(url: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            await limiter.acquire()
            return await func(*args, **kwargs)

        return wrapper

    return decorator
```

---

### 2. Create `backend/app/core/fhir/circuit_breaker.py`

Implement circuit breaker pattern:

```python
"""Circuit breaker pattern for FHIR API resilience.

Design refs:
    AIR-011 — Circuit breaker: 10 failures in 60s → open for 120s
    US-017 Technical Notes — Half-open probe after cooldown
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
    """Circuit breaker for async functions.

    Tracks failure rate and opens circuit if threshold exceeded.

    Attributes:
        failure_threshold: Number of consecutive failures before opening
        timeout: Seconds to wait in OPEN state before HALF_OPEN probe
        window: Time window (seconds) for counting failures
    """

    def __init__(
        self,
        failure_threshold: int = 10,
        timeout: int = 120,
        window: int = 60,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Max consecutive failures before opening (default: 10)
            timeout: Cooldown period in OPEN state (default: 120s)
            window: Time window for counting failures (default: 60s)
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
                            "state": self.state,
                            "elapsed_seconds": elapsed,
                            "cooldown_remaining": self.timeout - elapsed,
                        },
                    )
                    raise CircuitBreakerError(
                        f"Circuit breaker OPEN. Retry in {self.timeout - elapsed:.0f}s"
                    )
                else:
                    # Timeout expired — transition to HALF_OPEN for probe
                    self.state = CircuitBreakerState.HALF_OPEN
                    logger.info(
                        "Circuit breaker transitioning to HALF_OPEN",
                        extra={"event": "circuit_breaker_half_open"},
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
                        extra={"event": "circuit_breaker_close"},
                    )
                self.failure_count = 0
                self.last_failure_time = None

            return result

        except Exception as exc:
            # Failure — increment count and possibly open circuit
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.monotonic()

                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitBreakerState.OPEN
                    self.opened_at = time.monotonic()
                    logger.critical(
                        "Circuit breaker OPENED due to failure threshold",
                        extra={
                            "event": "circuit_breaker_open",
                            "failure_count": self.failure_count,
                            "threshold": self.failure_threshold,
                        },
                    )

            raise


def circuit_breaker(breaker: CircuitBreaker) -> Callable:
    """Decorator to apply circuit breaker to async functions.

    Args:
        breaker: CircuitBreaker instance

    Usage:
        breaker = CircuitBreaker(failure_threshold=10, timeout=120, window=60)

        @circuit_breaker(breaker)
        async def fetch_fhir_resource(url: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator
```

---

### 3. Create `backend/app/core/fhir/client.py`

Implement `FHIRClient` with fetch methods:

```python
"""FHIR R4 client with async resource fetch methods.

Design refs:
    US-017 AC Scenario 1 — Fetch methods return typed Pydantic models
    AIR-011              — Retry + circuit breaker
    AIR-013              — Rate limiting (100 req/min)
    AIR-012              — FHIR data not persisted (in-memory only)
    US-017 Technical Notes — Parse FHIR Bundle responses

IMPORTANT: FHIR data is NEVER persisted to SmartHandoff database.
All fetch methods return in-memory Pydantic models only.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fhir.resources.allergyintolerance import AllergyIntolerance
from fhir.resources.bundle import Bundle
from fhir.resources.condition import Condition
from fhir.resources.encounter import Encounter
from fhir.resources.medicationadministration import MedicationAdministration
from fhir.resources.medicationrequest import MedicationRequest
from fhir.resources.medicationstatement import MedicationStatement
from fhir.resources.patient import Patient

from app.core.config import get_settings
from app.core.fhir.auth import FHIRAuthClient
from app.core.fhir.circuit_breaker import CircuitBreaker, circuit_breaker
from app.core.fhir.models import (
    AllergyIntoleranceModel,
    ConditionModel,
    EncounterModel,
    MedicationAdministrationModel,
    MedicationRequestModel,
    MedicationStatementModel,
)
from app.core.fhir.rate_limiter import TokenBucketRateLimiter, rate_limited

logger = logging.getLogger(__name__)


class FHIRClient:
    """FHIR R4 client for async resource fetching.

    This client provides typed async fetch methods for FHIR resources:
    - Patient, Encounter
    - MedicationStatement, MedicationAdministration, MedicationRequest
    - AllergyIntolerance, Condition

    Features:
    - OAuth 2.0 authentication via FHIRAuthClient (US-016)
    - Exponential backoff retry (3 attempts: 1s/2s/4s)
    - Circuit breaker (10 failures → open for 120s)
    - Rate limiting (100 req/min per instance)
    - Pydantic model validation (TASK-001)

    IMPORTANT: FHIR data returned in-memory only; never persisted to SmartHandoff DB.

    Usage:
        client = FHIRClient()
        patient = await client.get_patient_by_mrn("MRN-001")
        medications = await client.get_medication_statements(patient.id)
        await client.close()
    """

    def __init__(self) -> None:
        """Initialize FHIR client with auth, rate limiter, and circuit breaker."""
        self._settings = get_settings()
        self._auth_client = FHIRAuthClient()
        self._http_client = httpx.AsyncClient(
            verify=True,
            timeout=httpx.Timeout(30.0),  # 30s timeout for FHIR requests
            follow_redirects=True,
        )
        self._rate_limiter = TokenBucketRateLimiter(capacity=100, refill_rate=1.67)
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=10, timeout=120, window=60
        )
        logger.info(
            "FHIRClient initialized",
            extra={
                "event": "fhir_client_init",
                "base_url": self._settings.FHIR_BASE_URL,
            },
        )

    async def _fetch_with_retry(
        self, url: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Fetch FHIR resource with exponential backoff retry.

        Args:
            url: Full FHIR resource URL
            params: Query parameters (optional)

        Returns:
            Parsed JSON response

        Raises:
            httpx.HTTPError: If all retry attempts fail
        """
        backoff_delays = [1, 2, 4]  # 3 attempts with exponential backoff
        access_token = await self._auth_client.get_access_token()

        for attempt in range(len(backoff_delays)):
            try:
                response = await self._http_client.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/fhir+json",
                    },
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (401, 403):
                    # Auth error — invalidate token and retry once
                    logger.warning(
                        "FHIR request auth error — invalidating token",
                        extra={
                            "event": "fhir_auth_error",
                            "status_code": exc.response.status_code,
                        },
                    )
                    await self._auth_client.invalidate_token()
                    access_token = await self._auth_client.get_access_token()
                    continue

                if attempt < len(backoff_delays) - 1:
                    delay = backoff_delays[attempt]
                    logger.warning(
                        "FHIR request failed — retrying",
                        extra={
                            "event": "fhir_retry",
                            "attempt": attempt + 1,
                            "status_code": exc.response.status_code,
                            "delay_seconds": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "FHIR request failed after all retries",
                        extra={
                            "event": "fhir_request_failed",
                            "status_code": exc.response.status_code,
                            "url": url,
                        },
                    )
                    raise

            except httpx.HTTPError as exc:
                if attempt < len(backoff_delays) - 1:
                    delay = backoff_delays[attempt]
                    logger.warning(
                        "FHIR network error — retrying",
                        extra={
                            "event": "fhir_network_error",
                            "attempt": attempt + 1,
                            "error": str(exc),
                            "delay_seconds": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "FHIR network error after all retries",
                        extra={"event": "fhir_network_failed", "error": str(exc)},
                    )
                    raise

    @rate_limited
    @circuit_breaker
    async def get_encounter_by_id(self, encounter_id: str) -> EncounterModel:
        """Fetch Encounter resource by ID.

        Args:
            encounter_id: FHIR Encounter resource ID

        Returns:
            EncounterModel with validated fields

        Raises:
            FHIRValidationError: If resource invalid
            httpx.HTTPError: If request fails after retries
            CircuitBreakerError: If circuit breaker open

        Note: FHIR data returned in-memory only; never persisted to SmartHandoff DB.
        """
        url = f"{self._settings.FHIR_BASE_URL}/Encounter/{encounter_id}"
        fhir_json = await self._fetch_with_retry(url)
        fhir_encounter = Encounter(**fhir_json)
        return EncounterModel.from_fhir(fhir_encounter)

    @rate_limited
    @circuit_breaker
    async def get_medication_statements(
        self, patient_id: str
    ) -> list[MedicationStatementModel]:
        """Fetch MedicationStatement resources for patient.

        Args:
            patient_id: FHIR Patient resource ID

        Returns:
            List of MedicationStatementModel (empty if none found)

        Note: FHIR data returned in-memory only; never persisted to SmartHandoff DB.
        """
        url = f"{self._settings.FHIR_BASE_URL}/MedicationStatement"
        params = {"patient": patient_id}
        fhir_json = await self._fetch_with_retry(url, params)

        # Parse Bundle
        bundle = Bundle(**fhir_json)
        results = []
        if bundle.entry:
            for entry in bundle.entry:
                if entry.resource and entry.resource.resource_type == "MedicationStatement":
                    fhir_med_statement = MedicationStatement(**entry.resource.dict())
                    results.append(MedicationStatementModel.from_fhir(fhir_med_statement))

        logger.info(
            "Fetched MedicationStatements",
            extra={
                "event": "fhir_fetch_medication_statements",
                "patient_id": patient_id,
                "count": len(results),
            },
        )
        return results

    @rate_limited
    @circuit_breaker
    async def get_medication_administrations(
        self, encounter_id: str
    ) -> list[MedicationAdministrationModel]:
        """Fetch MedicationAdministration resources for encounter.

        Args:
            encounter_id: FHIR Encounter resource ID

        Returns:
            List of MedicationAdministrationModel (empty if none found)

        Note: FHIR data returned in-memory only; never persisted to SmartHandoff DB.
        """
        url = f"{self._settings.FHIR_BASE_URL}/MedicationAdministration"
        params = {"encounter": encounter_id}
        fhir_json = await self._fetch_with_retry(url, params)

        bundle = Bundle(**fhir_json)
        results = []
        if bundle.entry:
            for entry in bundle.entry:
                if (
                    entry.resource
                    and entry.resource.resource_type == "MedicationAdministration"
                ):
                    fhir_med_admin = MedicationAdministration(**entry.resource.dict())
                    results.append(MedicationAdministrationModel.from_fhir(fhir_med_admin))

        logger.info(
            "Fetched MedicationAdministrations",
            extra={
                "event": "fhir_fetch_medication_administrations",
                "encounter_id": encounter_id,
                "count": len(results),
            },
        )
        return results

    @rate_limited
    @circuit_breaker
    async def get_medication_requests(
        self, patient_id: str
    ) -> list[MedicationRequestModel]:
        """Fetch MedicationRequest resources for patient.

        Args:
            patient_id: FHIR Patient resource ID

        Returns:
            List of MedicationRequestModel (empty if none found)

        Note: FHIR data returned in-memory only; never persisted to SmartHandoff DB.
        """
        url = f"{self._settings.FHIR_BASE_URL}/MedicationRequest"
        params = {"patient": patient_id}
        fhir_json = await self._fetch_with_retry(url, params)

        bundle = Bundle(**fhir_json)
        results = []
        if bundle.entry:
            for entry in bundle.entry:
                if entry.resource and entry.resource.resource_type == "MedicationRequest":
                    fhir_med_request = MedicationRequest(**entry.resource.dict())
                    results.append(MedicationRequestModel.from_fhir(fhir_med_request))

        logger.info(
            "Fetched MedicationRequests",
            extra={
                "event": "fhir_fetch_medication_requests",
                "patient_id": patient_id,
                "count": len(results),
            },
        )
        return results

    @rate_limited
    @circuit_breaker
    async def get_allergy_intolerances(
        self, patient_id: str
    ) -> list[AllergyIntoleranceModel]:
        """Fetch AllergyIntolerance resources for patient.

        Args:
            patient_id: FHIR Patient resource ID

        Returns:
            List of AllergyIntoleranceModel (empty if none found)

        Note: FHIR data returned in-memory only; never persisted to SmartHandoff DB.
        """
        url = f"{self._settings.FHIR_BASE_URL}/AllergyIntolerance"
        params = {"patient": patient_id}
        fhir_json = await self._fetch_with_retry(url, params)

        bundle = Bundle(**fhir_json)
        results = []
        if bundle.entry:
            for entry in bundle.entry:
                if entry.resource and entry.resource.resource_type == "AllergyIntolerance":
                    fhir_allergy = AllergyIntolerance(**entry.resource.dict())
                    results.append(AllergyIntoleranceModel.from_fhir(fhir_allergy))

        logger.info(
            "Fetched AllergyIntolerances",
            extra={
                "event": "fhir_fetch_allergy_intolerances",
                "patient_id": patient_id,
                "count": len(results),
            },
        )
        return results

    @rate_limited
    @circuit_breaker
    async def get_conditions(self, patient_id: str) -> list[ConditionModel]:
        """Fetch Condition resources for patient.

        Args:
            patient_id: FHIR Patient resource ID

        Returns:
            List of ConditionModel (empty if none found)

        Note: FHIR data returned in-memory only; never persisted to SmartHandoff DB.
        """
        url = f"{self._settings.FHIR_BASE_URL}/Condition"
        params = {"patient": patient_id}
        fhir_json = await self._fetch_with_retry(url, params)

        bundle = Bundle(**fhir_json)
        results = []
        if bundle.entry:
            for entry in bundle.entry:
                if entry.resource and entry.resource.resource_type == "Condition":
                    fhir_condition = Condition(**entry.resource.dict())
                    results.append(ConditionModel.from_fhir(fhir_condition))

        logger.info(
            "Fetched Conditions",
            extra={
                "event": "fhir_fetch_conditions",
                "patient_id": patient_id,
                "count": len(results),
            },
        )
        return results

    async def close(self) -> None:
        """Close HTTP clients and release resources."""
        await self._http_client.aclose()
        await self._auth_client.close()
        logger.info("FHIRClient closed")
```

---

### 4. Update `backend/app/core/fhir/__init__.py`

Add exports for client, rate limiter, and circuit breaker:

```python
"""FHIR authentication and API client.

Provides SMART on FHIR OAuth 2.0 authentication with token caching,
Pydantic wrapper models for FHIR R4 resources, and async resource fetch methods.
"""
from app.core.fhir.auth import FHIRAuthClient
from app.core.fhir.circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitBreakerState
from app.core.fhir.client import FHIRClient
from app.core.fhir.discovery import discover_smart_config, get_token_endpoint
from app.core.fhir.exceptions import FHIRAuthenticationError
from app.core.fhir.models import (
    AllergyIntoleranceModel,
    ConditionModel,
    EncounterModel,
    FHIRValidationError,
    MedicationAdministrationModel,
    MedicationRequestModel,
    MedicationStatementModel,
    PatientModel,
    PatientResolutionMethod,
)
from app.core.fhir.rate_limiter import TokenBucketRateLimiter, rate_limited
from app.core.fhir.token_cache import TokenCache, TokenCacheEntry

__all__ = [
    "FHIRAuthClient",
    "FHIRAuthenticationError",
    "FHIRValidationError",
    "FHIRClient",
    "TokenCache",
    "TokenCacheEntry",
    "TokenBucketRateLimiter",
    "rate_limited",
    "CircuitBreaker",
    "CircuitBreakerState",
    "CircuitBreakerError",
    "discover_smart_config",
    "get_token_endpoint",
    # Models
    "PatientModel",
    "EncounterModel",
    "MedicationStatementModel",
    "MedicationAdministrationModel",
    "MedicationRequestModel",
    "AllergyIntoleranceModel",
    "ConditionModel",
    "PatientResolutionMethod",
]
```

---

## Validation

### Manual fetch test with mock FHIR server

```bash
cd backend

# Test with real FHIR test server (or use respx mock for local testing)
python -c "
import asyncio
from app.core.fhir import FHIRClient

async def test_fetch():
    client = FHIRClient()
    
    try:
        # Test fetch encounter (replace with valid test encounter ID)
        encounter = await client.get_encounter_by_id('encounter-001')
        print(f'✓ Fetched Encounter: {encounter.id}')
        
        # Test fetch medications
        medications = await client.get_medication_statements('patient-001')
        print(f'✓ Fetched {len(medications)} MedicationStatements')
        
        print('All fetch methods working correctly')
    finally:
        await client.close()

asyncio.run(test_fetch())
"
```

---

## Code Review Checklist

- [ ] `FHIRClient` integrates `FHIRAuthClient` for OAuth authentication
- [ ] All fetch methods use `@rate_limited` and `@circuit_breaker` decorators
- [ ] Exponential backoff retry (3 attempts: 1s/2s/4s) in `_fetch_with_retry()`
- [ ] Token bucket rate limiter enforces 100 req/min capacity
- [ ] Circuit breaker opens after 10 failures, closes after 120s cooldown
- [ ] FHIR Bundle responses correctly parsed to extract `entry[].resource`
- [ ] All fetch methods return validated Pydantic models from TASK-001
- [ ] Docstrings include non-persistence note (AIR-012)
- [ ] No PHI in logs (SEC-011)
- [ ] Module exports updated in `__init__.py`

---

## Definition of Done Checklist

- [ ] `backend/app/core/fhir/rate_limiter.py` created with TokenBucketRateLimiter
- [ ] `backend/app/core/fhir/circuit_breaker.py` created with CircuitBreaker
- [ ] `backend/app/core/fhir/client.py` created with FHIRClient and 6 fetch methods
- [ ] All fetch methods use rate limiter and circuit breaker decorators
- [ ] Exponential backoff retry logic implemented
- [ ] FHIR Bundle parsing correctly extracts resources
- [ ] Manual fetch test with mock FHIR server passes
- [ ] Module exports updated in `__init__.py`
- [ ] Code passes `ruff check` and `mypy` validation
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | Pydantic models required for fetch method returns |
| US-016 | Story | FHIRAuthClient required for OAuth authentication |
| httpx | Package | Already in tech stack |
| fhir.resources | Package | Added in TASK-001 |

---

## Technical Notes

### Rate Limiter Token Bucket

- **Capacity:** 100 tokens (max burst)
- **Refill rate:** 1.67 tokens/sec = 100 tokens/min
- **Behavior:** If bucket empty, blocks with exponential backoff (1s, 2s, 4s)

### Circuit Breaker States

- **CLOSED:** Normal operation — all requests allowed
- **OPEN:** Failing — all requests rejected with `CircuitBreakerError`
- **HALF_OPEN:** Probing — allow 1 test request after cooldown

### Fetch Method Pattern

All fetch methods follow this pattern:
1. Apply `@rate_limited` decorator (acquire token before request)
2. Apply `@circuit_breaker` decorator (check circuit state)
3. Call `_fetch_with_retry()` with exponential backoff
4. Parse FHIR Bundle response (if list resource)
5. Convert to Pydantic model via `.from_fhir()`
6. Return validated model (in-memory only — never persisted)

---
