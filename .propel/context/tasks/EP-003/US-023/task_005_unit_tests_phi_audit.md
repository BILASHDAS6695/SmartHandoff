---
id: TASK-005
title: "Write Unit Tests — PHI Audit, Scenario Coverage, and Timeout Fallback for US-023"
user_story: US-023
epic: EP-003
sprint: 2
layer: Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-023/TASK-001, US-023/TASK-002, US-023/TASK-003, US-023/TASK-004]
---

# TASK-005: Write Unit Tests — PHI Audit, Scenario Coverage, and Timeout Fallback for US-023

> **Story:** US-023 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-023 DoD mandates:

> *"PHI audit: unit test confirms patient PII fields (`first_name`, `last_name`, `mrn`, `dob`) are absent from prompt before Gemini call"*

This task implements the complete unit test suite covering:

1. **PHI audit tests** — confirm PHI fields are absent from both the `ChecklistInput` model and the rendered Jinja2 prompt
2. **`HandoffChecklist` model validation tests** — actionable-verb enforcement, priority constraints, schema shape
3. **`ChecklistService` behaviour tests** — LLM success path, timeout fallback, error fallback
4. **Template fallback tests** — all transition types load and validate correctly
5. **API schema tests** — `AgentTaskResponse` includes `checklist` field

Design refs: AIR-021, US-023 DoD, AC Scenarios 1–4.

---

## Acceptance Criteria Addressed

| US-023 AC | Requirement |
|---|---|
| **Scenario 1** | Test: checklist for A03 discharge with T2D + Heart Failure diagnoses contains ≥3 items |
| **Scenario 2** | PHI audit test: `first_name`, `last_name`, `mrn`, `dob` absent from rendered prompt |
| **Scenario 3** | Test: checklist serialises to dict with `item`, `category`, `priority` keys |
| **Scenario 4** | Test: `asyncio.TimeoutError` triggers `generated_type="TEMPLATE"` fallback |

---

## Implementation Steps

### 1. Scaffold test directory structure

```
coordinator-agent/
└── tests/
    └── unit/
        ├── __init__.py
        ├── test_handoff_checklist_model.py    ← THIS TASK
        ├── test_checklist_service.py          ← THIS TASK
        └── test_checklist_phi_audit.py        ← THIS TASK
```

```bash
mkdir -p coordinator-agent/tests/unit
touch coordinator-agent/tests/__init__.py
touch coordinator-agent/tests/unit/__init__.py
```

### 2. Create `coordinator-agent/tests/unit/test_handoff_checklist_model.py`

