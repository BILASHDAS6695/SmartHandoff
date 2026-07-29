"""Locust load test for POST /api/v1/chat (US-043 AC Scenario 1).

Target: p95 response latency < 3,000 ms at 100 concurrent simulated patients.

Prerequisites:
    - Staging patient JWTs available in STAGING_PATIENT_JWTS env var
      (JSON list of 100 encounter-scoped tokens from provision_test_patients.py)
    - TARGET_HOST env var set to staging API base URL

Run:
    locust -f locustfile.py --headless \
        --host $TARGET_HOST \
        --users 100 \
        --spawn-rate 10 \
        --run-time 70s \
        --html=load-test-report.html
"""
from __future__ import annotations

import json
import os
import random
import uuid

from locust import HttpUser, between, events, task
from locust.env import Environment

# Load patient JWTs at module import — provisioned by scripts/provision_test_patients.py
_PATIENT_JWTS: list[str] = json.loads(os.environ.get("STAGING_PATIENT_JWTS", "[]"))
_ENCOUNTER_IDS: list[str] = json.loads(os.environ.get("STAGING_ENCOUNTER_IDS", "[]"))

# Candidate chat messages representative of real patient queries
_SAMPLE_MESSAGES = [
    "What medications should I take at home?",
    "When can I shower after surgery?",
    "What foods should I avoid?",
    "When should I call the doctor?",
    "How often do I need to change my dressing?",
    "Is it normal to feel tired after discharge?",
    "What are my activity restrictions?",
    "When is my follow-up appointment?",
    "Can I drive after taking this medication?",
    "What side effects should I watch for?",
]


class ChatbotPatient(HttpUser):
    """Simulated patient sending chatbot queries via POST /api/v1/chat."""

    wait_time = between(0.5, 2.0)  # Think time between requests

    def on_start(self) -> None:
        """Assign a unique patient JWT and encounter_id to this user."""
        if not _PATIENT_JWTS or not _ENCOUNTER_IDS:
            raise RuntimeError(
                "STAGING_PATIENT_JWTS and STAGING_ENCOUNTER_IDS env vars must be set. "
                "Run scripts/provision_test_patients.py first."
            )
        idx = random.randint(0, len(_PATIENT_JWTS) - 1)
        self._jwt = _PATIENT_JWTS[idx]
        self._encounter_id = _ENCOUNTER_IDS[idx]
        self._session_id = str(uuid.uuid4())

    @task
    def send_chat_message(self) -> None:
        """Send a single chatbot question and record latency."""
        payload = {
            "message": random.choice(_SAMPLE_MESSAGES),
            "encounter_id": self._encounter_id,
            "session_id": self._session_id,
        }
        self.client.post(
            "/api/v1/chat",
            json=payload,
            headers={"Authorization": f"Bearer {self._jwt}"},
            catch_response=True,
            name="POST /api/v1/chat",
        )


@events.quitting.add_listener
def assert_p95_latency(environment: Environment, **kwargs) -> None:
    """Fail the load test if p95 latency exceeds the 3-second SLA.

    US-043 AC Scenario 1: p95 response latency must be < 3,000 ms.
    Locust exits with code 1 on assertion failure, blocking CI promotion.
    """
    stats = environment.stats.total
    p95_ms = stats.get_response_time_percentile(0.95)
    error_rate = stats.fail_ratio

    print(f"\n── Load Test Summary ──────────────────────────────────")
    print(f"  Total requests : {stats.num_requests}")
    print(f"  Failure rate   : {error_rate:.2%}")
    print(f"  p50 latency    : {stats.get_response_time_percentile(0.50):.0f} ms")
    print(f"  p95 latency    : {p95_ms:.0f} ms  (SLA: <3,000 ms)")
    print(f"  p99 latency    : {stats.get_response_time_percentile(0.99):.0f} ms")
    print(f"────────────────────────────────────────────────────────\n")

    if p95_ms >= 3_000:
        environment.process_exit_code = 1
        print(f"FAIL: p95 latency {p95_ms:.0f} ms ≥ 3,000 ms SLA (US-043 AC Scenario 1)")
    elif error_rate > 0.01:
        environment.process_exit_code = 1
        print(f"FAIL: error rate {error_rate:.2%} > 1% threshold")
    else:
        print(f"PASS: p95 latency {p95_ms:.0f} ms < 3,000 ms ✓  error rate {error_rate:.2%} < 1% ✓")
