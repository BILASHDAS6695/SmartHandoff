---
id: TASK-001
title: "Implement `PatientInstructionsSchema` Pydantic Model and `SupportedLanguage` Enum"
user_story: US-027
epic: EP-004
sprint: 2
layer: Backend — Data Model
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-025, TASK-001-US025]
---

# TASK-001: Implement `PatientInstructionsSchema` Pydantic Model and `SupportedLanguage` Enum

> **Story:** US-027 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Data Model | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The `PatientInstructionsGenerator` requires a Pydantic contract for:
1. Structured output returned by Gemini when generating plain-language patient instructions
2. The per-language translation container stored in `Document.translations` JSONB
3. The `SupportedLanguage` enum constraining the 5 supported language codes (`en`, `es`, `fr`, `zh`, `pt`)

This schema is the single source of truth consumed by TASK-002 (language detector), TASK-003 (generator core), TASK-004 (translation & back-check), and TASK-005 (ORM write).

---

## Acceptance Criteria Addressed

| US-027 AC | Requirement |
|---|---|
| **Scenario 3** | Primary output language driven by `SupportedLanguage` enum values |
| **Scenario 4** | `language_fallback` and `requested_language` fields captured in `Document.metadata` |

---

## Implementation Steps

### 1. Create `agents/documentation/patient_instructions_schemas.py`

```python
"""
Pydantic schemas for the PatientInstructionsGenerator structured output.

These models define the Gemini structured-output contract for patient-friendly
discharge instructions and per-language translation storage in Document.translations.

Supported languages (FR-022): English, Spanish, French, Chinese Simplified, Portuguese.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, Field


class SupportedLanguage(str, Enum):
    """BCP-47 language codes supported for patient instruction generation (FR-022)."""
    EN = "en"
    ES = "es"
    FR = "fr"
    ZH = "zh"
    PT = "pt"


class PatientInstructionsContent(BaseModel):
    """
    Structured patient instructions returned by Gemini Flash.

    All sections must use plain language at ≤6th-grade reading level (Scenario 1).
    Medical jargon must be replaced with common equivalents.
    """
    home_care_instructions: str = Field(
        ...,
        description=(
            "Step-by-step home care instructions written at a 6th-grade reading level. "
            "Use short sentences and common words. Avoid medical jargon."
        ),
    )
    medications: str = Field(
        ...,
        description=(
            "List each medicine with name, dose, when to take it, and why. "
            "Use plain language. Example: 'Take 1 white pill called metformin with breakfast each morning.'"
        ),
    )
    warning_signs: str = Field(
        ...,
        description=(
            "Clear signs that mean the patient should call a doctor or go to the emergency room. "
            "Use plain language bullet points."
        ),
    )
    follow_up_appointments: str = Field(
        ...,
        description=(
            "Who to call, when to make the appointment, and what to say. "
            "Include phone numbers if available."
        ),
    )
    diet_and_activity: str = Field(
        ...,
        description="Foods to eat or avoid, and what physical activities are safe.",
    )
    emergency_contact: str = Field(
        ...,
        description="When and how to contact emergency services or the care team.",
    )


class TranslationEntry(BaseModel):
    """A single translated version of patient instructions with quality metadata."""
    language_code: str = Field(..., description="BCP-47 language code, e.g. 'es'")
    content: PatientInstructionsContent = Field(
        ..., description="Translated instruction content"
    )
    back_translation_similarity: Optional[float] = Field(
        default=None,
        description=(
            "Cosine similarity (0.0–1.0) between original English and back-translated text. "
            "Must be ≥0.85 to pass quality check (Scenario 2)."
        ),
    )
    quality_check_passed: Optional[bool] = Field(
        default=None,
        description="True if back-translation similarity ≥ 0.85.",
    )
    flesch_kincaid_grade: Optional[float] = Field(
        default=None,
        description="Flesch-Kincaid Grade Level of this content (target ≤ 6.0).",
    )


class PatientInstructionsDocument(BaseModel):
    """
    Top-level container for patient instructions document.

    Stores the primary language output and all generated translations.
    Stored as JSON in Document.translations JSONB column.
    """
    primary_language: str = Field(
        ...,
        description="BCP-47 code of the primary output language derived from FHIR Patient.communication.",
    )
    primary_content: PatientInstructionsContent = Field(
        ..., description="Instructions in the primary language."
    )
    primary_flesch_kincaid_grade: float = Field(
        ...,
        description="FK Grade of primary (English base) content. Must be ≤ 6.0 after retry.",
    )
    translations: Dict[str, TranslationEntry] = Field(
        default_factory=dict,
        description="Keyed by BCP-47 language code. Populated for all 5 supported languages.",
    )
    language_fallback: bool = Field(
        default=False,
        description="True when patient's preferred language is not in SupportedLanguage.",
    )
    requested_language: Optional[str] = Field(
        default=None,
        description="The original BCP-47 code requested when fallback was triggered.",
    )
```