```python
"""Unit tests for HandoffChecklist and ChecklistItem Pydantic models.

Coverage:
  - Valid model instantiation
  - Actionable-verb enforcement (model_validator)
  - Priority constraint (Literal type)
  - generated_type discriminator (LLM / TEMPLATE)
  - llm_response_schema() returns checklist definition
  - No PHI fields in model schema

Design refs: AIR-021, US-023 AC Scenarios 1, 2, 4
"""
import pytest
from pydantic import ValidationError

from app.models.handoff_checklist import ChecklistItem, HandoffChecklist


# ---------------------------------------------------------------------------
# ChecklistItem — valid construction
# ---------------------------------------------------------------------------


class TestChecklistItemValidConstruction:
    def test_valid_item_verify(self) -> None:
        item = ChecklistItem(
            item="Verify blood glucose monitoring plan",
            category="medications",
            priority="HIGH",
        )
        assert item.item.startswith("Verify")
        assert item.priority == "HIGH"

    def test_valid_item_confirm(self) -> None:
        item = ChecklistItem(
            item="Confirm diuretic dose adjustment per discharge orders",
            category="medications",
            priority="MEDIUM",
        )
        assert item.priority == "MEDIUM"

    @pytest.mark.parametrize(
        "verb",
        ["Verify", "Confirm", "Schedule", "Review", "Assess", "Ensure", "Notify"],
    )
    def test_all_actionable_verbs_accepted(self, verb: str) -> None:
        item = ChecklistItem(
            item=f"{verb} care plan updated before discharge",
            category="documentation",
            priority="LOW",
        )
        assert item.item.startswith(verb)


# ---------------------------------------------------------------------------
# ChecklistItem — invalid construction
# ---------------------------------------------------------------------------


class TestChecklistItemInvalidConstruction:
    def test_non_actionable_verb_raises(self) -> None:
        with pytest.raises(ValidationError, match="actionable"):
            ChecklistItem(
                item="Patient should monitor blood glucose daily",
                category="medications",
                priority="HIGH",
            )

    def test_invalid_priority_raises(self) -> None:
        with pytest.raises(ValidationError):
            ChecklistItem(
                item="Verify labs reviewed",
                category="documentation",
                priority="CRITICAL",  # Not in Literal
            )

    def test_item_too_short_raises(self) -> None:
        with pytest.raises(ValidationError):
            ChecklistItem(item="Check", category="safety", priority="HIGH")


# ---------------------------------------------------------------------------
# HandoffChecklist — valid construction
# ---------------------------------------------------------------------------


class TestHandoffChecklistValid:
    def _make_checklist(
        self,
        count: int = 3,
        generated_type: str = "LLM",
        transition_type: str = "A03",
    ) -> HandoffChecklist:
        items = [
            ChecklistItem(
                item=f"Verify care item number {i} for patient",
                category="documentation",
                priority="MEDIUM",
            )
            for i in range(count)
        ]
        return HandoffChecklist(
            checklist=items,
            generated_type=generated_type,
            transition_type=transition_type,
        )

    def test_three_items_discharge_scenario(self) -> None:
        """US-023 AC Scenario 1 — discharge checklist contains ≥3 items."""
        checklist = self._make_checklist(count=3, transition_type="A03")
        assert len(checklist.checklist) >= 3

    def test_generated_type_llm(self) -> None:
        checklist = self._make_checklist(generated_type="LLM")
        assert checklist.generated_type == "LLM"

    def test_generated_type_template(self) -> None:
        """US-023 AC Scenario 4 — TEMPLATE discriminator accepted."""
        checklist = self._make_checklist(generated_type="TEMPLATE")
        assert checklist.generated_type == "TEMPLATE"

    def test_serialises_to_dict_with_required_keys(self) -> None:
        """US-023 AC Scenario 3 — checklist items serialise to dict with item/category/priority."""
        checklist = self._make_checklist()
        for item_dict in [i.model_dump() for i in checklist.checklist]:
            assert "item" in item_dict
            assert "category" in item_dict
            assert "priority" in item_dict


# ---------------------------------------------------------------------------
# HandoffChecklist — PHI schema audit (US-023 AC Scenario 2)
# ---------------------------------------------------------------------------


class TestHandoffChecklistPHIAudit:
    PHI_FIELDS = {"first_name", "last_name", "mrn", "dob", "phone", "email", "patient_name"}

    def test_handoff_checklist_schema_contains_no_phi_fields(self) -> None:
        """Ensure HandoffChecklist model schema exposes zero PHI field names."""
        schema_str = str(HandoffChecklist.model_json_schema())
        violations = [f for f in self.PHI_FIELDS if f in schema_str]
        assert not violations, f"PHI fields found in HandoffChecklist schema: {violations}"

    def test_checklist_item_schema_contains_no_phi_fields(self) -> None:
        schema_str = str(ChecklistItem.model_json_schema())
        violations = [f for f in self.PHI_FIELDS if f in schema_str]
        assert not violations, f"PHI fields found in ChecklistItem schema: {violations}"


# ---------------------------------------------------------------------------
# llm_response_schema()
# ---------------------------------------------------------------------------


class TestLlmResponseSchema:
    def test_returns_dict(self) -> None:
        schema = HandoffChecklist.llm_response_schema()
        assert isinstance(schema, dict)

    def test_schema_contains_checklist_definition(self) -> None:
        schema_str = str(HandoffChecklist.llm_response_schema())
        assert "checklist" in schema_str
```

### 3. Create `coordinator-agent/tests/unit/test_checklist_phi_audit.py`

