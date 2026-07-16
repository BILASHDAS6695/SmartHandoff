---
id: TASK-002
title: "Add Prometheus Metrics for Retry, Circuit Breaker, and Rate Limiter"
user_story: US-018
epic: EP-002
sprint: 1
layer: Backend / Observability
estimate: 8h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-018/TASK-001, US-017/TASK-002]
---

# TASK-002: Add Prometheus Metrics for Retry, Circuit Breaker, and Rate Limiter

> **Story:** US-018 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend / Observability | **Est:** 8 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-018 DoD requires:

> *"Prometheus metrics: `fhir_circuit_state`, `fhir_retry_total`, `fhir_rate_limited_total`"*

This task instruments the FHIR resilience patterns (circuit breaker, retry, rate limiter) with Prometheus metrics for observability. These metrics are scraped by Cloud Monitoring (GCP Prometheus integration) and used for alerting and dashboards.

**Design references:**
- US-018 DoD — Prometheus metrics requirement
- EP-001 US-011 TASK-004 — Prometheus metrics pattern
- TR-016 — Observability requirements

---

## Acceptance Criteria Addressed

- US-018 DoD: Prometheus metrics `fhir_circuit_state`, `fhir_retry_total`, `fhir_rate_limited_total` exported

---

## Implementation Steps

### 1. Create `backend/app/core/fhir/metrics.py`

Define Prometheus metrics for FHIR resilience patterns:

```python
"""Prometheus metrics for FHIR client resilience patterns.

Exposes metrics for circuit breaker, retry, rate limiter, and fetch duration.
Scraped by Cloud Monitoring (GCP Prometheus integration).

Metrics:
  - fhir_circuit_state{state}            — Gauge (CLOSED=0, HALF_OPEN=1, OPEN=2)
  - fhir_retry_total{outcome}            — Counter (success, exhausted, no_retry_needed)
  - fhir_rate_limited_total              — Counter (rate limiter backoff events)
  - fhir_fetch_duration_seconds{resource_type} — Histogram (fetch latency)

Design refs:
    US-018 DoD — Prometheus metrics requirement
    TR-016     — Observability / metrics
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Circuit Breaker Metrics ───────────────────────────────────────────────────
CIRCUIT_STATE: Gauge = Gauge(
    name="fhir_circuit_state",
    documentation=(
        "Current circuit breaker state for FHIR API calls. "
        "Values: 0=CLOSED, 1=HALF_OPEN, 2=OPEN"
    ),
)

# ── Retry Metrics ─────────────────────────────────────────────────────────────
RETRY_TOTAL: Counter = Counter(
    name="fhir_retry_total",
    documentation=(
        "Total FHIR API retry outcomes. "
        "Labels: outcome (success, exhausted, no_retry_needed)"
    ),
    labelnames=["outcome"],
)

# ── Rate Limiter Metrics ──────────────────────────────────────────────────────
RATE_LIMITED_TOTAL: Counter = Counter(
    name="fhir_rate_limited_total",
    documentation=(
        "Total number of FHIR API requests delayed due to rate limiting "
        "(token bucket empty, backoff applied)."
    ),
)

# ── Fetch Duration Metrics ────────────────────────────────────────────────────
FETCH_DURATION: Histogram = Histogram(
    name="fhir_fetch_duration_seconds",
    documentation=(
        "FHIR resource fetch latency in seconds, labelled by resource type. "
        "Measured from HTTP request start to response body received."
    ),
    labelnames=["resource_type"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)


# ── Helper Functions ──────────────────────────────────────────────────────────
def set_circuit_state(state: str) -> None:
    """Update circuit breaker state gauge.

    Args:
        state: CircuitBreakerState value (CLOSED, HALF_OPEN, OPEN)
    """
    state_values = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}
    CIRCUIT_STATE.set(state_values.get(state, 0))


def increment_retry_outcome(outcome: str) -> None:
    """Increment retry outcome counter.

    Args:
        outcome: Retry result (success, exhausted, no_retry_needed)
    """
    RETRY_TOTAL.labels(outcome=outcome).inc()


def increment_rate_limited() -> None:
    """Increment rate limiter backoff counter."""
    RATE_LIMITED_TOTAL.inc()


def observe_fetch_duration(resource_type: str, duration: float) -> None:
    """Record FHIR fetch duration.

    Args:
        resource_type: FHIR resource type (Patient, Encounter, etc.)
        duration: Fetch duration in seconds
    """
    FETCH_DURATION.labels(resource_type=resource_type).observe(duration)
```

---

### 2. Instrument Circuit Breaker with Metrics

Modify `backend/app/core/fhir/circuit_breaker.py` to update metrics on state transitions:

**Add import:**
```python
from app.core.fhir.metrics import set_circuit_state
```

**Update state transitions:**

