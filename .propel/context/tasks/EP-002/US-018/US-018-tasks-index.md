# US-018 Implementation Tasks — FHIR Client Circuit Breaker & Exponential Backoff Retry

> **Epic:** EP-002 — EHR / FHIR Integration | **Sprint:** 1 | **Story Points:** 3  
> **Status:** Draft | **Date:** 2026-07-16

---

## Task Breakdown Summary

| Task ID | Title | Layer | Effort | Dependencies |
|---------|-------|-------|--------|--------------|
| TASK-001 | Refactor Circuit Breaker to Module-Level Singleton with State Persistence | Backend | 6 h | US-017/TASK-002 |
| TASK-002 | Add Prometheus Metrics for Retry, Circuit Breaker, and Rate Limiter | Backend | 8 h | TASK-001, US-017/TASK-002 |
| TASK-003 | Validate and Enhance Retry Logic with Selective Error Handling | Backend | 6 h | US-017/TASK-002 |
| TASK-004 | Comprehensive Unit Tests for Resilience Patterns with Edge Cases | Backend Testing | 8 h | TASK-001, TASK-002, TASK-003 |

**Total:** 28 hours ≈ 3.5 story points → Rounded to **3 story points** (optimistic scenario assuming US-017 foundation is solid)

---

## Task Descriptions

### TASK-001: Refactor Circuit Breaker to Module-Level Singleton with State Persistence
**Effort:** 6 h | **File:** [task_001_circuit_breaker_singleton_metrics.md](task_001_circuit_breaker_singleton_metrics.md)

**Scope:**
- Refactor `CircuitBreaker` in `backend/app/core/fhir/circuit_breaker.py` to module-level singleton
- State persisted in module-level variable (per Cloud Run instance scope)
- Ensure thread-safe state transitions with `asyncio.Lock`
- Implement OPEN → HALF_OPEN probe logic after 120s cooldown
- Add state transition logging at INFO (CLOSED→OPEN, OPEN→HALF_OPEN) and CRITICAL (OPEN) levels

**Acceptance Criteria Addressed:**
- AC Scenario 2 (circuit opens after 10 failures in 60s)
- AC Scenario 3 (half-open probe after 120s)
- Technical Note: Module-level singleton per instance

**Files Modified:**
- `backend/app/core/fhir/circuit_breaker.py`
- `backend/app/core/fhir/client.py` (use singleton)

---

### TASK-002: Add Prometheus Metrics for Retry, Circuit Breaker, and Rate Limiter
**Effort:** 8 h | **File:** [task_002_prometheus_metrics_instrumentation.md](task_002_prometheus_metrics_instrumentation.md)

**Scope:**
- Create `backend/app/core/fhir/metrics.py` module
- Define Prometheus metrics:
  - `fhir_circuit_state{state}` — Gauge (CLOSED=0, HALF_OPEN=1, OPEN=2)
  - `fhir_retry_total{outcome}` — Counter (success, exhausted, no_retry_needed)
  - `fhir_rate_limited_total` — Counter (incremented when bucket empty and backoff occurs)
  - `fhir_fetch_duration_seconds{resource_type}` — Histogram
- Instrument circuit breaker state transitions
- Instrument retry decorator to increment counters
- Instrument rate limiter to count delays
- Export metrics to Cloud Monitoring (GCP Prometheus scrape)

**Acceptance Criteria Addressed:**
- US-018 DoD: Prometheus metrics for circuit breaker, retry, rate limiter

**Files Created:**
- `backend/app/core/fhir/metrics.py`

**Files Modified:**
- `backend/app/core/fhir/circuit_breaker.py` (add metric updates)
- `backend/app/core/fhir/rate_limiter.py` (add metric updates)
- `backend/app/core/fhir/client.py` (add fetch duration histogram)
- `backend/app/core/fhir/__init__.py` (exports)
- `backend/requirements.txt` (add prometheus_client if not present)

---

### TASK-003: Validate and Enhance Retry Logic with Selective Error Handling
**Effort:** 6 h | **File:** [task_003_retry_error_handling_validation.md](task_003_retry_error_handling_validation.md)

