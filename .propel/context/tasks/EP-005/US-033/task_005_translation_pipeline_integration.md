---
id: TASK-005
title: "Translation Pipeline Integration — Reuse US-027 for Patient Preferred Language"
user_story: US-033
epic: EP-005
sprint: 2
layer: Backend / AI
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-033/TASK-003, US-027]
---

# TASK-005: Translation Pipeline Integration — Reuse US-027 for Patient Preferred Language

> **Story:** US-033 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend / AI | **Est:** 2 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-033 AC Scenario 4 requires that when a patient has `preferred_language ≠ en`, the medication summary is translated and stored as `Document.translations.{lang_code}`. The EP-004 translation pipeline (US-027) already delivers a reusable Gemini-powered translation service — this task wires that pipeline into the medication summary workflow.

**No new translation logic is written.** This task is purely an integration task: call the existing US-027 translation service with the medication summary text fields, then persist the translated summary alongside the English version in the `document.translations` JSONB map.

**Design references:**
- US-033 AC Scenario 4 — `preferred_language=es`; stored under `Document.translations.es`
- US-033 Definition of Done — "Language translation: reuse EP-004 translation pipeline (US-027)"
- design.md §4.1 — Vertex AI Gemini 1.5 Pro for translation (EP-004 pipeline)

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 4 — Spanish translation | Translation of summary triggered when `preferred_language=es`; stored under `Document.translations.es` |

---

## Implementation Steps

### 1. Identify the US-027 translation service interface

Locate the translation service from EP-004 / US-027. It is expected to expose:

```python
# backend/app/agents/documentation/translation/service.py (US-027)
class TranslationService:
    async def translate(
        self,
        text: str,
        target_language: str,   # ISO 639-1 code, e.g. "es", "zh", "fr"
        source_language: str = "en",
    ) -> str:
        """Translate text using Gemini via the EP-004 pipeline."""
        ...
```

If the interface differs, adapt the call below accordingly — do not duplicate logic.

### 2. Create `backend/app/agents/medication_reconciliation/summary/translator.py`

```python
"""Translates a MedicationSummaryOutput into the patient's preferred language.

Reuses the EP-004 / US-027 TranslationService — no new translation logic is added.
Iterates over text fields in each medication entry and translates each field
individually to preserve structure, then reassembles a translated
MedicationSummaryOutput.

Design refs:
    US-033 AC Scenario 4       — preferred_language=es; stored under Document.translations.es
    US-033 Definition of Done  — reuse EP-004 translation pipeline (US-027)
    design.md §4.1             — Vertex AI Gemini 1.5 Pro for translation
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.documentation.translation.service import TranslationService
from app.agents.medication_reconciliation.summary.schema import (
    ChangedMedicationEntry,
    MedicationEntry,
    MedicationSummaryOutput,
    StoppedMedicationEntry,
)

logger = logging.getLogger(__name__)

# Text fields to translate per entry type
_MEDICATION_ENTRY_TEXT_FIELDS = (
    "dosing_instructions",
    "purpose",
    "common_side_effects",
)
_STOPPED_ENTRY_TEXT_FIELDS = ("reason",)
_CHANGED_ENTRY_TEXT_FIELDS = ("dosing_instructions", "reason")


class MedicationSummaryTranslator:
    """Translates a MedicationSummaryOutput using the EP-004 translation pipeline.

    Args:
        translation_service: US-027 ``TranslationService`` instance.
    """

    def __init__(self, translation_service: TranslationService) -> None:
        self._svc = translation_service

    async def translate(
        self,
        summary: MedicationSummaryOutput,
        target_language: str,
    ) -> MedicationSummaryOutput:
        """Translate all text fields in the summary to ``target_language``.

        Drug names (``generic_name``, ``brand_name``, ``dose``) are NOT translated —
        only human-readable instructions, purpose, side effects, and reason fields.

        Args:
            summary: English ``MedicationSummaryOutput`` to translate.
            target_language: ISO 639-1 language code, e.g. ``"es"``.

        Returns:
            New ``MedicationSummaryOutput`` with text fields translated.
        """
        logger.info(
            "Translating medication summary to language=%s", target_language
        )
        translated_new = [
            await self._translate_medication_entry(med, target_language)
            for med in summary.new
        ]
        translated_stopped = [
            await self._translate_stopped_entry(med, target_language)
            for med in summary.stopped
        ]
        translated_changed = [
            await self._translate_changed_entry(med, target_language)
            for med in summary.changed
        ]
        translated_continued = [
            await self._translate_medication_entry(med, target_language)
            for med in summary.continued
        ]
        return MedicationSummaryOutput(
            new=translated_new,
            stopped=translated_stopped,
            changed=translated_changed,
            continued=translated_continued,
        )

    async def _translate_medication_entry(
        self, entry: MedicationEntry, lang: str
    ) -> MedicationEntry:
        translated_side_effects = [
            await self._svc.translate(effect, lang)
            for effect in entry.common_side_effects
        ]
        return entry.model_copy(
            update={
                "dosing_instructions": await self._svc.translate(
                    entry.dosing_instructions, lang
                ),
                "purpose": await self._svc.translate(entry.purpose, lang),
                "common_side_effects": translated_side_effects,
            }
        )

    async def _translate_stopped_entry(
        self, entry: StoppedMedicationEntry, lang: str
    ) -> StoppedMedicationEntry:
        reason = (
            await self._svc.translate(entry.reason, lang)
            if entry.reason
            else None
        )
        return entry.model_copy(update={"reason": reason})

    async def _translate_changed_entry(
        self, entry: ChangedMedicationEntry, lang: str
    ) -> ChangedMedicationEntry:
        reason = (
            await self._svc.translate(entry.reason, lang)
            if entry.reason
            else None
        )
        return entry.model_copy(
            update={
                "dosing_instructions": await self._svc.translate(
                    entry.dosing_instructions, lang
                ),
                "reason": reason,
            }
        )
```

