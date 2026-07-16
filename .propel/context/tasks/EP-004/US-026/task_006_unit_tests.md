---
id: TASK-026-006
title: "Unit Tests — `CompletenessValidator` (Complete, Single Missing, Multiple Missing)"
user_story: US-026
epic: EP-004
sprint: 2
layer: Backend — Testing
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-026-001, TASK-026-002, TASK-026-003]
---

# TASK-026-006: Unit Tests — `CompletenessValidator` (Complete, Single Missing, Multiple Missing)

> **Story:** US-026 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Testing | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The DoD for US-026 mandates three unit test scenarios:
1. Complete document — passes validation
2. Missing one required field — flagged as INCOMPLETE
3. Missing multiple required fields — all absent fields listed

These tests are pure unit tests: they instantiate `CompletenessValidator` with an in-memory `CompletenessConfig` (backed by a temporary YAML file), inject known document dicts, and assert on the returned `CompletenessResult`. No DB, no Pub/Sub, no LLM.

Additionally this task covers tests for `_is_absent()` helper edge cases and `CompletenessConfig` YAML loading, including the env-var override path.

---

## Acceptance Criteria Addressed

| US-026 AC | Requirement |
|---|---|
| **Scenario 1** | Unit test: all fields present → `COMPLETE`, `missing_fields=[]` |
| **Scenario 2** | Unit test: one field missing → `INCOMPLETE`, `missing_fields=["follow_up_instructions"]` |
| **Scenario 3** | Unit test: adding a new field to temp YAML → validator picks it up without code change |

---

## Implementation Steps

### 1. Create `backend/tests/agents/documentation/test_completeness_validator.py`