**Scope:**
- Review existing retry logic in `FHIRClient._fetch_with_retry()`
- Implement selective retry: ONLY retry on 5xx status codes, network timeouts, connection errors
- Do NOT retry on 4xx status codes (client errors) — log and raise immediately
- Add custom exception `FHIRClientError` for 4xx responses
- Exponential backoff: 1s, 2s, 4s (3 attempts total, matching US-018 AC)
- Log retry attempts at WARNING level with attempt count and delay
- Log exhausted retries at ERROR level

**Acceptance Criteria Addressed:**
- AC Scenario 1 (retry succeeds after one transient failure)
- Technical Note: Retry should NOT retry on 4xx

**Files Modified:**
- `backend/app/core/fhir/exceptions.py` (add FHIRClientError)
- `backend/app/core/fhir/client.py` (enhance _fetch_with_retry logic)
- `backend/app/core/fhir/__init__.py` (export FHIRClientError)

---

### TASK-004: Comprehensive Unit Tests for Resilience Patterns with Edge Cases
**Effort:** 8 h | **File:** [task_004_comprehensive_resilience_tests.md](task_004_comprehensive_resilience_tests.md)

**Scope:**
- Create test suite for circuit breaker (12 tests):
  - Open after 10 consecutive failures in 60s window
  - HALF_OPEN probe after 120s cooldown
  - Close after successful probe
  - Remain OPEN after failed probe
  - Window expiry resets failure count
  - Thread-safety of state transitions
- Create test suite for retry logic (8 tests):
  - Success after 1 transient failure (HTTP 503)
  - Success after 2 transient failures
  - Exhausted retries after 3 failures
  - No retry on 4xx errors (HTTP 400, 404)
  - Network timeout triggers retry
  - Connection error triggers retry
- Create test suite for rate limiter (6 tests):
  - Delay on 101st request within 60s
  - Token refill over time
  - Exponential backoff when bucket empty
  - Thread-safety of token consumption
- Test Prometheus metrics increments for all scenarios
- Mock HTTP requests with `respx` (no real FHIR server calls)
- Achieve ≥95% code coverage for resilience modules

**Acceptance Criteria Addressed:**
- AC Scenario 1, 2, 3, 4 (all scenarios tested)

**Files Created:**
- `backend/tests/unit/core/fhir/test_circuit_breaker_resilience.py`
- `backend/tests/unit/core/fhir/test_retry_logic.py`
- `backend/tests/unit/core/fhir/test_rate_limiter_resilience.py`
- `backend/tests/unit/core/fhir/test_resilience_metrics.py`

**Files Modified:**
- `backend/requirements-dev.txt` (add freezegun for time mocking if needed)

---

## Acceptance Criteria Coverage Matrix

| AC Scenario | TASK-001 | TASK-002 | TASK-003 | TASK-004 |
|-------------|----------|----------|----------|----------|
| AC Scenario 1: Retry succeeds after one transient failure | | | ✓ | ✓ (test) |
| AC Scenario 2: Circuit breaker opens after 10 consecutive failures | ✓ | | | ✓ (test) |
| AC Scenario 3: Circuit breaker probes after 120s | ✓ | | | ✓ (test) |
| AC Scenario 4: Rate limiter enforces 100 req/min per instance | | | | ✓ (test) |
| DoD: Prometheus metrics for circuit, retry, rate limiter | | ✓ | | ✓ (test) |

---

## Definition of Done Checklist

### US-018 Overall DoD

- [ ] `@retry(max_attempts=3, backoff=[1, 2, 4])` decorator applied to all FHIR fetch methods (TASK-003)
- [ ] Circuit breaker implemented using async-compatible implementation (custom asyncio) (TASK-001)
- [ ] Circuit breaker thresholds: 10 failures / 60s window → OPEN; 120s reset timeout (TASK-001)
- [ ] Circuit breaker state persisted in module-level singleton (per Cloud Run instance) (TASK-001)
- [ ] Token bucket rate limiter: 100 tokens/minute refill, applied globally per FHIR client instance (US-017/TASK-002 — validated in TASK-004)
- [ ] Unit tests: (a) retry on transient error, (b) circuit open after threshold, (c) circuit probe logic, (d) rate limiter delay (TASK-004)
- [ ] Prometheus metrics: `fhir_circuit_state`, `fhir_retry_total`, `fhir_rate_limited_total` (TASK-002)
- [ ] Code reviewed and approved (All tasks)

---

## Implementation Order

