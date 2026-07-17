---
id: TASK-006
title: "Unit Tests — De-identification Pipeline & Schema PHI Guard"
user_story: US-062
epic: EP-012
sprint: 2
layer: Testing
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003]
---

# TASK-006: Unit Tests — De-identification Pipeline & Schema PHI Guard

> **Story:** US-062 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Testing | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-062 Technical Notes require: *"Test: run export on synthetic data in dev; verify PHI fields absent via BigQuery `INFORMATION_SCHEMA.COLUMNS`"*. Before integration testing, this task delivers unit tests covering:

- `hash_encounter_id()` — determinism, salt sensitivity, output format
- `deidentify_row()` — PHI removal, hash field insertion, `assert_no_phi()` enforcement
- `deidentify_batch()` — skip behaviour on missing `encounter_id`; partial batch handling
- `assert_no_phi()` — raises on each blocked field; passes on clean schema
- `get_target_date()` — override env var handling; default to yesterday UTC
- Schema field names — regression guard that no PHI column names creep into `ENCOUNTERS_DEIDENTIFIED_SCHEMA`

**Design references:**
- US-062 AC Scenario 2 — PHI fields absent; de-identification verified
- US-062 AC Scenario 3 — deterministic hash output (same input + salt = same hash)
- design.md ADR-007 — PHI never in plaintext; application-layer controls

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | Unit tests assert zero PHI field names in schema and de-identified row output |
| Scenario 3 | Idempotency test: same input + salt → identical `encounter_id_hash` on repeated calls |

---

## Implementation Steps

### 1. Create test directory and fixtures

```bash
mkdir -p jobs/bq-export/tests
touch jobs/bq-export/tests/__init__.py
touch jobs/bq-export/tests/conftest.py
touch jobs/bq-export/tests/test_deidentify.py
touch jobs/bq-export/tests/test_schema.py
touch jobs/bq-export/tests/test_date_utils.py
```

### 2. Implement shared fixtures in `jobs/bq-export/tests/conftest.py`

```python
"""Shared pytest fixtures for bq-export unit tests.

All test data is synthetic — no real PHI values used in any fixture.
"""
from __future__ import annotations

import datetime

import pytest


SYNTHETIC_SALT = "test-salt-2026-07"

SYNTHETIC_ENCOUNTER_ROW = {
    "encounter_id": "ENC-001-SYNTHETIC",
    "admit_date": datetime.date(2026, 7, 14),
    "discharge_date": datetime.date(2026, 7, 16),
    "primary_diagnosis_code": "J18.9",
    "risk_score": 0.72,
    "risk_tier": "HIGH",
    "unit": "ICU-3",
    "los_days": 2.0,
    "discharge_disposition": "HOME",
    "readmitted_30d": False,
}

# A row that incorrectly contains a PHI column — used to test the guard
SYNTHETIC_ROW_WITH_PHI = {
    **SYNTHETIC_ENCOUNTER_ROW,
    "first_name": "SYNTHETIC_FNAME",  # PHI — must be blocked
}


@pytest.fixture
def synthetic_row() -> dict:
    return dict(SYNTHETIC_ENCOUNTER_ROW)


@pytest.fixture
def synthetic_row_with_phi() -> dict:
    return dict(SYNTHETIC_ROW_WITH_PHI)


@pytest.fixture
def synthetic_salt() -> str:
    return SYNTHETIC_SALT
```

### 3. Implement de-identification unit tests in `jobs/bq-export/tests/test_deidentify.py`

