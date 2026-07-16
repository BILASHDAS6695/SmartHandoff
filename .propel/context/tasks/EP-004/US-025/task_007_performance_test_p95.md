---
id: TASK-007
title: "Performance Test — p95 Discharge Summary Generation Latency <30 Seconds (100 Cases)"
user_story: US-025
epic: EP-004
sprint: 2
layer: Test — Performance
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-004, TASK-005, TASK-006]
---

# TASK-007: Performance Test — p95 Discharge Summary Generation Latency <30 Seconds (100 Cases)

> **Story:** US-025 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Test — Performance | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The 30-second p95 SLA (Scenario 1) must be validated by a dedicated performance test that:
1. Drives 100 concurrent discharge summary generation calls against the `DocumentationAgent`
2. Measures wall-clock latency per run (FHIR fetch → prompt render → Gemini call → DB write)
3. Computes the p95 latency across all 100 runs
4. Asserts p95 < 30,000 ms

The test runs against the staging environment (`STAGE`) with real Vertex AI Gemini 1.5 Pro calls and a seeded Cloud SQL database. It does not use mocks for the LLM or FHIR layers (those are unit tests).

A lightweight fixture provides 100 distinct test encounters (varying diagnosis count: 1–8, medication count: 1–12) to simulate realistic prompt size variance.

---

## Acceptance Criteria Addressed

| US-025 AC | Requirement |
|---|---|
| **Scenario 1** | p95 generation latency <30 seconds across 100 test cases |

---

## Implementation Steps

### 1. Create `tests/performance/test_discharge_summary_p95.py`

```python
"""
Performance test: p95 discharge summary generation latency < 30 seconds.

Test environment: staging (STAGE)
LLM: Vertex AI Gemini 1.5 Pro (real API calls)
FHIR: Staging FHIR R4 server with seeded encounters
Concurrency: asyncio.gather (10 concurrent batches of 10)

Run with:
    pytest tests/performance/test_discharge_summary_p95.py \
        --env=staging \
        -v \
        --timeout=600
"""
from __future__ import annotations

import asyncio
import statistics
import time
from typing import List

import pytest

from agents.documentation.agent import DocumentationAgent
from tests.performance.fixtures.encounter_factory import build_test_encounters


# ---- Configuration --------------------------------------------------------
P95_LATENCY_THRESHOLD_MS = 30_000   # 30 seconds
TOTAL_TEST_CASES = 100
BATCH_SIZE = 10                      # 10 concurrent generations per batch


# ---- Fixtures -------------------------------------------------------------

@pytest.fixture(scope="module")
def test_encounters():
    """
    Generate 100 test EncounterContext instances with varying complexity:
    - diagnosis count: 1–8 (uniformly distributed)
    - medication count: 1–12 (uniformly distributed)
    - length of stay: 1–14 days
    """
    return build_test_encounters(count=TOTAL_TEST_CASES)


@pytest.fixture(scope="module")
def documentation_agent(staging_fhir_client, staging_doc_repository, staging_settings):
    """Real DocumentationAgent wired to staging dependencies."""
    return DocumentationAgent(
        fhir_client=staging_fhir_client,
        document_repository=staging_doc_repository,
        project_id=staging_settings.GCP_PROJECT_ID,
        location=staging_settings.GCP_REGION,
    )


# ---- Performance Harness --------------------------------------------------

async def _run_single(agent: DocumentationAgent, event: dict) -> int:
    """Run one generation and return wall-clock milliseconds."""
    start = time.monotonic_ns()
    await agent.process(event)
    return (time.monotonic_ns() - start) // 1_000_000


async def _run_batch(agent: DocumentationAgent, events: list[dict]) -> list[int]:
    """Run a batch of events concurrently; return list of latencies in ms."""
    return list(await asyncio.gather(*[_run_single(agent, e) for e in events]))


# ---- Test -----------------------------------------------------------------

@pytest.mark.performance
@pytest.mark.asyncio
@pytest.mark.timeout(600)  # 10-minute overall test timeout
async def test_p95_discharge_summary_latency(documentation_agent, test_encounters):
    """
    Assert that the 95th-percentile discharge summary generation latency
    is under 30,000 ms across 100 test cases.
    """
    all_latencies: List[int] = []

    # Run in batches of BATCH_SIZE to avoid overwhelming staging Gemini quota
    for batch_start in range(0, TOTAL_TEST_CASES, BATCH_SIZE):
        batch = test_encounters[batch_start : batch_start + BATCH_SIZE]
        events = [
            {"event_type": "A03", "encounter_id": enc.encounter_id, "occurred_at": "2026-07-16T10:00:00Z"}
            for enc in batch
        ]
        batch_latencies = await _run_batch(documentation_agent, events)
        all_latencies.extend(batch_latencies)

        # Progress log for CI visibility
        completed = min(batch_start + BATCH_SIZE, TOTAL_TEST_CASES)
        current_p95 = _percentile(all_latencies, 95)
        print(f"  [{completed}/{TOTAL_TEST_CASES}] running p95 = {current_p95} ms")

    # ---- Assertions -------------------------------------------------------
    assert len(all_latencies) == TOTAL_TEST_CASES, (
        f"Expected {TOTAL_TEST_CASES} latency samples, got {len(all_latencies)}"
    )

    p95_ms = _percentile(all_latencies, 95)
    p50_ms = _percentile(all_latencies, 50)
    max_ms = max(all_latencies)
    min_ms = min(all_latencies)
    mean_ms = int(statistics.mean(all_latencies))

    # Report for CI output
    print(
        f"\n=== Discharge Summary Generation Latency Report ===\n"
        f"  Samples : {TOTAL_TEST_CASES}\n"
        f"  p50     : {p50_ms} ms\n"
        f"  p95     : {p95_ms} ms  (threshold: {P95_LATENCY_THRESHOLD_MS} ms)\n"
        f"  mean    : {mean_ms} ms\n"
        f"  min     : {min_ms} ms\n"
        f"  max     : {max_ms} ms\n"
        f"  fallback count: {sum(1 for l in all_latencies if l >= 25_000)}\n"
    )

    assert p95_ms < P95_LATENCY_THRESHOLD_MS, (
        f"p95 latency {p95_ms} ms exceeds threshold {P95_LATENCY_THRESHOLD_MS} ms. "
        f"Histogram: min={min_ms}ms, p50={p50_ms}ms, p95={p95_ms}ms, max={max_ms}ms"
    )


def _percentile(data: List[int], percentile: int) -> int:
    """Compute the Nth percentile from a list of integer millisecond values."""
    if not data:
        raise ValueError("Cannot compute percentile of empty list")
    sorted_data = sorted(data)
    index = int(len(sorted_data) * percentile / 100)
    return sorted_data[min(index, len(sorted_data) - 1)]
```