```python
"""
Unit tests for CompletenessValidator and related components.

Tests cover:
  - Complete document → COMPLETE status
  - Single missing field → INCOMPLETE with correct field name
  - Multiple missing fields → INCOMPLETE with all field names listed
  - Edge cases for _is_absent() helper: None, "", [], {}, non-empty values
  - Config: new field in YAML picked up immediately (Scenario 3)
  - Config: unknown document type returns empty required_fields (non-blocking)

All tests use an in-memory temporary YAML config to avoid coupling to the real
config/document_completeness.yaml file.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agents.documentation.completeness_validator import (
    CompletenessStatus,
    CompletenessValidator,
    _is_absent,
)
from config.completeness_config import CompletenessConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STANDARD_REQUIRED_FIELDS = [
    "diagnosis_summary",
    "medications_at_discharge",
    "follow_up_instructions",
    "warning_signs",
    "activity_restrictions",
]

COMPLETE_DOCUMENT: dict = {
    "encounter_id": "ENC-001",
    "diagnosis_summary": [{"icd10_code": "E11.9", "description": "Type 2 diabetes", "is_primary": True}],
    "medications_at_discharge": [
        {"drug_name": "metformin", "dose": "500 mg", "frequency": "twice daily", "route": "oral"}
    ],
    "follow_up_instructions": [{"instruction": "Follow up with PCP within 7 days"}],
    "warning_signs": ["Shortness of breath", "Chest pain"],
    "activity_restrictions": ["No heavy lifting for 4 weeks"],
}


@pytest.fixture()
def temp_yaml(tmp_path: Path) -> Path:
    """Write a temporary document_completeness.yaml with the standard 5 required fields."""
    config_file = tmp_path / "document_completeness.yaml"
    config_file.write_text(
        textwrap.dedent("""\
            document_types:
              discharge_summary:
                required_fields:
                  - diagnosis_summary
                  - medications_at_discharge
                  - follow_up_instructions
                  - warning_signs
                  - activity_restrictions
        """),
        encoding="utf-8",
    )
    return config_file


@pytest.fixture()
def validator(temp_yaml: Path) -> CompletenessValidator:
    """Return a CompletenessValidator backed by the temporary YAML config."""
    config = CompletenessConfig(config_path=temp_yaml)
    return CompletenessValidator(config=config, document_type="discharge_summary")


# ---------------------------------------------------------------------------
# Core validation scenarios (US-026 DoD)
# ---------------------------------------------------------------------------

class TestCompletenessValidatorScenarios:
    """DoD scenarios: complete doc, single missing, multiple missing."""

    def test_complete_document_returns_complete_status(self, validator: CompletenessValidator) -> None:
        """Scenario 1: all required fields populated → COMPLETE, no missing fields."""
        result = validator.validate(COMPLETE_DOCUMENT)

        assert result.status == CompletenessStatus.COMPLETE
        assert result.missing_fields == []
        assert result.is_complete is True

    def test_single_missing_field_returns_incomplete(self, validator: CompletenessValidator) -> None:
        """Scenario 2: follow_up_instructions missing → INCOMPLETE, correct field listed."""
        doc = {**COMPLETE_DOCUMENT}
        del doc["follow_up_instructions"]

        result = validator.validate(doc)

        assert result.status == CompletenessStatus.INCOMPLETE
        assert result.missing_fields == ["follow_up_instructions"]
        assert result.is_complete is False

    def test_multiple_missing_fields_returns_all_absent_names(
        self, validator: CompletenessValidator
    ) -> None:
        """DoD: multiple missing fields → all absent field names listed in missing_fields."""
        doc = {**COMPLETE_DOCUMENT}
        del doc["warning_signs"]
        del doc["activity_restrictions"]

        result = validator.validate(doc)

        assert result.status == CompletenessStatus.INCOMPLETE
        assert "warning_signs" in result.missing_fields
        assert "activity_restrictions" in result.missing_fields
        assert len(result.missing_fields) == 2


# ---------------------------------------------------------------------------
# _is_absent() edge cases
# ---------------------------------------------------------------------------

class TestIsAbsentHelper:
    """Edge cases for the _is_absent() field-presence helper."""

    @pytest.mark.parametrize(
        "value",
        [None, "", "   ", [], {}],
        ids=["None", "empty_string", "whitespace_string", "empty_list", "empty_dict"],
    )
    def test_absent_values_return_true(self, value) -> None:
        assert _is_absent(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "some text",
            ["item"],
            {"key": "value"},
            0,
            False,
            [{"icd10_code": "E11.9"}],
        ],
        ids=["string", "non_empty_list", "non_empty_dict", "zero_int", "false_bool", "list_of_dicts"],
    )
    def test_present_values_return_false(self, value) -> None:
        assert _is_absent(value) is False

    def test_null_field_in_document_marked_missing(self, validator: CompletenessValidator) -> None:
        """Explicit None value for a required field counts as missing."""
        doc = {**COMPLETE_DOCUMENT, "warning_signs": None}
        result = validator.validate(doc)

        assert result.status == CompletenessStatus.INCOMPLETE
        assert "warning_signs" in result.missing_fields

    def test_empty_list_field_marked_missing(self, validator: CompletenessValidator) -> None:
        """Empty list for a required field counts as missing."""
        doc = {**COMPLETE_DOCUMENT, "medications_at_discharge": []}
        result = validator.validate(doc)

        assert result.status == CompletenessStatus.INCOMPLETE
        assert "medications_at_discharge" in result.missing_fields


# ---------------------------------------------------------------------------
# Config: Scenario 3 — new field in YAML picked up without code change
# ---------------------------------------------------------------------------

class TestCompletenessConfigDrivenBehaviour:
    """Ensures the validator is fully config-driven (Scenario 3)."""

    def test_new_field_in_yaml_enforced_immediately(self, tmp_path: Path) -> None:
        """
        Scenario 3: Adding 'specialist_referral' to YAML causes the validator
        to require it — without any code change.
        """
        config_file = tmp_path / "document_completeness.yaml"
        config_file.write_text(
            textwrap.dedent("""\
                document_types:
                  discharge_summary:
                    required_fields:
                      - diagnosis_summary
                      - medications_at_discharge
                      - follow_up_instructions
                      - warning_signs
                      - activity_restrictions
                      - specialist_referral
            """),
            encoding="utf-8",
        )
        config = CompletenessConfig(config_path=config_file)
        validator = CompletenessValidator(config=config, document_type="discharge_summary")

        # Document that was COMPLETE under the old 5-field config
        result = validator.validate(COMPLETE_DOCUMENT)

        # Must now be INCOMPLETE because specialist_referral is absent
        assert result.status == CompletenessStatus.INCOMPLETE
        assert "specialist_referral" in result.missing_fields

    def test_unknown_document_type_treated_as_complete(self, temp_yaml: Path) -> None:
        """An unconfigured document type has no required fields → always COMPLETE."""
        config = CompletenessConfig(config_path=temp_yaml)
        validator = CompletenessValidator(config=config, document_type="transfer_note")

        result = validator.validate({})  # completely empty doc

        assert result.status == CompletenessStatus.COMPLETE
        assert result.missing_fields == []

    def test_config_file_not_found_raises_file_not_found_error(self, tmp_path: Path) -> None:
        """Missing YAML file raises FileNotFoundError at config load time."""
        with pytest.raises(FileNotFoundError, match="Completeness config not found"):
            CompletenessConfig(config_path=tmp_path / "nonexistent.yaml")
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/tests/agents/documentation/test_completeness_validator.py` |

---

## Definition of Done

- [ ] All test classes and methods present: `TestCompletenessValidatorScenarios`, `TestIsAbsentHelper`, `TestCompletenessConfigDrivenBehaviour`
- [ ] `test_complete_document_returns_complete_status` — passes (Scenario 1)
- [ ] `test_single_missing_field_returns_incomplete` — `missing_fields == ["follow_up_instructions"]` (Scenario 2)
- [ ] `test_multiple_missing_fields_returns_all_absent_names` — all absent fields in list (DoD)
- [ ] `test_new_field_in_yaml_enforced_immediately` — `specialist_referral` caught without code change (Scenario 3)
- [ ] All `_is_absent()` parametrised edge cases pass
- [ ] All tests pass via `pytest backend/tests/agents/documentation/test_completeness_validator.py -v`
- [ ] No real file I/O against `config/document_completeness.yaml` — all tests use `tmp_path` fixture

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-026-001 | Task | `CompletenessConfig` class must exist |
| TASK-026-002 | Task | `CompletenessValidator`, `CompletenessResult`, `CompletenessStatus`, `_is_absent` must be importable |
| `pytest` | Library | Already in dev dependencies |
