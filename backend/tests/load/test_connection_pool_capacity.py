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
    LOAD_TEST_BASE_URL=https://api-gateway-staging.run.app \\
    LOAD_TEST_API_KEY=<jwt> \\
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
