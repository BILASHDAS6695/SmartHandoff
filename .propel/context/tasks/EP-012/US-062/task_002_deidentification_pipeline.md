---
id: TASK-002
title: "De-identification Pipeline — SHA-256 Hashing & PHI Scrubbing"
user_story: US-062
epic: EP-012
sprint: 2
layer: Backend / Data
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [TASK-001, DR-017, PRV-003]
---

# TASK-002: De-identification Pipeline — SHA-256 Hashing & PHI Scrubbing

> **Story:** US-062 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

With the module structure, schema, and Cloud SQL reader in place (TASK-001), this task implements the core de-identification transformation pipeline:

- SHA-256 hashing of `encounter_id` using a monthly-rotated salt (stored in Secret Manager)
- Removal of the raw `encounter_id` from the output row — replaced with `encounter_id_hash`
- Final `assert_no_phi()` guard invoked before any row is passed downstream
- A pure-function design that is easily unit-testable with synthetic data

**Design references:**
- US-062 Technical Notes — `encounter_id_hash = SHA-256(encounter_id + salt)`; salt rotated monthly
- design.md §8 — PHI containment; field-level encryption; defense-in-depth
- DR-017 — De-identified analytics data requirement (HIPAA Safe Harbor method)
- design.md ADR-007 — PHI never in plaintext logs; application-layer controls

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | PHI fields absent from output; `encounter_id_hash` replaces raw `encounter_id`; `assert_no_phi()` enforced |
| Scenario 3 | De-identification is deterministic for the same input + salt — idempotent hash output |

---

## Implementation Steps

### 1. Create `jobs/bq-export/app/deidentify.py`

```python
"""De-identification pipeline for encounter export records.

Transforms raw Cloud SQL encounter rows into BigQuery-safe records by:
  1. Hashing encounter_id with SHA-256(encounter_id + salt)
  2. Dropping the raw encounter_id from the output dict
  3. Asserting no PHI columns remain before the record is returned

HIPAA Safe Harbor compliance:
    Implements the de-identification standard under 45 CFR §164.514(b).
    The following identifiers are removed:
      - Names (first_name, last_name) — excluded at SQL query level (TASK-001)
      - Geographic data below state level — unit field contains only unit code
      - Dates — only year-level aggregation for dates >89y old (not applicable here;
        admit_date and discharge_date retained as date only, no birth year correlation)
      - Account numbers / encounter IDs — replaced by one-way hash
      - Contact info (phone, email, MRN) — excluded at SQL query level (TASK-001)

Design refs:
    US-062 Technical Notes — SHA-256(encounter_id + salt); monthly salt rotation
    design.md §8.3 — PHI containment
    DR-017 — de-identified analytics data
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.schema import assert_no_phi

logger = logging.getLogger(__name__)

# Name of the raw encounter ID key as returned by sql_reader.fetch_encounters()
_RAW_ID_FIELD = "encounter_id"
# Name of the hashed field written to BigQuery
_HASH_FIELD = "encounter_id_hash"


def hash_encounter_id(encounter_id: str | int, salt: str) -> str:
    """Return the SHA-256 hex digest of (encounter_id + salt).

    The concatenation uses a pipe separator to prevent length-extension
    collisions between different encounter_id / salt combinations.

    Args:
        encounter_id: Raw encounter primary key from Cloud SQL.
        salt: Monthly-rotated secret salt from Secret Manager.

    Returns:
        64-character lowercase hex string (SHA-256 digest).
    """
    payload = f"{encounter_id}|{salt}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def deidentify_row(row: dict[str, Any], salt: str) -> dict[str, Any]:
    """Transform a single encounter row into a de-identified BigQuery record.

    Steps:
      1. Hash the raw encounter_id → encounter_id_hash
      2. Remove the raw encounter_id key
      3. Assert no PHI columns remain in the output dict

    Args:
        row: A dict returned by sql_reader.fetch_encounters(); must contain
             the 'encounter_id' key plus the safe columns defined in schema.py.
        salt: Monthly-rotated de-identification salt from Secret Manager.

    Returns:
        A new dict safe for BigQuery insertion; never mutates the input row.

    Raises:
        KeyError: If 'encounter_id' is absent from the row.
        ValueError: If any PHI column is detected in the output (schema violation).
    """
    output = dict(row)  # shallow copy — never mutate caller's data

    raw_id = output.pop(_RAW_ID_FIELD)
    output[_HASH_FIELD] = hash_encounter_id(raw_id, salt)

    # Final PHI guard — raises ValueError if any blocklisted column is present
    assert_no_phi(list(output.keys()))

    return output


def deidentify_batch(
    rows: list[dict[str, Any]], salt: str
) -> list[dict[str, Any]]:
    """Apply de-identification to an entire batch of encounter rows.

    Logs a warning (and skips) any row missing the encounter_id key rather
    than aborting the entire export — partial exports are preferable to
    complete failures for non-critical data quality issues.

    Args:
        rows: List of dicts from sql_reader.fetch_encounters().
        salt: Monthly-rotated de-identification salt.

    Returns:
        List of de-identified dicts ready for BigQuery insertion.
    """
    output: list[dict[str, Any]] = []
    skipped = 0

    for row in rows:
        if _RAW_ID_FIELD not in row:
            logger.warning(
                "Skipping row missing encounter_id — cannot hash",
                extra={"row_keys": list(row.keys())},
            )
            skipped += 1
            continue
        output.append(deidentify_row(row, salt))

    if skipped:
        logger.warning(
            "De-identification batch completed with skipped rows",
            extra={"total": len(rows), "skipped": skipped, "exported": len(output)},
        )
    else:
        logger.info(
            "De-identification batch completed",
            extra={"total": len(rows), "exported": len(output)},
        )

    return output
```

