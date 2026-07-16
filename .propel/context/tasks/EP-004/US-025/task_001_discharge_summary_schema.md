---
id: TASK-001
title: "Implement `DischargeSummarySchema` Pydantic Model and `GenerationType` Enum"
user_story: US-025
epic: EP-004
sprint: 2
layer: Backend — Data Model
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-006]
---

# TASK-001: Implement `DischargeSummarySchema` Pydantic Model and `GenerationType` Enum

> **Story:** US-025 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Data Model | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The `DocumentationAgent` generates AI discharge summaries using Vertex AI Gemini 1.5 Pro with structured JSON output. Gemini's `response_mime_type="application/json"` mode requires a Pydantic model that maps directly to the `response_schema` parameter. This task defines the canonical Pydantic contract for discharge summary structured output, the `GenerationType` enum used to distinguish AI vs. template-generated documents, and the `DischargeSummarySection` sub-models.

This schema is the single source of truth referenced by both the LLM call (TASK-004) and the template fallback renderer (TASK-005).

---

## Acceptance Criteria Addressed

| US-025 AC | Requirement |
|---|---|
| **Scenario 3** | Structured output includes all mandatory sections: `diagnosis_summary`, `procedures`, `medications_at_discharge`, `follow_up_instructions`, `warning_signs`, `activity_restrictions` |

---

## Implementation Steps

### 1. Create `agents/documentation/schemas.py`

Create the file at `backend/agents/documentation/schemas.py`. This module must be importable with no side-effects.

```python
"""
Pydantic schemas for the Documentation Agent structured output.

These models define the contract between Vertex AI Gemini structured output
(response_schema) and the DocumentationAgent. They are also used by the
Jinja2 template fallback renderer to ensure structural consistency.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class GenerationType(str, Enum):
    """Indicates how the discharge summary was produced."""
    AI = "AI"
    TEMPLATE = "TEMPLATE"


class DiagnosisEntry(BaseModel):
    """Single diagnosis with ICD-10 code and human-readable description."""
    icd10_code: str = Field(
        ...,
        description="ICD-10-CM code, e.g. 'E11.9' for Type 2 diabetes without complications",
    )
    description: str = Field(
        ...,
        description="Generic clinical description — must NOT include patient name or DOB",
    )
    is_primary: bool = Field(
        default=False,
        description="True if this is the primary admission diagnosis",
    )


class MedicationEntry(BaseModel):
    """Medication at discharge with dosage and frequency."""
    drug_name: str = Field(..., description="Generic drug name (not brand name)")
    dose: str = Field(..., description="Dose with unit, e.g. '500 mg'")
    frequency: str = Field(..., description="Frequency, e.g. 'twice daily with meals'")
    route: str = Field(..., description="Route of administration, e.g. 'oral'")
    rxnorm_code: Optional[str] = Field(
        default=None,
        description="RxNorm concept identifier if available",
    )


class ProcedureEntry(BaseModel):
    """Clinical procedure performed during the encounter."""
    cpt_code: Optional[str] = Field(default=None, description="CPT code if applicable")
    description: str = Field(..., description="Procedure description")
    date_performed: Optional[str] = Field(
        default=None,
        description="ISO 8601 date string, e.g. '2026-07-14'",
    )


class FollowUpInstruction(BaseModel):
    """Single follow-up instruction item."""
    instruction: str = Field(..., description="Actionable follow-up step for the patient")
    timeframe: Optional[str] = Field(
        default=None,
        description="Timeframe for action, e.g. 'within 7 days'",
    )
    provider_type: Optional[str] = Field(
        default=None,
        description="Type of provider to follow up with, e.g. 'primary care physician'",
    )


class DischargeSummarySchema(BaseModel):
    """
    Structured discharge summary schema.

    Used as:
    - Vertex AI Gemini response_schema (TASK-004)
    - Template fallback output contract (TASK-005)

    All six mandatory sections must be populated. The LLM is instructed to
    use ICD-10 codes and generic descriptions — NOT patient PII.
    """

    encounter_id: str = Field(
        ...,
        description="Encounter identifier (non-PHI reference key)",
    )

    # --- Mandatory Sections (Scenario 3) ---
    diagnosis_summary: List[DiagnosisEntry] = Field(
        ...,
        min_length=1,
        description="Primary and secondary diagnoses with ICD-10 codes",
    )
    procedures: List[ProcedureEntry] = Field(
        default_factory=list,
        description="Procedures performed during the encounter",
    )
    medications_at_discharge: List[MedicationEntry] = Field(
        ...,
        min_length=1,
        description="Complete medication list at time of discharge",
    )
    follow_up_instructions: List[FollowUpInstruction] = Field(
        ...,
        min_length=1,
        description="Actionable follow-up steps the patient must take",
    )
    warning_signs: List[str] = Field(
        ...,
        min_length=1,
        description=(
            "Symptom warning signs that should prompt the patient to seek immediate care. "
            "Plain language, reading level ≤8th grade."
        ),
    )
    activity_restrictions: List[str] = Field(
        ...,
        min_length=1,
        description="Physical activity restrictions or limitations post-discharge",
    )

    # --- Optional Enrichment ---
    diet_instructions: Optional[List[str]] = Field(
        default=None,
        description="Dietary recommendations if applicable",
    )
    wound_care_instructions: Optional[str] = Field(
        default=None,
        description="Wound care or dressing change instructions if applicable",
    )

    # --- Generation Metadata ---
    generation_type: GenerationType = Field(
        default=GenerationType.AI,
        description="Whether this summary was AI-generated or template-generated (fallback)",
    )
    generation_duration_ms: Optional[int] = Field(
        default=None,
        description="Wall-clock milliseconds taken to generate this summary",
    )
```

