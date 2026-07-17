---
id: TASK-006
title: "Performance Test — p95 Response Latency <3s at 100 Concurrent Users"
user_story: US-043
epic: EP-008
sprint: 2
layer: Testing / Performance
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer
upstream: [US-043/TASK-004]
---

# TASK-006: Performance Test — p95 Response Latency <3s at 100 Concurrent Users

> **Story:** US-043 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Testing / Performance | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-043 AC Scenario 1 requires:

> *"A response is returned within 3 seconds for 95% of test queries (p95 latency measured in load test of 100 concurrent users)."*

This task implements a **Locust** load test against the staging `POST /api/v1/chat` endpoint with 100 concurrent simulated patients, each sending chat queries using their own JWT (encounter-scoped). The test runs for **60 seconds** at peak load and exports a summary asserting `response_time_percentile_95 < 3000ms`.

### Why Locust (not pytest-benchmark)

pytest-benchmark measures single-threaded Python call overhead. This test requires true concurrency — 100 simultaneous HTTP connections to the Cloud Run staging deployment, exercising the full stack including Gemini Flash, Redis, and Cloud SQL read replica. Locust's asyncio-based worker model is the appropriate tool.

### Test environment

- Target: Staging Cloud Run endpoint (`https://api-staging.smarthandoff.internal/api/v1/chat`)
- Auth: Staging patient JWTs generated via the test patient provisioning script (`scripts/provision_test_patients.py`) — encounter-scoped, 1-hour expiry
- Concurrency: 100 users (spawned at rate 10 users/second → full load at t=10s)
- Duration: 60 seconds at peak load (after ramp-up)
- Pass criteria: p95 latency < 3 000 ms; error rate < 1%

**Design references:**
- design.md §4.1 TR-006 — Chatbot response <3 seconds; p95 target
- design.md §9.2 — `comms-agent` Cloud Run: min=1, max=10, Concurrency=10
- US-043 AC Scenario 1 — p95 latency <3 seconds at 100 concurrent users
- US-043 DoD — performance test with p95 latency metric required

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Locust load test: 100 concurrent users; p95 response latency <3 000 ms |

---

## Implementation Steps

### 1. Create test directory and files

```bash
mkdir -p performance-tests/chat
touch performance-tests/chat/locustfile.py
touch performance-tests/chat/run_load_test.sh
touch performance-tests/chat/requirements.txt
```

### 2. Create `performance-tests/chat/requirements.txt`

```
locust==2.29.1
httpx==0.27.0
```

### 3. Implement `performance-tests/chat/locustfile.py`

```python
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
        with self.client.post(
            "/api/v1/chat",
            json=payload,
            headers={"Authorization": f"Bearer {self._jwt}"},
            catch_response=True,
            name="POST /api/v1/chat",
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "reply" not in data:
                    response.failure("Response missing 'reply' field")
                else:
                    response.success()
            elif response.status_code == 403:
                response.failure(f"Unexpected 403 — check JWT/encounter_id alignment")
            else:
                response.failure(f"Unexpected status: {response.status_code}")


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
```

### 4. Create `performance-tests/chat/run_load_test.sh`

```bash
#!/usr/bin/env bash
# Run the US-043 chatbot load test against staging.
# Usage: ./run_load_test.sh
# Prerequisites: STAGING_PATIENT_JWTS, STAGING_ENCOUNTER_IDS, TARGET_HOST env vars set.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

pip install -r requirements.txt --quiet

echo "Starting load test: 100 users, 70s run time (10s ramp + 60s steady state)"
locust -f locustfile.py --headless \
    --host "${TARGET_HOST:?TARGET_HOST not set}" \
    --users 100 \
    --spawn-rate 10 \
    --run-time 70s \
    --html="load-test-report-$(date +%Y%m%d-%H%M%S).html" \
    --csv="load-test-$(date +%Y%m%d-%H%M%S)"

echo "Load test complete. HTML report generated."
```

### 5. Register the load test in Cloud Build (staging gate)

Add to the existing Cloud Build pipeline (`cloudbuild.yaml`) after integration tests and before canary deploy:

```yaml
# US-043 — Chatbot p95 latency performance gate (staging)
- name: 'python:3.12-slim'
  id: 'perf-test-chat'
  entrypoint: 'bash'
  args: ['performance-tests/chat/run_load_test.sh']
  env:
    - 'TARGET_HOST=${_STAGING_API_HOST}'
    - 'STAGING_PATIENT_JWTS=$$STAGING_PATIENT_JWTS'
    - 'STAGING_ENCOUNTER_IDS=$$STAGING_ENCOUNTER_IDS'
  secretEnv: ['STAGING_PATIENT_JWTS', 'STAGING_ENCOUNTER_IDS']
```

---

## Pass Criteria

| Metric | Threshold | Source |
|--------|-----------|--------|
| p95 response latency | < 3 000 ms | US-043 AC Scenario 1 |
| Error rate | < 1% | General SLA |
| Total requests | ≥ 500 | Sufficient sample for p95 confidence |

---

## Definition of Done

- [ ] `performance-tests/chat/locustfile.py` created with `ChatbotPatient` user and `assert_p95_latency` quitting hook
- [ ] `performance-tests/chat/run_load_test.sh` created and executable (`chmod +x`)
- [ ] `performance-tests/chat/requirements.txt` created with locust pinned version
- [ ] Load test registered as a Cloud Build step after integration tests
- [ ] Load test exits with code 0 when p95 < 3 000 ms and error rate < 1%
- [ ] Load test exits with code 1 (blocking deploy) when thresholds are breached
- [ ] HTML report artifact uploaded to Cloud Storage for review
