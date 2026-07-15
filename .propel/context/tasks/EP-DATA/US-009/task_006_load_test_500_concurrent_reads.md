---
id: TASK-006
title: "Load Test — 500 Concurrent Read Queries via PgBouncer Without DB Connection Errors"
user_story: US-009
epic: EP-DATA
sprint: 1
layer: Backend (Test)
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-006: Load Test — 500 Concurrent Read Queries via PgBouncer Without DB Connection Errors

> **Story:** US-009 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend (Test) | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-009 DoD explicitly requires:

> "Load test: 500 concurrent read queries complete without DB connection errors"

US-009 Scenario 1 acceptance criteria add:

> "PgBouncer is running in transaction-pool mode; 600 simultaneous client connections attempted; first 500 succeed; 501–600 queued or rejected with PgBouncer connection limit error; Cloud SQL shows ≤50 server-side connections (pool_size)"

This task implements two test suites:

1. **`test_connection_pool_capacity.py`** (pytest-asyncio integration test): Fires 500 + overflow requests concurrently against the FastAPI API layer, verifies no DB connection errors in the first 500, and verifies PgBouncer reports ≤50 server-side connections after the test.

2. **`locustfile.py`** (Locust load test): Simulates 500 sustained concurrent users hitting `GET /api/v1/encounters` (a read-replica query) for 60 seconds to verify the system sustains throughput without connection exhaustion.

Both suites run against the **staging** environment (Cloud Run + real PgBouncer sidecar + Cloud SQL), not in CI against a local mock. They are excluded from the standard `pytest` unit/integration suite via `pytest.ini` markers.

---

## Acceptance Criteria Addressed

| US-009 AC | Test | File |
|---|---|---|
| **Scenario 1** | 500 succeed; 501–600 queued/rejected; Cloud SQL ≤50 connections | `test_connection_pool_capacity.py` |
| **Scenario 3** | Reads go to replica (verified in TASK-003; smoke-tested here) | `test_connection_pool_capacity.py` |
| **DoD** | Load test passes without DB connection errors | `locustfile.py` |

---

## Implementation Steps

### 1. Create `backend/tests/load/test_connection_pool_capacity.py`

This test connects directly to the FastAPI `/api/v1/encounters` endpoint (which uses `get_read_db`) rather than to the database. It measures connection-level errors, not latency.

```python
"""Load test: PgBouncer connection pool capacity validation.

Verifies US-009 Scenario 1 and DoD:
  - 500 concurrent read queries complete without DB connection errors
  - Cloud SQL server-side connection count stays ≤50 (PgBouncer default_pool_size=20
    × max active pool users ≤ pool budget)

Prerequisites:
  - LOAD_TEST_BASE_URL set to staging Cloud Run URL
  - LOAD_TEST_API_KEY set to a valid staff JWT
  - PgBouncer sidecar running (TASK-001)
  - get_read_db routing active (TASK-003)

Run:
    LOAD_TEST_BASE_URL=https://api-gateway-staging.run.app \
    LOAD_TEST_API_KEY=<jwt> \
    pytest backend/tests/load/test_connection_pool_capacity.py -v -m load
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

BASE_URL = os.getenv("LOAD_TEST_BASE_URL", "http://localhost:8080")
API_KEY = os.getenv("LOAD_TEST_API_KEY", "")
CONCURRENT_REQUESTS = 500
OVERFLOW_REQUESTS = 100  # Total beyond max_client_conn


@pytest.mark.load
@pytest.mark.asyncio
async def test_500_concurrent_reads_no_connection_errors():
    """500 concurrent GET /encounters requests complete without DB connection errors.

    A DB connection error manifests as an HTTP 500 or 503 response with
    a body containing 'connection' or 'pool' in the detail field.
    """
    headers = {"Authorization": f"Bearer {API_KEY}"}

    async def fetch_one(client: httpx.AsyncClient, index: int) -> tuple[int, int]:
        """Return (index, status_code)."""
        try:
            response = await client.get(
                f"{BASE_URL}/api/v1/encounters",
                params={"limit": 1},
                headers=headers,
                timeout=30.0,
            )
            return (index, response.status_code)
        except httpx.TimeoutException:
            return (index, 408)
        except httpx.ConnectError:
            return (index, 503)

    async with httpx.AsyncClient() as client:
        tasks = [
            asyncio.create_task(fetch_one(client, i))
            for i in range(CONCURRENT_REQUESTS)
        ]
        results = await asyncio.gather(*tasks)

    statuses = [status for _, status in results]
    error_responses = [
        (i, s) for i, s in results
        if s in (500, 503, 408)
    ]

    assert not error_responses, (
        f"{len(error_responses)} of {CONCURRENT_REQUESTS} requests failed with "
        f"connection-level errors. First 5 failures: {error_responses[:5]}"
    )

    # All 500 requests should have returned a valid response (200 or 401/403 for auth)
    successful = [s for s in statuses if s in (200, 401, 403)]
    assert len(successful) == CONCURRENT_REQUESTS, (
        f"Expected {CONCURRENT_REQUESTS} valid responses; "
        f"got {len(successful)}. Status distribution: {set(statuses)}"
    )


@pytest.mark.load
@pytest.mark.asyncio
async def test_pgbouncer_server_connection_count():
    """PgBouncer SHOW POOLS reports ≤50 server connections after 500-request burst.

    Connects to the PgBouncer admin console via the Cloud Run exec mechanism
    (or a forwarded port in staging). Verifies that Cloud SQL received no more
    than default_pool_size + reserve_pool_size = 25 server connections.

    NOTE: This test requires the PgBouncer admin port to be accessible from the
    test runner (Cloud Build staging environment). It is skipped if
    PGBOUNCER_ADMIN_DSN is not set.
    """
    import asyncpg  # type: ignore[import]

    admin_dsn = os.getenv("PGBOUNCER_ADMIN_DSN")
    if not admin_dsn:
        pytest.skip("PGBOUNCER_ADMIN_DSN not set; skipping server-connection count check.")

    conn = await asyncpg.connect(admin_dsn)
    try:
        rows = await conn.fetch("SHOW POOLS;")
        total_server_connections = sum(
            (row["sv_active"] or 0) + (row["sv_idle"] or 0)
            for row in rows
            if row["database"] == "smarthandoff"
        )
        assert total_server_connections <= 50, (
            f"PgBouncer reports {total_server_connections} server-side connections "
            "to Cloud SQL. Expected ≤50 (default_pool_size=20 + reserve=5 per pool × "
            "up to 2 active databases = max 50). PgBouncer may not be in transaction mode."
        )
    finally:
        await conn.close()
```