### 2. Export from `agents/documentation/__init__.py`

Ensure `DischargeSummarySchema` and `GenerationType` are exported from the package:

```python
from agents.documentation.schemas import DischargeSummarySchema, GenerationType

__all__ = ["DischargeSummarySchema", "GenerationType"]
```

### 3. Unit Tests — `tests/agents/documentation/test_schemas.py`

```python
import pytest
from pydantic import ValidationError
from agents.documentation.schemas import DischargeSummarySchema, GenerationType


MINIMAL_VALID_PAYLOAD = {
    "encounter_id": "ENC-001",
    "diagnosis_summary": [{"icd10_code": "E11.9", "description": "Type 2 diabetes", "is_primary": True}],
    "procedures": [],
    "medications_at_discharge": [
        {"drug_name": "metformin", "dose": "500 mg", "frequency": "twice daily", "route": "oral"}
    ],
    "follow_up_instructions": [{"instruction": "Follow up with PCP within 7 days"}],
    "warning_signs": ["Shortness of breath", "Chest pain"],
    "activity_restrictions": ["No heavy lifting for 4 weeks"],
}


def test_valid_schema_parses_successfully():
    schema = DischargeSummarySchema(**MINIMAL_VALID_PAYLOAD)
    assert schema.encounter_id == "ENC-001"
    assert schema.generation_type == GenerationType.AI


def test_missing_mandatory_section_raises_validation_error():
    payload = {**MINIMAL_VALID_PAYLOAD}
    del payload["warning_signs"]
    with pytest.raises(ValidationError):
        DischargeSummarySchema(**payload)


def test_empty_mandatory_list_raises_validation_error():
    payload = {**MINIMAL_VALID_PAYLOAD, "medications_at_discharge": []}
    with pytest.raises(ValidationError):
        DischargeSummarySchema(**payload)


def test_generation_type_template_sets_correctly():
    payload = {**MINIMAL_VALID_PAYLOAD, "generation_type": "TEMPLATE"}
    schema = DischargeSummarySchema(**payload)
    assert schema.generation_type == GenerationType.TEMPLATE
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/agents/documentation/schemas.py` |
| **Create/Update** | `backend/agents/documentation/__init__.py` |
| **Create** | `backend/tests/agents/documentation/test_schemas.py` |

---

## Definition of Done

- [ ] `DischargeSummarySchema` defines all six mandatory sections with `min_length=1` constraints
- [ ] `GenerationType` enum has `AI` and `TEMPLATE` values
- [ ] `DiagnosisEntry`, `MedicationEntry`, `ProcedureEntry`, `FollowUpInstruction` sub-models defined
- [ ] Schema exported from `agents/documentation/__init__.py`
- [ ] All 4 unit tests pass (`pytest tests/agents/documentation/test_schemas.py`)
- [ ] No PHI field names (`patient_name`, `dob`, `ssn`, `address`) present in the schema

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-006 | Story | `document` ORM model referenced in TASK-006; schema is standalone |
| Pydantic v2 | Library | Already in `pyproject.toml`; use `model_fields` not `__fields__` |