### 2. Add date utilities in `jobs/bq-export/app/date_utils.py`

```python
"""Date utility helpers for the nightly export job.

Centralises the logic for determining the target export date so that:
  - Scheduled runs default to yesterday (UTC)
  - Manual backfill runs can override via EXPORT_DATE_OVERRIDE env var
  - All date arithmetic is UTC-based to avoid DST edge cases

Design refs:
    US-062 AC Scenario 1 — export covers encounters completed in the previous day
    US-062 AC Scenario 3 — idempotent; re-runs for same date must not duplicate
"""
from __future__ import annotations

import datetime
import logging

from app.config import Config

logger = logging.getLogger(__name__)


def get_target_date() -> datetime.date:
    """Return the target export date.

    Priority:
      1. EXPORT_DATE_OVERRIDE env var (format: YYYY-MM-DD) — for manual backfills
      2. Yesterday in UTC — default for scheduled nightly runs

    Returns:
        A datetime.date representing the day whose encounters will be exported.
    """
    override = Config.EXPORT_DATE_OVERRIDE
    if override:
        try:
            target = datetime.date.fromisoformat(override)
            logger.info(
                "Using EXPORT_DATE_OVERRIDE",
                extra={"target_date": str(target)},
            )
            return target
        except ValueError as exc:
            raise ValueError(
                f"EXPORT_DATE_OVERRIDE must be YYYY-MM-DD, got: {override!r}"
            ) from exc

    yesterday = datetime.datetime.now(tz=datetime.timezone.utc).date() - datetime.timedelta(days=1)
    logger.info(
        "Using default target date (yesterday UTC)",
        extra={"target_date": str(yesterday)},
    )
    return yesterday
```

---

## Definition of Done

- [ ] `deidentify.py` created with `hash_encounter_id()`, `deidentify_row()`, `deidentify_batch()` functions
- [ ] `hash_encounter_id()` uses SHA-256 with pipe-separated `encounter_id|salt` payload (prevents length-extension collisions)
- [ ] `deidentify_row()` removes raw `encounter_id` from output and sets `encounter_id_hash`
- [ ] `assert_no_phi()` called inside `deidentify_row()` — raises `ValueError` on any PHI column detection
- [ ] `deidentify_batch()` logs skipped rows and continues rather than aborting the export
- [ ] `date_utils.py` created; `get_target_date()` respects `EXPORT_DATE_OVERRIDE` env var; defaults to yesterday UTC
- [ ] All functions are pure (no side effects, no I/O) except logging — readily unit-testable with synthetic data

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `app/schema.py` (provides `assert_no_phi()`); `app/config.py` (provides `Config`) |

---

## Files Modified

| File | Action |
|---|---|
| `jobs/bq-export/app/deidentify.py` | Create — SHA-256 hashing + PHI scrubbing pipeline |
| `jobs/bq-export/app/date_utils.py` | Create — target export date resolver |