```python
"""Unit tests for the de-identification pipeline.

Tests are pure and require no external services (no Cloud SQL, no BigQuery).
All assertions use synthetic data only.

Design refs:
    US-062 AC Scenario 2 — PHI fields absent
    US-062 AC Scenario 3 — deterministic idempotent hash
    US-062 Technical Notes — SHA-256(encounter_id + salt)
"""
from __future__ import annotations

import hashlib

import pytest

from app.deidentify import deidentify_batch, deidentify_row, hash_encounter_id


class TestHashEncounterId:
    def test_returns_64_char_hex_string(self, synthetic_salt):
        result = hash_encounter_id("ENC-001", synthetic_salt)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic_same_inputs_same_output(self, synthetic_salt):
        """Same encounter_id + salt must always produce the same hash (idempotency)."""
        h1 = hash_encounter_id("ENC-001", synthetic_salt)
        h2 = hash_encounter_id("ENC-001", synthetic_salt)
        assert h1 == h2

    def test_different_salts_produce_different_hashes(self):
        h1 = hash_encounter_id("ENC-001", "salt-2026-06")
        h2 = hash_encounter_id("ENC-001", "salt-2026-07")
        assert h1 != h2

    def test_different_encounter_ids_produce_different_hashes(self, synthetic_salt):
        h1 = hash_encounter_id("ENC-001", synthetic_salt)
        h2 = hash_encounter_id("ENC-002", synthetic_salt)
        assert h1 != h2

    def test_pipe_separator_prevents_collision(self, synthetic_salt):
        """'ENC|001' + 'salt' must differ from 'ENC' + '001salt'."""
        h1 = hash_encounter_id("ENC|001", synthetic_salt)
        h2 = hash_encounter_id("ENC", f"001{synthetic_salt}")
        assert h1 != h2

    def test_matches_manual_sha256(self, synthetic_salt):
        enc_id = "ENC-001"
        expected = hashlib.sha256(
            f"{enc_id}|{synthetic_salt}".encode("utf-8")
        ).hexdigest()
        assert hash_encounter_id(enc_id, synthetic_salt) == expected


class TestDeidentifyRow:
    def test_encounter_id_removed_from_output(self, synthetic_row, synthetic_salt):
        result = deidentify_row(synthetic_row, synthetic_salt)
        assert "encounter_id" not in result

    def test_encounter_id_hash_present_in_output(self, synthetic_row, synthetic_salt):
        result = deidentify_row(synthetic_row, synthetic_salt)
        assert "encounter_id_hash" in result
        assert len(result["encounter_id_hash"]) == 64

    def test_safe_fields_preserved(self, synthetic_row, synthetic_salt):
        result = deidentify_row(synthetic_row, synthetic_salt)
        safe_fields = {
            "admit_date", "discharge_date", "primary_diagnosis_code",
            "risk_score", "risk_tier", "unit", "los_days",
            "discharge_disposition", "readmitted_30d",
        }
        for field in safe_fields:
            assert field in result, f"Expected safe field '{field}' missing from output"

    def test_phi_guard_raises_on_phi_column(self, synthetic_row_with_phi, synthetic_salt):
        with pytest.raises(ValueError, match="PHI columns detected"):
            deidentify_row(synthetic_row_with_phi, synthetic_salt)

    def test_does_not_mutate_input_row(self, synthetic_row, synthetic_salt):
        original_keys = set(synthetic_row.keys())
        deidentify_row(synthetic_row, synthetic_salt)
        assert set(synthetic_row.keys()) == original_keys

    def test_idempotent_hash_on_repeated_calls(self, synthetic_row, synthetic_salt):
        """Re-running de-identification for the same row + salt yields the same hash."""
        h1 = deidentify_row(dict(synthetic_row), synthetic_salt)["encounter_id_hash"]
        h2 = deidentify_row(dict(synthetic_row), synthetic_salt)["encounter_id_hash"]
        assert h1 == h2

    def test_raises_key_error_if_encounter_id_missing(self, synthetic_salt):
        row_without_id = {
            "admit_date": "2026-07-14",
            "unit": "ICU-3",
        }
        with pytest.raises(KeyError):
            deidentify_row(row_without_id, synthetic_salt)


class TestDeidentifyBatch:
    def test_all_rows_processed(self, synthetic_row, synthetic_salt):
        batch = [dict(synthetic_row) for _ in range(5)]
        result = deidentify_batch(batch, synthetic_salt)
        assert len(result) == 5

    def test_rows_missing_encounter_id_are_skipped(self, synthetic_row, synthetic_salt):
        row_no_id = {k: v for k, v in synthetic_row.items() if k != "encounter_id"}
        batch = [dict(synthetic_row), row_no_id]
        result = deidentify_batch(batch, synthetic_salt)
        # Only the valid row is processed; missing-ID row is skipped
        assert len(result) == 1

    def test_empty_batch_returns_empty_list(self, synthetic_salt):
        assert deidentify_batch([], synthetic_salt) == []
```

### 4. Implement schema PHI guard unit tests in `jobs/bq-export/tests/test_schema.py`