### 2. Create `tests/performance/fixtures/encounter_factory.py`

```python
"""
Factory for generating deterministic test EncounterContext instances
with varying clinical complexity for performance testing.
"""
from __future__ import annotations

import random
from typing import List

from agents.documentation.fhir_fetcher import (
    DiagnosisContext, EncounterContext, MedicationContext,
)

# Sample ICD-10 codes representing common inpatient diagnoses
_SAMPLE_DIAGNOSES = [
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("I10", "Essential (primary) hypertension"),
    ("I50.9", "Heart failure, unspecified"),
    ("J18.9", "Pneumonia, unspecified organism"),
    ("N18.3", "Chronic kidney disease, stage 3"),
    ("K92.1", "Melena"),
    ("F32.1", "Major depressive disorder, single episode, moderate"),
    ("M54.5", "Low back pain"),
]

# Sample generic drug names
_SAMPLE_MEDICATIONS = [
    ("metformin", "500 mg", "twice daily", "oral", "860975"),
    ("lisinopril", "10 mg", "once daily", "oral", "29046"),
    ("atorvastatin", "40 mg", "once daily at bedtime", "oral", "617310"),
    ("furosemide", "40 mg", "once daily", "oral", "202991"),
    ("amlodipine", "5 mg", "once daily", "oral", "17767"),
    ("omeprazole", "20 mg", "once daily before breakfast", "oral", "40790"),
    ("aspirin", "81 mg", "once daily", "oral", "1191"),
    ("warfarin", "5 mg", "once daily", "oral", "11289"),
    ("insulin glargine", "20 units", "once daily at bedtime", "subcutaneous", "274783"),
    ("albuterol", "2.5 mg", "every 4-6 hours as needed", "inhaled", "435"),
    ("prednisone", "20 mg", "once daily", "oral", "8787"),
    ("sertraline", "50 mg", "once daily", "oral", "36437"),
]


def build_test_encounters(count: int, seed: int = 42) -> List[EncounterContext]:
    """
    Generate `count` EncounterContext instances with deterministic randomness.

    Args:
        count: Number of encounter contexts to generate.
        seed: Random seed for reproducibility across test runs.

    Returns:
        List of EncounterContext instances with varying diagnosis and
        medication counts.
    """
    rng = random.Random(seed)
    encounters = []

    for i in range(count):
        num_diagnoses = rng.randint(1, 8)
        num_medications = rng.randint(1, 12)
        los = rng.randint(1, 14)

        selected_dx = rng.choices(_SAMPLE_DIAGNOSES, k=num_diagnoses)
        selected_meds = rng.choices(_SAMPLE_MEDICATIONS, k=num_medications)

        diagnoses = [
            DiagnosisContext(
                icd10_code=dx[0],
                description=dx[1],
                is_primary=(j == 0),
            )
            for j, dx in enumerate(selected_dx)
        ]
        medications = [
            MedicationContext(
                drug_name=med[0],
                dose=med[1],
                frequency=med[2],
                route=med[3],
                rxnorm_code=med[4],
            )
            for med in selected_meds
        ]

        encounters.append(
            EncounterContext(
                encounter_id=f"PERF-ENC-{i + 1:04d}",
                admission_reason=selected_dx[0][1],
                encounter_type="inpatient",
                discharge_disposition="Home",
                length_of_stay_days=los,
                diagnoses=diagnoses,
                medications=medications,
            )
        )

    return encounters
```

### 3. Add `pytest.ini` marker

```ini
[pytest]
markers =
    performance: marks tests as performance tests (deselect with '-m "not performance"')
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/tests/performance/test_discharge_summary_p95.py` |
| **Create** | `backend/tests/performance/fixtures/encounter_factory.py` |
| **Update** | `backend/pytest.ini` (add `performance` marker) |

---

## Definition of Done

- [ ] Performance test runs 100 cases (10 × batches of 10 concurrent calls) against staging
- [ ] p95 latency assertion: `< 30,000 ms` — test FAILS CI if exceeded
- [ ] Latency report printed (p50, p95, mean, min, max, fallback count)
- [ ] `EncounterFactory` generates deterministic encounters with 1–8 diagnoses and 1–12 medications
- [ ] Test tagged `@pytest.mark.performance`; excluded from unit test suite by default (`-m "not performance"`)
- [ ] CI pipeline runs this test in staging gate (not in PR unit test suite)

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-004 | Task | `DocumentationAgent.process()` is the system under test |
| TASK-005 | Task | Fallback logic active during test; fallback cases counted in report |
| TASK-006 | Task | `DocumentRepository.create_discharge_document()` must write to staging DB |
| Staging environment | Infra | Staging Vertex AI quota must support 10 concurrent Gemini calls |