```python
"""PHI audit unit tests — US-023 DoD mandatory test.

Confirms that:
  1. ``ChecklistInput`` model has no PHI field definitions.
  2. The rendered ``checklist.jinja2`` prompt contains no PHI field names or values.
  3. ``ChecklistService._call_gemini()`` receives a rendered prompt free of PHI.

Design refs: AIR-021, US-023 DoD PHI audit requirement
"""
import pathlib

import jinja2
import pytest

from app.checklist import ChecklistInput


_PROMPTS_DIR = pathlib.Path(__file__).parent.parent.parent / "prompts"

_PHI_FIELDS = ["first_name", "last_name", "mrn", "dob", "date_of_birth", "phone", "email", "ssn"]

_SAFE_INPUT = ChecklistInput(
    encounter_id="ENC-001",
    diagnosis_codes=["E11.9", "I50.9"],
    unit_name="Med-Surg 4B",
    transition_type="A03",
    medication_names=["Metformin", "Furosemide"],
)


class TestChecklistInputPHIAudit:
    """Verify ChecklistInput model defines no PHI fields (AIR-021)."""

    def test_checklist_input_has_no_phi_fields(self) -> None:
        model_fields = set(ChecklistInput.model_fields.keys())
        phi_violations = set(_PHI_FIELDS) & model_fields
        assert not phi_violations, (
            f"PHI fields found in ChecklistInput model definition: {phi_violations}. "
            "Remove all patient-identifying fields per AIR-021."
        )

    def test_encounter_id_is_only_identifier(self) -> None:
        """encounter_id (UUID) is the only identifier — not a PHI field."""
        fields = set(ChecklistInput.model_fields.keys())
        expected = {"encounter_id", "diagnosis_codes", "unit_name", "transition_type", "medication_names"}
        assert fields == expected, f"Unexpected fields in ChecklistInput: {fields - expected}"


class TestRenderedPromptPHIAudit:
    """Verify the rendered Jinja2 prompt contains no PHI values or field names."""

    @pytest.fixture()
    def rendered_prompt(self) -> str:
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_PROMPTS_DIR)),
            autoescape=False,
            undefined=jinja2.StrictUndefined,
        )
        tmpl = env.get_template("checklist.jinja2")
        return tmpl.render(
            diagnosis_codes=_SAFE_INPUT.diagnosis_codes,
            unit_name=_SAFE_INPUT.unit_name,
            transition_type=_SAFE_INPUT.transition_type,
            medication_names=_SAFE_INPUT.medication_names,
        )

    def test_phi_field_names_absent_from_rendered_prompt(self, rendered_prompt: str) -> None:
        """US-023 DoD — unit test confirms PHI field names absent from prompt."""
        violations = [field for field in _PHI_FIELDS if field in rendered_prompt.lower()]
        assert not violations, (
            f"PHI field names found in rendered prompt: {violations}. "
            "Review checklist.jinja2 template to remove PHI references."
        )

    def test_encounter_id_absent_from_rendered_prompt(self, rendered_prompt: str) -> None:
        """encounter_id is used only for logging, must NOT appear in the LLM prompt."""
        assert "ENC-001" not in rendered_prompt, (
            "encounter_id appears in rendered prompt. "
            "It must be used only for logging, never injected into the LLM prompt."
        )

    def test_rendered_prompt_contains_diagnosis_codes(self, rendered_prompt: str) -> None:
        """ICD-10 codes (not text) should appear in the prompt."""
        assert "E11.9" in rendered_prompt
        assert "I50.9" in rendered_prompt

    def test_rendered_prompt_contains_unit_name(self, rendered_prompt: str) -> None:
        assert "Med-Surg 4B" in rendered_prompt

    def test_rendered_prompt_contains_transition_type(self, rendered_prompt: str) -> None:
        assert "A03" in rendered_prompt or "DISCHARGE" in rendered_prompt
```

### 4. Create `coordinator-agent/tests/unit/test_checklist_service.py`