```python
class CircuitBreaker:
    async def call(self, func: Callable, *args, **kwargs):
        async with self._lock:
            # ... existing logic ...
            
            # When opening circuit
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                self.opened_at = time.monotonic()
                set_circuit_state("OPEN")  # ← Add this
                logger.critical(...)
            
            # When transitioning to HALF_OPEN
            if elapsed >= self.timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                set_circuit_state("HALF_OPEN")  # ← Add this
                logger.info(...)
        
        try:
            result = await func(*args, **kwargs)
            
            async with self._lock:
                # When closing circuit
                if self.state == CircuitBreakerState.HALF_OPEN:
                    self.state = CircuitBreakerState.CLOSED
                    set_circuit_state("CLOSED")  # ← Add this
                    logger.info(...)
            
            return result
        
        except Exception as exc:
            async with self._lock:
                # When reopening circuit after failed probe
                if self.state == CircuitBreakerState.HALF_OPEN:
                    self.state = CircuitBreakerState.OPEN
                    self.opened_at = time.monotonic()
                    set_circuit_state("OPEN")  # ← Add this
                    logger.critical(...)
```

**Initialize metric on singleton creation:**

```python
async def get_circuit_breaker() -> CircuitBreaker:
    global _circuit_breaker_instance
    async with _instance_lock:
        if _circuit_breaker_instance is None:
            _circuit_breaker_instance = CircuitBreaker(...)
            set_circuit_state("CLOSED")  # ← Initialize metric
            logger.info(...)
        return _circuit_breaker_instance
```

---

### 3. Instrument Rate Limiter with Metrics

Modify `backend/app/core/fhir/rate_limiter.py` to count rate limit backoffs:

**Add import:**
```python
from app.core.fhir.metrics import increment_rate_limited
```

**Update `acquire()` method:**

```python
class TokenBucketRateLimiter:
    async def acquire(self, tokens: int = 1) -> None:
        async with self._lock:
            attempt = 0
            backoff_delays = [1, 2, 4]
            
            while self.tokens < tokens:
                await self._refill()
                
                if self.tokens >= tokens:
                    break
                
                # Bucket empty — backoff
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                increment_rate_limited()  # ← Add this
                logger.warning(...)
                await asyncio.sleep(delay)
                attempt += 1
            
            self.tokens -= tokens
```

---

### 4. Instrument Retry Logic with Metrics

Modify `backend/app/core/fhir/client.py` to track retry outcomes:

**Add import:**
```python
from app.core.fhir.metrics import increment_retry_outcome, observe_fetch_duration
```

**Update `_fetch_with_retry()` method:**

```python
class FHIRClient:
    async def _fetch_with_retry(
        self, url: str, params: dict | None = None
    ) -> dict:
        """Fetch FHIR resource with exponential backoff retry.
        
        Retry only on: 5xx status, network timeout, connection errors.
        Do NOT retry on: 4xx status (client errors).
        """
        attempts = 3
        backoff_delays = [1, 2, 4]
        
        for attempt in range(attempts):
            try:
                start_time = time.monotonic()
                
                # Make HTTP request
                response = await self._http_client.get(url, params=params, ...)
                
                # Record duration
                duration = time.monotonic() - start_time
                resource_type = url.split("/")[-2] if "/" in url else "unknown"
                observe_fetch_duration(resource_type, duration)
                
                if response.status_code < 400:
                    # Success
                    if attempt == 0:
                        increment_retry_outcome("no_retry_needed")
                    else:
                        increment_retry_outcome("success")
                    return response.json()
                
                elif 400 <= response.status_code < 500:
                    # Client error — no retry
                    increment_retry_outcome("no_retry_needed")
                    raise FHIRClientError(...)
                
                else:
                    # Server error — retry
                    if attempt == attempts - 1:
                        # Exhausted retries
                        increment_retry_outcome("exhausted")
                        raise FHIRServerError(...)
                    
                    delay = backoff_delays[attempt]
                    logger.warning(f"Retry attempt {attempt + 1} after {delay}s")
                    await asyncio.sleep(delay)
            
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                # Network error — retry
                if attempt == attempts - 1:
                    increment_retry_outcome("exhausted")
                    raise FHIRNetworkError(...) from exc
                
                delay = backoff_delays[attempt]
                logger.warning(f"Network error, retry {attempt + 1} after {delay}s")
                await asyncio.sleep(delay)
```

---

### 5. Update `backend/app/core/fhir/__init__.py` Exports

Export metrics module:

```python
from app.core.fhir import metrics

__all__ = [
    # ... existing exports
    "metrics",
]
```

---

### 6. Add `prometheus_client` to `backend/requirements.txt`

```txt
# Prometheus metrics
prometheus_client>=0.20.0
```

---

### 7. Expose `/metrics` Endpoint in FastAPI

In `backend/app/main.py`, add Prometheus metrics endpoint:

```python
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint (scraped by Cloud Monitoring)."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

---

## Validation

### Manual Testing

```bash
# Start backend server
cd backend
uvicorn app.main:app --reload

# Trigger FHIR requests (requires mock FHIR server or HAPI sandbox)
curl http://localhost:8000/api/v1/patients/MRN-001

# Check metrics endpoint
curl http://localhost:8000/metrics | grep fhir_
```

Expected output:
```
# HELP fhir_circuit_state Current circuit breaker state
# TYPE fhir_circuit_state gauge
fhir_circuit_state 0.0

