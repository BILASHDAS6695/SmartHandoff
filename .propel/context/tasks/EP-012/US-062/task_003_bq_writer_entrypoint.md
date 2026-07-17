---
id: TASK-003
title: "BigQuery Idempotent Writer — WRITE_TRUNCATE Partition Load & Job Entrypoint"
user_story: US-062
epic: EP-012
sprint: 2
layer: Backend / Data
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, DR-017]
---

# TASK-003: BigQuery Idempotent Writer — WRITE_TRUNCATE Partition Load & Job Entrypoint

> **Story:** US-062 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

With schema, SQL reader, and de-identification in place (TASK-001, TASK-002), this task wires everything together into:

- An idempotent BigQuery writer that uses `WRITE_TRUNCATE` to replace the `admit_date` date partition on every run
- The `main.py` job entrypoint with structured logging, timing, and non-zero exit on failure (required for Cloud Monitoring alerting in TASK-005)
- A `Dockerfile` for the Cloud Run job container

**Design references:**
- US-062 AC Scenario 3 — `WRITE_TRUNCATE` for the date partition; re-runs replace, not append
- US-062 Technical Notes — `TimePartitioning(type_=TimePartitioningType.DAY, field="admit_date")`
- design.md §3.1 — Cloud Run stateless jobs
- design.md ADR-002 — Cloud Run for compute; per-request billing

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Job entrypoint runs end-to-end; export runtime logged to Cloud Logging |
| Scenario 3 | `WRITE_TRUNCATE` write disposition replaces partition on re-run — no duplicate rows |
| Scenario 4 | `main.py` exits with `sys.exit(1)` on exception — Cloud Monitoring alert triggered by non-zero exit |

---

## Implementation Steps

### 1. Implement BigQuery writer in `jobs/bq-export/app/bq_writer.py`

```python
"""Idempotent BigQuery partition writer for de-identified encounter data.

Write strategy:
    - WriteDisposition.WRITE_TRUNCATE on the specific admit_date partition
    - Ensures re-runs for the same date REPLACE rows, never APPEND
    - Partition decorator set to the target date to scope truncation to that
      partition only (prevents overwriting other date partitions)

Design refs:
    US-062 AC Scenario 3 — WRITE_TRUNCATE; idempotent export
    US-062 Technical Notes — TimePartitioning by admit_date
    US-062 DoD — WRITE_TRUNCATE for the date partition on each run
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig, WriteDisposition

from app.config import Config
from app.schema import (
    ENCOUNTERS_DEIDENTIFIED_SCHEMA,
    ENCOUNTERS_DEIDENTIFIED_TIME_PARTITIONING,
    assert_no_phi,
)

logger = logging.getLogger(__name__)


def write_partition(
    client: bigquery.Client,
    rows: list[dict[str, Any]],
    target_date: datetime.date,
) -> int:
    """Write de-identified rows to the BigQuery encounters_deidentified table.

    Uses WRITE_TRUNCATE scoped to the admit_date partition so that:
      - Re-running the job for the same date replaces rather than appends
      - Other date partitions are unaffected

    Args:
        client: Authenticated BigQuery client.
        rows: De-identified row dicts (output of deidentify.deidentify_batch()).
        target_date: The admit_date partition being written; used as the
                     partition decorator in the destination table reference.

    Returns:
        Number of rows written to BigQuery.

    Raises:
        ValueError: If any PHI column is detected in any row (pre-write guard).
        google.cloud.exceptions.GoogleCloudError: On BigQuery API errors.
    """
    if not rows:
        logger.info(
            "No rows to write — skipping BigQuery load",
            extra={"target_date": str(target_date)},
        )
        return 0

    # Pre-write PHI guard — second line of defence after deidentify_row()
    assert_no_phi(list(rows[0].keys()))

    # Partition decorator: table$YYYYMMDD scopes WRITE_TRUNCATE to one partition
    partition_str = target_date.strftime("%Y%m%d")
    destination = (
        f"{Config.GCP_PROJECT_ID}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"
        f"${partition_str}"
    )

    job_config = LoadJobConfig(
        schema=ENCOUNTERS_DEIDENTIFIED_SCHEMA,
        time_partitioning=ENCOUNTERS_DEIDENTIFIED_TIME_PARTITIONING,
        write_disposition=WriteDisposition.WRITE_TRUNCATE,
        # Fail the job on unknown fields to catch schema drift early
        ignore_unknown_values=False,
    )

    load_job = client.load_table_from_json(
        rows, destination, job_config=job_config
    )
    load_job.result()  # Block until the load job completes

    destination_table = client.get_table(
        f"{Config.GCP_PROJECT_ID}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"
    )
    logger.info(
        "BigQuery partition write complete",
        extra={
            "target_date": str(target_date),
            "rows_written": len(rows),
            "table_total_rows": destination_table.num_rows,
            "partition": partition_str,
        },
    )
    return len(rows)
```

### 2. Implement job entrypoint in `jobs/bq-export/main.py`

