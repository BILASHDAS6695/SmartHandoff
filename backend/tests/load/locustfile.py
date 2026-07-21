"""Locust load test for SmartHandoff API — sustained 500-user read throughput.

Tests:
  - GET /api/v1/encounters  (read replica via get_read_db)
  - GET /api/v1/beds        (read replica — bed board)
  - GET /health             (not DB-bound; baseline latency)

Target: 500 concurrent users for 60 seconds without HTTP 500/503 errors
and without DB connection exhaustion.

Run:
    cd backend
    locust -f tests/load/locustfile.py \\
      --host=https://api-gateway-staging.run.app \\
      --users=500 \\
      --spawn-rate=50 \\
      --run-time=60s \\
      --headless \\
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