# HELP fhir_retry_total Total FHIR API retry outcomes
# TYPE fhir_retry_total counter
fhir_retry_total{outcome="no_retry_needed"} 1.0

# HELP fhir_rate_limited_total Total rate limit backoffs
# TYPE fhir_rate_limited_total counter
fhir_rate_limited_total 0.0

# HELP fhir_fetch_duration_seconds FHIR fetch latency
# TYPE fhir_fetch_duration_seconds histogram
fhir_fetch_duration_seconds_bucket{le="0.05",resource_type="Patient"} 0.0
fhir_fetch_duration_seconds_bucket{le="0.1",resource_type="Patient"} 1.0
```

### Integration Test

```python
# Test script: test_metrics_instrumentation.py
import asyncio
import httpx
from app.core.fhir.circuit_breaker import get_circuit_breaker, CircuitBreakerState
from app.core.fhir.metrics import CIRCUIT_STATE, RETRY_TOTAL

async def test_circuit_breaker_metric():
    """Verify circuit breaker metric updates."""
    breaker = await get_circuit_breaker()
    
    # Initial state
    assert CIRCUIT_STATE._value.get() == 0  # CLOSED
    
    # Simulate opening circuit
    breaker.state = CircuitBreakerState.OPEN
    from app.core.fhir.metrics import set_circuit_state
    set_circuit_state("OPEN")
    
    assert CIRCUIT_STATE._value.get() == 2  # OPEN
    print("✓ Circuit breaker metric verified")

def test_retry_metric():
    """Verify retry metric increments."""
    from app.core.fhir.metrics import increment_retry_outcome
    
    initial = RETRY_TOTAL.labels(outcome="success")._value.get()
    increment_retry_outcome("success")
    
    assert RETRY_TOTAL.labels(outcome="success")._value.get() == initial + 1
    print("✓ Retry metric verified")

asyncio.run(test_circuit_breaker_metric())
test_retry_metric()
```

---

## Code Review Checklist

- [ ] `metrics.py` module created with all 4 required metrics
- [ ] Circuit breaker updates `fhir_circuit_state` on every state transition
- [ ] Rate limiter increments `fhir_rate_limited_total` on backoff
- [ ] Retry logic increments `fhir_retry_total` with correct outcome label
- [ ] Fetch duration histogram records latency per resource type
- [ ] `/metrics` endpoint returns Prometheus text format
- [ ] Metrics use appropriate types (Gauge, Counter, Histogram)
- [ ] No metric cardinality explosion (bounded label values)
- [ ] Metrics follow naming convention: `fhir_*`

---

## Definition of Done Checklist

- [ ] `backend/app/core/fhir/metrics.py` created with 4 metrics
- [ ] Circuit breaker instrumented with `set_circuit_state()`
- [ ] Rate limiter instrumented with `increment_rate_limited()`
- [ ] Retry logic instrumented with `increment_retry_outcome()`
- [ ] Fetch duration recorded with `observe_fetch_duration()`
- [ ] `/metrics` endpoint exposed in FastAPI
- [ ] `prometheus_client>=0.20.0` added to `requirements.txt`
- [ ] Manual validation confirms metrics appear at `/metrics`
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-018 TASK-001 | Task | Circuit breaker singleton must exist to instrument |
| US-017 TASK-002 | Task | Rate limiter and retry logic must exist |
| prometheus_client | Package | Python Prometheus client library |

---

## Technical Notes

- **Metric Types:**
  - `Gauge` for circuit state (can go up/down)
  - `Counter` for retry outcomes and rate limit events (monotonic increase)
  - `Histogram` for fetch duration (distribution with buckets)
- **Label Cardinality:** Keep label values bounded to prevent cardinality explosion:
  - `outcome`: 3 values (success, exhausted, no_retry_needed)
  - `resource_type`: 7 FHIR types (Patient, Encounter, etc.)
- **Cloud Monitoring:** GCP Prometheus integration scrapes `/metrics` every 60s
- **Alerting:** Metrics can trigger Cloud Monitoring alerts (e.g., circuit open > 5 minutes)

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Metric cardinality explosion | Bounded label values, no dynamic user data in labels |
| Performance impact of metric recording | Prometheus client is highly optimized; <1ms overhead per call |
| Missing metric updates | Comprehensive unit tests (TASK-004) validate all code paths |

---

## Metrics Schema Reference

```python
# Circuit Breaker State Gauge
fhir_circuit_state 0  # 0=CLOSED, 1=HALF_OPEN, 2=OPEN

# Retry Outcome Counter
fhir_retry_total{outcome="success"} 42
fhir_retry_total{outcome="exhausted"} 3
fhir_retry_total{outcome="no_retry_needed"} 150

# Rate Limiter Counter
fhir_rate_limited_total 5

# Fetch Duration Histogram
fhir_fetch_duration_seconds_bucket{resource_type="Patient",le="0.1"} 120
fhir_fetch_duration_seconds_bucket{resource_type="Patient",le="0.5"} 200
fhir_fetch_duration_seconds_sum{resource_type="Patient"} 45.3
fhir_fetch_duration_seconds_count{resource_type="Patient"} 250
```

---