```python
"""Nightly BigQuery export job entrypoint.

Executed as a Cloud Run job triggered by Cloud Scheduler at 02:00 UTC daily.

Exit behaviour:
    - Exit code 0 on success
    - Exit code 1 on any exception (enables Cloud Monitoring alert via
      Cloud Run job failure detection — US-062 AC Scenario 4)

Structured logging:
    All log records use key=value extras to produce structured JSON logs
    in Cloud Logging. Export runtime is logged on completion.

Design refs:
    US-062 AC Scenario 1 — nightly export; runtime logged to Cloud Logging
    US-062 AC Scenario 4 — non-zero exit triggers Cloud Monitoring alert
    design.md §3.1 — Cloud Run jobs; stateless execution
"""
from __future__ import annotations

import logging
import sys
import time

from app.bq_client import ensure_table_exists, get_bq_client
from app.bq_writer import write_partition
from app.config import Config
from app.date_utils import get_target_date
from app.deidentify import deidentify_batch
from app.sql_reader import fetch_encounters

# Structured JSON logging — Cloud Run captures stdout as Cloud Logging entries
logging.basicConfig(
    level=logging.INFO,
    format='{"severity":"%(levelname)s","message":"%(message)s","logger":"%(name)s"}',
    stream=sys.stdout,
)
logger = logging.getLogger("bq_export_job")


def run() -> None:
    """Execute the full nightly export pipeline.

    Pipeline stages:
      1. Resolve target date (yesterday UTC or EXPORT_DATE_OVERRIDE)
      2. Ensure BigQuery table and partition exist
      3. Fetch encounter rows from Cloud SQL (PHI-excluded at SQL level)
      4. Apply de-identification (SHA-256 hash encounter_id; assert no PHI)
      5. Write to BigQuery with WRITE_TRUNCATE on admit_date partition
    """
    start_time = time.monotonic()
    target_date = get_target_date()

    logger.info(
        "BigQuery nightly export job started",
        extra={"target_date": str(target_date), "project": Config.GCP_PROJECT_ID},
    )

    # Stage 1: Ensure BigQuery table exists (idempotent)
    bq_client = get_bq_client()
    ensure_table_exists(bq_client)

    # Stage 2: Fetch encounter data from Cloud SQL (no PHI in result set)
    rows = fetch_encounters(target_date)
    logger.info(
        "Encounter rows fetched from Cloud SQL",
        extra={"target_date": str(target_date), "row_count": len(rows)},
    )

    # Stage 3: Apply de-identification pipeline
    salt = Config.deidentification_salt()
    deidentified_rows = deidentify_batch(rows, salt)

    # Stage 4: Write to BigQuery (WRITE_TRUNCATE on partition)
    rows_written = write_partition(bq_client, deidentified_rows, target_date)

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "BigQuery nightly export job completed",
        extra={
            "target_date": str(target_date),
            "rows_written": rows_written,
            "elapsed_ms": elapsed_ms,
        },
    )


if __name__ == "__main__":
    try:
        run()
        sys.exit(0)
    except Exception:  # noqa: BLE001
        logger.exception("BigQuery nightly export job FAILED — exiting with code 1")
        sys.exit(1)
```

### 3. Create `jobs/bq-export/Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# SmartHandoff — BigQuery Nightly Export Job
# Cloud Run Job container; triggered by Cloud Scheduler at 02:00 UTC daily.
#
# Design refs:
#   design.md §3.1 — Cloud Run stateless jobs
#   US-062 — nightly BigQuery de-identified encounter export
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run Job executes the entrypoint directly (not a long-running server)
ENTRYPOINT ["python", "main.py"]
```

---

## Definition of Done

- [ ] `bq_writer.py` uses `WriteDisposition.WRITE_TRUNCATE` with partition decorator (`table$YYYYMMDD`) to scope truncation to the target date partition only
- [ ] `write_partition()` calls `assert_no_phi()` as a pre-write second guard before any data reaches BigQuery
- [ ] `main.py` entrypoint executes all four pipeline stages in order; logs `elapsed_ms` on completion
- [ ] `main.py` exits `0` on success, `1` on any unhandled exception (required for Cloud Monitoring alert)
- [ ] Structured JSON logging format applied at `basicConfig` level — Cloud Logging receives parseable JSON
- [ ] `Dockerfile` uses `python:3.12-slim`; `ENTRYPOINT ["python", "main.py"]`; no secrets baked into image
- [ ] Manual smoke test: run container locally with `EXPORT_DATE_OVERRIDE` and synthetic Cloud SQL data; confirm BigQuery partition written and idempotent on second run

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `bq_client.py`, `schema.py`, `sql_reader.py`, `config.py` |
| TASK-002 | Task | `deidentify.py`, `date_utils.py` |

---

## Files Modified

| File | Action |
|---|---|
| `jobs/bq-export/app/bq_writer.py` | Create — WRITE_TRUNCATE partition writer |
| `jobs/bq-export/main.py` | Create — job entrypoint with structured logging + sys.exit |
| `jobs/bq-export/Dockerfile` | Create — Cloud Run job container definition |