```python
"""Unit tests for the BigQuery schema and PHI blocklist guard.

Design refs:
    US-062 AC Scenario 2 — PHI columns absent from schema
    US-062 DoD — BigQuery schema fields defined
"""
from __future__ import annotations

import pytest

from app.schema import (
    ENCOUNTERS_DEIDENTIFIED_SCHEMA,
    _PHI_COLUMNS_BLOCKLIST,
    assert_no_phi,
)

# All PHI fields that must NEVER appear in the schema
PHI_FIELDS = ["mrn", "first_name", "last_name", "dob", "phone", "email",
              "patient_id", "encounter_id"]

# All safe fields that MUST be present in the schema per US-062 DoD
REQUIRED_SAFE_FIELDS = [
    "encounter_id_hash", "admit_date", "discharge_date",
    "primary_diagnosis_code", "risk_score", "risk_tier",
    "unit", "los_days", "discharge_disposition", "readmitted_30d",
]


class TestSchemaFields:
    @pytest.fixture
    def schema_field_names(self):
        return [field.name for field in ENCOUNTERS_DEIDENTIFIED_SCHEMA]

    def test_all_required_safe_fields_present(self, schema_field_names):
        for field in REQUIRED_SAFE_FIELDS:
            assert field in schema_field_names, (
                f"Required safe field '{field}' missing from ENCOUNTERS_DEIDENTIFIED_SCHEMA"
            )

    @pytest.mark.parametrize("phi_field", PHI_FIELDS)
    def test_phi_field_absent_from_schema(self, schema_field_names, phi_field):
        assert phi_field not in schema_field_names, (
            f"PHI field '{phi_field}' must NOT appear in ENCOUNTERS_DEIDENTIFIED_SCHEMA"
        )

    def test_schema_has_exactly_ten_fields(self, schema_field_names):
        assert len(schema_field_names) == 10, (
            f"Schema should have exactly 10 fields per US-062 DoD, got {len(schema_field_names)}"
        )


class TestAssertNoPhi:
    @pytest.mark.parametrize("phi_field", PHI_FIELDS)
    def test_raises_on_each_phi_field(self, phi_field):
        with pytest.raises(ValueError, match="PHI columns detected"):
            assert_no_phi(["encounter_id_hash", "admit_date", phi_field])

    def test_passes_on_clean_schema(self):
        """assert_no_phi should not raise for the safe schema column list."""
        assert_no_phi(REQUIRED_SAFE_FIELDS)  # must not raise

    def test_error_message_includes_field_name(self):
        with pytest.raises(ValueError, match="mrn"):
            assert_no_phi(["admit_date", "mrn"])
```

### 5. Implement date utilities unit tests in `jobs/bq-export/tests/test_date_utils.py`

```python
"""Unit tests for the export date resolver.

Design refs:
    US-062 AC Scenario 1 — export covers previous day
    US-062 AC Scenario 3 — same date on re-run (idempotent)
"""
from __future__ import annotations

import datetime

import pytest

from app.date_utils import get_target_date


class TestGetTargetDate:
    def test_returns_yesterday_utc_by_default(self, monkeypatch):
        monkeypatch.delenv("EXPORT_DATE_OVERRIDE", raising=False)
        # Override Config to clear any override
        import app.config as cfg
        monkeypatch.setattr(cfg.Config, "EXPORT_DATE_OVERRIDE", None)

        result = get_target_date()
        yesterday = (
            datetime.datetime.now(tz=datetime.timezone.utc).date()
            - datetime.timedelta(days=1)
        )
        assert result == yesterday

    def test_respects_export_date_override(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.Config, "EXPORT_DATE_OVERRIDE", "2026-01-15")

        result = get_target_date()
        assert result == datetime.date(2026, 1, 15)

    def test_raises_on_invalid_override_format(self, monkeypatch):
        import app.config as cfg
        monkeypatch.setattr(cfg.Config, "EXPORT_DATE_OVERRIDE", "15-01-2026")

        with pytest.raises(ValueError, match="EXPORT_DATE_OVERRIDE must be YYYY-MM-DD"):
            get_target_date()
```

### 6. Add `pytest` to dev dependencies in `requirements.txt`

```text
# Append to requirements.txt
pytest==8.3.2
pytest-mock==3.14.0
```

---

## Definition of Done

- [ ] All test files created under `jobs/bq-export/tests/`
- [ ] `TestHashEncounterId`: 6 test cases covering determinism, length, salt sensitivity, pipe separator collision resistance, and manual SHA-256 verification
- [ ] `TestDeidentifyRow`: 7 test cases covering PHI removal, hash insertion, field preservation, PHI guard, input immutability, idempotency, and missing ID error
- [ ] `TestDeidentifyBatch`: 3 test cases covering full batch, skipped rows, and empty batch
- [ ] `TestSchemaFields`: PHI field absence asserted for all 8 PHI field names; all 10 required safe fields verified present
- [ ] `TestAssertNoPhi`: parameterized — each PHI field individually tested; clean schema passes
- [ ] `TestGetTargetDate`: default yesterday, override parsing, invalid format error
- [ ] `pytest jobs/bq-export/tests/` runs with zero failures on synthetic data (no external services required)
- [ ] No real PHI values used in any test fixture or assertion

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `app/schema.py`, `app/config.py` |
| TASK-002 | Task | `app/deidentify.py`, `app/date_utils.py` |

---

## Files Modified

| File | Action |
|---|---|
| `jobs/bq-export/tests/__init__.py` | Create — empty package marker |
| `jobs/bq-export/tests/conftest.py` | Create — shared synthetic fixtures |
| `jobs/bq-export/tests/test_deidentify.py` | Create — de-identification pipeline unit tests |
| `jobs/bq-export/tests/test_schema.py` | Create — schema PHI guard unit tests |
| `jobs/bq-export/tests/test_date_utils.py` | Create — date resolver unit tests |
| `jobs/bq-export/requirements.txt` | Update — add `pytest`, `pytest-mock` |