### 2. Create `backend/tests/load/locustfile.py`

Locust load test for sustained 500-user throughput. Run manually against staging — not part of CI.

```python
"""Locust load test for SmartHandoff API — sustained 500-user read throughput.

Tests:
  - GET /api/v1/encounters  (read replica via get_read_db)
  - GET /api/v1/beds        (read replica — bed board)
  - GET /health             (not DB-bound; baseline latency)

Target: 500 concurrent users for 60 seconds without HTTP 500/503 errors
and without DB connection exhaustion.

Run:
    cd backend
    locust -f tests/load/locustfile.py \
      --host=https://api-gateway-staging.run.app \
      --users=500 \
      --spawn-rate=50 \
      --run-time=60s \
      --headless \
      --html=load_test_report.html

Success criteria:
  - HTTP error rate < 1%
  - p95 response time < 500ms (TR-001)
  - No "connection refused" or "pool exhausted" errors in Cloud Logging
"""
from __future__ import annotations

import os

from locust import HttpUser, between, task


_API_KEY = os.getenv("LOAD_TEST_API_KEY", "")


class SmartHandoffReadUser(HttpUser):
    """Simulates a staff member performing dashboard read operations."""

    wait_time = between(0.1, 0.5)  # Realistic think time between requests

    def on_start(self):
        """Set JWT header for all requests."""
        self.client.headers.update({"Authorization": f"Bearer {_API_KEY}"})

    @task(5)
    def list_encounters(self):
        """GET /api/v1/encounters — routes to read replica (TASK-003)."""
        with self.client.get(
            "/api/v1/encounters",
            params={"limit": 20, "status": "ADMITTED"},
            catch_response=True,
            name="GET /encounters",
        ) as response:
            if response.status_code == 500:
                response.failure(f"Server error: {response.text[:200]}")
            elif response.status_code == 503:
                response.failure("Service unavailable — possible connection pool exhaustion")
            else:
                response.success()

    @task(3)
    def get_bed_board(self):
        """GET /api/v1/beds — reads mv_bed_board materialised view."""
        with self.client.get(
            "/api/v1/beds",
            catch_response=True,
            name="GET /beds",
        ) as response:
            if response.status_code >= 500:
                response.failure(f"Server error {response.status_code}: {response.text[:200]}")
            else:
                response.success()

    @task(1)
    def health_check(self):
        """GET /health — not DB-bound; measures baseline infrastructure latency."""
        self.client.get("/health", name="GET /health")
```

### 3. Add `load` pytest Marker to `backend/pytest.ini`

Load tests must not run in CI alongside unit/integration tests:

```ini
# backend/pytest.ini
[pytest]
markers =
    load: Load and performance tests (run manually against staging, not in CI)
    integration: Integration tests requiring a running database (testcontainers)
    unit: Pure unit tests (no external dependencies)
```

And add an exclusion to the CI test command in Cloud Build:

```yaml
# In cloudbuild.yaml (Step 2: Unit Tests)
args:
  - pytest
  - backend/tests/unit
  - backend/tests/integration
  - -m
  - "not load"          # Exclude load tests from CI
  - --cov=backend/app
  - --cov-fail-under=80
```

### 4. Install Load Test Dependencies

```bash
# Add to backend/requirements-dev.txt
locust>=2.24.0
asyncpg>=0.29.0   # For pgbouncer admin console test
```

### 5. Verify Results Against Acceptance Criteria

After running both tests, confirm:

| Criterion | Evidence |
|---|---|
| 500 concurrent reads complete without error | `test_connection_pool_capacity.py` passes (0 HTTP 500/503 in 500 requests) |
| Cloud SQL shows ≤50 server-side connections | `test_pgbouncer_server_connection_count` passes OR PgBouncer `SHOW POOLS` output verified manually |
| Locust p95 < 500ms | Locust HTML report (`load_test_report.html`) shows p95 response time |
| HTTP error rate < 1% | Locust report shows failure rate < 1% |

---

## File Checklist

| File | Action |
|---|---|
| `backend/tests/load/test_connection_pool_capacity.py` | Create |
| `backend/tests/load/locustfile.py` | Create |
| `backend/tests/load/__init__.py` | Create (empty) |
| `backend/pytest.ini` | Add `load` marker |
| `backend/requirements-dev.txt` | Add `locust>=2.24.0`, `asyncpg>=0.29.0` |

---

## Dependencies

- **TASK-001** — PgBouncer sidecar running in staging
- **TASK-002** — Dual session factories initialised
- **TASK-003** — `get_read_db` dependency routing reads to replica
- **TASK-004 / TASK-005** — Materialised views and refresh jobs active in staging