### 2. Create `agents/documentation/language_utils.py`

```python
"""
Language utility helpers for patient instruction generation.

Provides FHIR preferred-language extraction and SupportedLanguage resolution.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from agents.documentation.patient_instructions_schemas import SupportedLanguage

logger = logging.getLogger(__name__)

_SUPPORTED_CODES: frozenset[str] = frozenset(lang.value for lang in SupportedLanguage)


def resolve_patient_language(
    fhir_patient: dict,
) -> Tuple[SupportedLanguage, bool, Optional[str]]:
    """
    Extract preferred language from FHIR Patient.communication[0].language.coding[0].code.

    Returns:
        Tuple of (resolved_language, is_fallback, requested_language_code)

    Behaviour:
        - If preferred language is in SupportedLanguage → return it, fallback=False
        - If preferred language is not supported → return SupportedLanguage.EN, fallback=True
        - If Patient.communication is absent → return SupportedLanguage.EN, fallback=False
    """
    requested_code: Optional[str] = None

    try:
        communication = fhir_patient.get("communication", [])
        if communication:
            coding = (
                communication[0]
                .get("language", {})
                .get("coding", [{}])
            )
            requested_code = coding[0].get("code") if coding else None
    except (IndexError, KeyError, AttributeError):
        logger.warning("Failed to parse Patient.communication — defaulting to English.")
        return SupportedLanguage.EN, False, None

    if requested_code is None:
        return SupportedLanguage.EN, False, None

    # Normalise to lowercase BCP-47 base tag (e.g. "zh-CN" → "zh")
    normalised = requested_code.lower().split("-")[0]

    if normalised in _SUPPORTED_CODES:
        return SupportedLanguage(normalised), False, None

    logger.info(
        "Unsupported language '%s' requested — falling back to English.", requested_code
    )
    return SupportedLanguage.EN, True, requested_code
```

---

## File Locations

| File | Path |
|---|---|
| `patient_instructions_schemas.py` | `backend/agents/documentation/patient_instructions_schemas.py` |
| `language_utils.py` | `backend/agents/documentation/language_utils.py` |

---

## Validation Checklist

- [ ] `SupportedLanguage` enum has exactly 5 members: `en`, `es`, `fr`, `zh`, `pt`
- [ ] `PatientInstructionsContent` has 6 mandatory string fields (no Optional)
- [ ] `TranslationEntry.back_translation_similarity` is Optional (populated after back-check)
- [ ] `PatientInstructionsDocument.language_fallback` defaults to `False`
- [ ] `resolve_patient_language()` returns `(SupportedLanguage.EN, True, "ja")` for Japanese input
- [ ] `resolve_patient_language()` handles absent `communication` without raising
- [ ] No imports with side effects in schemas module

---

## Dependencies

| Dependency | Notes |
|---|---|
| `pydantic>=2.0` | Already in project requirements |
| `US-025 TASK-001` | Provides pattern for schema design |