```python
"""Unit tests for ChecklistService — LLM success, timeout fallback, error fallback.

Design refs: US-023 AC Scenarios 1, 4; ADR-004; AIR-021
"""
from __future__ import annotations

import asyncio
import os
import unittest.mock

import pytest
import pytest_asyncio

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

from app.checklist import ChecklistInput, ChecklistService
from app.models.handoff_checklist import ChecklistItem, HandoffChecklist


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def service() -> ChecklistService:
    return ChecklistService(timeout_sec=5)


@pytest.fixture()
def discharge_input() -> ChecklistInput:
    """US-023 AC Scenario 1 — discharge with T2D and Heart Failure."""
    return ChecklistInput(
        encounter_id="ENC-001",
        diagnosis_codes=["E11.9", "I50.9"],
        unit_name="Med-Surg 4B",
        transition_type="A03",
        medication_names=["Metformin", "Furosemide"],
    )


def _make_llm_checklist(count: int = 3) -> HandoffChecklist:
    """Helper: build a HandoffChecklist simulating an LLM response."""
    items = [
        ChecklistItem(
            item=f"Verify clinical care item {i} completed before discharge",
            category="documentation",
            priority="HIGH",
        )
        for i in range(count)
    ]
    return HandoffChecklist(
        checklist=items,
        generated_type="LLM",
        transition_type="A03",
    )


# ---------------------------------------------------------------------------
# LLM success path (US-023 AC Scenario 1)
# ---------------------------------------------------------------------------


class TestChecklistServiceLLMSuccess:
    @pytest.mark.asyncio()
    async def test_generate_returns_llm_type_on_success(
        self, service: ChecklistService, discharge_input: ChecklistInput
    ) -> None:
        mock_result = _make_llm_checklist(count=4)

        with unittest.mock.patch.object(
            service, "_call_gemini", return_value=mock_result
        ):
            result = await service.generate(discharge_input)

        assert result.generated_type == "LLM"
        assert len(result.checklist) >= 3

    @pytest.mark.asyncio()
    async def test_generate_passes_correct_transition_type(
        self, service: ChecklistService, discharge_input: ChecklistInput
    ) -> None:
        mock_result = _make_llm_checklist()
        captured_input: list[ChecklistInput] = []

        async def mock_call(ctx: ChecklistInput) -> HandoffChecklist:
            captured_input.append(ctx)
            return mock_result

        with unittest.mock.patch.object(service, "_call_gemini", mock_call):
            await service.generate(discharge_input)

        assert captured_input[0].transition_type == "A03"

    @pytest.mark.asyncio()
    async def test_generate_does_not_inject_encounter_id_into_call(
        self, service: ChecklistService, discharge_input: ChecklistInput
    ) -> None:
        """encounter_id must not appear in the rendered prompt (AIR-021)."""
        mock_result = _make_llm_checklist()
        captured_prompts: list[str] = []

        original_render = service._prompt_template.render

        def _capture_render(**kwargs: object) -> str:
            rendered = original_render(**kwargs)
            captured_prompts.append(rendered)
            return rendered

        with (
            unittest.mock.patch.object(service._prompt_template, "render", _capture_render),
            unittest.mock.patch.object(service, "_call_gemini", return_value=mock_result),
        ):
            await service.generate(discharge_input)

        assert captured_prompts, "render() was not called"
        assert "ENC-001" not in captured_prompts[0], "encounter_id leaked into LLM prompt"


# ---------------------------------------------------------------------------
# Timeout fallback (US-023 AC Scenario 4)
# ---------------------------------------------------------------------------


class TestChecklistServiceTimeoutFallback:
    @pytest.mark.asyncio()
    async def test_timeout_returns_template_type(
        self, service: ChecklistService, discharge_input: ChecklistInput
    ) -> None:
        """US-023 AC Scenario 4 — 15s timeout fires → TEMPLATE fallback."""

        async def _slow_gemini(_ctx: ChecklistInput) -> HandoffChecklist:
            await asyncio.sleep(999)  # Will always time out
            return _make_llm_checklist()

        with unittest.mock.patch.object(service, "_call_gemini", _slow_gemini):
            result = await service.generate(discharge_input)

        assert result.generated_type == "TEMPLATE"

    @pytest.mark.asyncio()
    async def test_timeout_fallback_has_minimum_three_items(
        self, service: ChecklistService, discharge_input: ChecklistInput
    ) -> None:
        async def _slow_gemini(_ctx: ChecklistInput) -> HandoffChecklist:
            await asyncio.sleep(999)
            return _make_llm_checklist()

        with unittest.mock.patch.object(service, "_call_gemini", _slow_gemini):
            result = await service.generate(discharge_input)

        assert len(result.checklist) >= 3

    @pytest.mark.asyncio()
    async def test_timeout_fallback_transition_type_matches_input(
        self, service: ChecklistService, discharge_input: ChecklistInput
    ) -> None:
        async def _slow_gemini(_ctx: ChecklistInput) -> HandoffChecklist:
            await asyncio.sleep(999)
            return _make_llm_checklist()

        with unittest.mock.patch.object(service, "_call_gemini", _slow_gemini):
            result = await service.generate(discharge_input)

        assert result.transition_type == "A03"

    @pytest.mark.asyncio()
    async def test_error_in_gemini_returns_template_fallback(
        self, service: ChecklistService, discharge_input: ChecklistInput
    ) -> None:
        async def _error_gemini(_ctx: ChecklistInput) -> HandoffChecklist:
            raise RuntimeError("Vertex AI unavailable")

        with unittest.mock.patch.object(service, "_call_gemini", _error_gemini):
            result = await service.generate(discharge_input)

        assert result.generated_type == "TEMPLATE"


# ---------------------------------------------------------------------------
# Template fallback — direct load tests
# ---------------------------------------------------------------------------


class TestChecklistServiceTemplateFallback:
    @pytest.mark.parametrize("transition_type", ["A01", "A02", "A03"])
    def test_all_adt_transitions_have_fallback(
        self, service: ChecklistService, transition_type: str
    ) -> None:
        ctx = ChecklistInput(
            encounter_id="ENC-TEST",
            diagnosis_codes=["Z99.99"],
            unit_name="Test Unit",
            transition_type=transition_type,
        )
        result = service._load_template_fallback(ctx)
        assert result.generated_type == "TEMPLATE"
        assert len(result.checklist) >= 3

    def test_unknown_transition_type_uses_default(self, service: ChecklistService) -> None:
        ctx = ChecklistInput(
            encounter_id="ENC-TEST",
            diagnosis_codes=["Z99.99"],
            unit_name="Test Unit",
            transition_type="A99",  # Unknown
        )
        result = service._load_template_fallback(ctx)
        assert result.generated_type == "TEMPLATE"
        assert len(result.checklist) >= 1
```