### 3. Persist translated summary to `Document.translations`

In the Medication Reconciliation Agent event handler, after generating the English summary and writing it (TASK-004), check the patient's `preferred_language` and translate if needed:

```python
if patient.preferred_language and patient.preferred_language != "en":
    translated_summary = await self._translator.translate(
        summary=english_summary,
        target_language=patient.preferred_language,
    )
    # Merge into document.translations JSONB map
    await self._translation_writer.write(
        document_id=encounter.discharge_document_id,
        lang_code=patient.preferred_language,
        translated_summary=translated_summary,
    )
```

Add `TranslationWriter` inline in the agent or in a small helper:

```python
async def write_translation(
    db: AsyncSession,
    document_id: int,
    lang_code: str,
    translated_summary: MedicationSummaryOutput,
) -> None:
    """Merge translated medication summary into document.translations JSONB map."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if document is None:
        raise ValueError(f"Document id={document_id} not found for translation write")

    translations: dict[str, Any] = document.translations or {}
    translations[lang_code] = translated_summary.model_dump()
    document.translations = translations
    await db.flush()
    logger.info(
        "Translation written: document_id=%d lang=%s", document_id, lang_code
    )
```

> **Note:** `Document.translations` must be a JSONB column. Verify it exists; if absent, add alongside the TASK-004 Alembic migration.

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/medication_reconciliation/summary/translator.py` | Create |
| `backend/app/agents/medication_reconciliation/agent.py` | Update — wire `MedicationSummaryTranslator` after English summary written |
| `backend/app/models/document.py` | Verify `translations: Mapped[dict \| None]` JSONB column exists |

---

## Validation

- [ ] `MedicationSummaryTranslator.translate()` returns a new `MedicationSummaryOutput` (original not mutated)
- [ ] Drug names (`generic_name`, `brand_name`, `dose`) are NOT translated
- [ ] `common_side_effects` list items translated individually
- [ ] `reason` and `dosing_instructions` translated only when not `None`
- [ ] No new translation logic — `TranslationService` from US-027 called exclusively
- [ ] Translation skipped entirely when `patient.preferred_language == "en"` or `None`
- [ ] `document.translations.{lang_code}` JSONB map updated, not replaced

---

## Definition of Done

- [ ] `translator.py` implemented and peer-reviewed
- [ ] No duplication of Gemini translation logic from US-027
- [ ] Unit tests written in TASK-006 covering Spanish translation path
- [ ] Module-level docstring with `Design refs` complete