```
TASK-001 (Circuit breaker singleton state)
    ↓
TASK-002 (Prometheus metrics instrumentation)
    ↓
TASK-003 (Retry logic validation and selective error handling)
    ↓
TASK-004 (Comprehensive unit tests for all resilience patterns)
```

---

## Technical Notes

### Module Structure (Enhancements to US-017)

```
backend/app/core/fhir/
├── __init__.py              # Public exports (add FHIRClientError, metrics)
├── exceptions.py            # Add FHIRClientError for 4xx responses
├── metrics.py               # NEW: Prometheus metrics for resilience patterns
├── circuit_breaker.py       # MODIFIED: Module-level singleton + metrics
├── rate_limiter.py          # MODIFIED: Add metrics
└── client.py                # MODIFIED: Selective retry + metrics
```

### Test Structure

```
backend/tests/unit/core/fhir/
├── test_circuit_breaker_resilience.py   # 12 tests (TASK-004)
├── test_retry_logic.py                  # 8 tests (TASK-004)
├── test_rate_limiter_resilience.py      # 6 tests (TASK-004)
└── test_resilience_metrics.py           # 4 tests (TASK-004)
```

### Prometheus Metrics Schema

```python
# fhir_circuit_state — Gauge (0=CLOSED, 1=HALF_OPEN, 2=OPEN)
fhir_circuit_state 0

# fhir_retry_total — Counter
fhir_retry_total{outcome="success"} 42
fhir_retry_total{outcome="exhausted"} 3
fhir_retry_total{outcome="no_retry_needed"} 150

# fhir_rate_limited_total — Counter
fhir_rate_limited_total 5

# fhir_fetch_duration_seconds — Histogram
fhir_fetch_duration_seconds_bucket{resource_type="Patient",le="0.1"} 120
fhir_fetch_duration_seconds_bucket{resource_type="Patient",le="0.5"} 200
```

### Circuit Breaker State Machine

```
CLOSED ──(10 failures in 60s)──> OPEN
   ↑                                │
   │                                │ (120s cooldown)
   │                                ↓
   └──(probe succeeds)────── HALF_OPEN
                                    │
                (probe fails) ──────┘
```

### Retry Logic Decision Tree

```
HTTP Response
    ├─ 2xx → Success (no retry)
    ├─ 4xx → FHIRClientError (no retry, log ERROR)
    └─ 5xx → Retry with backoff [1s, 2s, 4s]

Network Error
    ├─ Connection refused → Retry
    ├─ Timeout → Retry
    └─ DNS failure → Retry
```

---

## Architecture Integration Requirements Coverage

| AIR | Requirement | Implementation |
|-----|-------------|----------------|
| AIR-011 | FHIR resource fetching | TASK-003 (retry), TASK-001 (circuit breaker) |
| AIR-013 | FHIR rate limiting | US-017/TASK-002 (validated in TASK-004) |

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-017 | Story | FHIR fetch methods with basic resilience patterns must exist |
| prometheus_client | Package | Prometheus Python client library |
| respx | Package | Already added for US-016/US-017 tests |
| freezegun | Package | Time mocking for circuit breaker cooldown tests |

---

## Effort Estimation Rationale

- **TASK-001 (6h):** Singleton refactor requires careful state management and testing
- **TASK-002 (8h):** Instrumentation across 3 modules + metric definition + validation
- **TASK-003 (6h):** Selective retry logic + exception handling + validation
- **TASK-004 (8h):** 30+ unit tests covering all edge cases and metrics validation

**Total: 28 hours** ≈ 3.5 story points. Rounded to **3 story points** assuming solid US-017 foundation.

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| US-017 implementation gaps | Validate US-017 TASK-002 completion before starting TASK-001 |
| Prometheus client library conflicts | Pin `prometheus_client>=0.20.0` in requirements.txt |
| Circuit breaker race conditions | Comprehensive thread-safety tests in TASK-004 |
| Metrics cardinality explosion | Limit label values to known set (resource_type, outcome, state) |

---

## Upstream User Stories

- **US-017:** Fetch & Validate FHIR R4 Resources with Typed Pydantic Models (provides base FHIRClient)

---

## Acceptance Validation

All acceptance criteria will be validated through:
1. **TASK-004 unit tests** covering all 4 scenarios
2. **Code review** verifying decorator application and metric export
3. **Integration test** (manual) confirming Cloud Monitoring metric ingestion
4. **Load test** (future) validating rate limiter under 100 req/min load

---