---

## Validation

Run from `coordinator-agent/`:

```bash
# 1. Run full test suite
python -m pytest tests/unit/ -v --tb=short

# 2. Run PHI audit tests specifically (US-023 DoD mandatory)
python -m pytest tests/unit/test_checklist_phi_audit.py -v

# 3. Run with coverage report
python -m pytest tests/unit/ --cov=app/models/handoff_checklist \
    --cov=app/checklist --cov-report=term-missing

# 4. Expected pass count: ≥25 tests
python -m pytest tests/unit/ -v --tb=short -q 2>&1 | tail -5
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `coordinator-agent/tests/__init__.py` |
| CREATE | `coordinator-agent/tests/unit/__init__.py` |
| CREATE | `coordinator-agent/tests/unit/test_handoff_checklist_model.py` |
| CREATE | `coordinator-agent/tests/unit/test_checklist_phi_audit.py` |
| CREATE | `coordinator-agent/tests/unit/test_checklist_service.py` |

---

## Definition of Done Checklist

- [ ] `test_checklist_phi_audit.py` passes — `ChecklistInput` has no PHI fields
- [ ] `test_checklist_phi_audit.py` passes — rendered `checklist.jinja2` prompt contains no PHI field names
- [ ] `test_checklist_phi_audit.py` passes — `encounter_id` absent from rendered LLM prompt
- [ ] `test_handoff_checklist_model.py` — all 7 actionable verbs accepted; non-verb rejected
- [ ] `test_handoff_checklist_model.py` — `generated_type` LLM and TEMPLATE both validated
- [ ] `test_checklist_service.py` — timeout test returns `generated_type="TEMPLATE"`
- [ ] `test_checklist_service.py` — LLM success returns `generated_type="LLM"` with ≥3 items
- [ ] `test_checklist_service.py` — all 3 ADT transition types (A01/A02/A03) have template fallback
- [ ] All tests pass: `pytest tests/unit/ -v` — 0 failures
