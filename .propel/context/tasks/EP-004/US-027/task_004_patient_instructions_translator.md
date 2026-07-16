---
id: TASK-004
title: "Implement `PatientInstructionsTranslator` — Gemini Flash Translation + Back-Translation Quality Check"
user_story: US-027
epic: EP-004
sprint: 2
layer: Backend — AI Agent
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-001, TASK-002, TASK-003]
---

# TASK-004: Implement `PatientInstructionsTranslator` — Gemini Flash Translation + Back-Translation Quality Check

> **Story:** US-027 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — AI Agent | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

After English patient instructions are generated (TASK-003), this task translates them into the remaining 4 supported languages (`es`, `fr`, `zh`, `pt`) using Gemini Flash and validates each translation via a back-translation quality check.

**Back-translation pipeline (US-027 Technical Notes):**
1. Translate English → target language (Gemini Flash)
2. Translate target language → English back-translation (Gemini Flash)
3. Compute cosine similarity between original English and back-translated English using `paraphrase-multilingual-MiniLM-L12-v2` sentence embeddings
4. If similarity < 0.85, flag `quality_check_passed=False` in `TranslationEntry`

**FK scoring of translations:** Each translated output is also FK-scored for informational purposes (stored in `TranslationEntry.flesch_kincaid_grade`). No retry is applied to translations — FK enforcement is applied only to the English base (TASK-003).

**Concurrency:** All 4 language translations are issued concurrently via `asyncio.gather` to minimise total latency.

---

## Acceptance Criteria Addressed

| US-027 AC | Requirement |
|---|---|
| **Scenario 2** | Back-translation cosine similarity ≥ 85% flagged; < 85% sets `quality_check_passed=False` |
| **Scenario 3** | All 5 languages populated in `PatientInstructionsDocument.translations` |

---

## Implementation Steps

### 1. Create `agents/documentation/patient_instructions_translator.py`

```python
"""
PatientInstructionsTranslator — multilingual translation with back-translation quality check.

Translates English patient instructions into 4 additional languages (es, fr, zh, pt) using
Gemini Flash. Validates translation quality via back-translation cosine similarity using
sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2`.

Supported Languages (FR-022): en, es, fr, zh, pt.
Quality threshold: cosine similarity ≥ 0.85 (US-027 Scenario 2).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict

import numpy as np
from sentence_transformers import SentenceTransformer
from langchain_google_vertexai import ChatVertexAI

from agents.documentation.patient_instructions_schemas import (
    PatientInstructionsContent,
    PatientInstructionsDocument,
    SupportedLanguage,
    TranslationEntry,
)
from agents.documentation.reading_level_scorer import ReadingLevelScorer

logger = logging.getLogger(__name__)

# Sentence-transformer model for cosine similarity (US-027 Technical Notes)
_EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Back-translation quality threshold
_SIMILARITY_THRESHOLD: float = 0.85

# Language names for Gemini prompts
_LANGUAGE_NAMES: dict[str, str] = {
    "es": "Spanish",
    "fr": "French",
    "zh": "Chinese (Simplified)",
    "pt": "Portuguese (Brazilian)",
}

_TRANSLATION_PROMPT_TEMPLATE = (
    "You are a professional medical translator. "
    "Translate the following patient health instructions from English to {target_language}. "
    "Keep the same simple, plain-language style. Preserve all health information exactly. "
    "Do not add or remove any medical instructions.\n\n"
    "--- ENGLISH INSTRUCTIONS ---\n{text}\n--- END ---\n\n"
    "Return only the translated text in {target_language}. Do not include any English."
)

_BACK_TRANSLATION_PROMPT_TEMPLATE = (
    "Translate the following text from {source_language} to English. "
    "Translate precisely and literally.\n\n"
    "--- {source_language_upper} TEXT ---\n{text}\n--- END ---\n\n"
    "Return only the English translation."
)


class PatientInstructionsTranslator:
    """
    Translates English patient instructions into 4 non-English languages (es, fr, zh, pt).

    Performs back-translation quality check using sentence-transformers cosine similarity.
    Issues all 4 translations concurrently via asyncio.gather.

    Args:
        project_id: GCP project ID for Vertex AI.
        location: GCP region for Vertex AI.
    """

    def __init__(self, project_id: str, location: str = "us-central1") -> None:
        self._llm = ChatVertexAI(
            model_name="gemini-1.5-flash",
            project=project_id,
            location=location,
            temperature=0.1,
            max_output_tokens=2048,
        )
        # Load embedding model once; reused across all translation requests
        self._embedder = SentenceTransformer(_EMBEDDING_MODEL_NAME)
        self._scorer = ReadingLevelScorer()

    async def translate_all(
        self,
        instructions_doc: PatientInstructionsDocument,
    ) -> PatientInstructionsDocument:
        """
        Translate English instructions into es, fr, zh, pt concurrently.

        Updates `instructions_doc.translations` in place and returns the same object.

        Args:
            instructions_doc: Document with `primary_content` (English) already set by TASK-003.

        Returns:
            Updated PatientInstructionsDocument with `translations` dict fully populated.
        """
        english_text = self._content_to_plain_text(instructions_doc.primary_content)

        # Non-English languages to translate into
        target_langs = [lang for lang in SupportedLanguage if lang != SupportedLanguage.EN]

        # Issue all translations concurrently
        translation_results = await asyncio.gather(
            *[
                self._translate_single(english_text, lang)
                for lang in target_langs
            ],
            return_exceptions=True,
        )

        translations: Dict[str, TranslationEntry] = {}

        for lang, result in zip(target_langs, translation_results):
            if isinstance(result, Exception):
                logger.error(
                    "Translation to '%s' failed: %s", lang.value, result, exc_info=result
                )
                # Store failed entry — downstream ORM write records it for ops visibility
                translations[lang.value] = TranslationEntry(
                    language_code=lang.value,
                    content=instructions_doc.primary_content,  # English fallback content
                    back_translation_similarity=None,
                    quality_check_passed=False,
                    flesch_kincaid_grade=None,
                )
            else:
                translations[lang.value] = result

        # Also store English base in translations for completeness
        english_entry = self._build_english_entry(
            instructions_doc.primary_content,
            instructions_doc.primary_flesch_kincaid_grade,
        )
        translations[SupportedLanguage.EN.value] = english_entry

        # Return updated document (translations is immutable in Pydantic v2 — rebuild)
        return instructions_doc.model_copy(update={"translations": translations})

    async def _translate_single(
        self,
        english_text: str,
        target_lang: SupportedLanguage,
    ) -> TranslationEntry:
        """
        Translate English text to `target_lang` and perform back-translation quality check.

        Args:
            english_text: Concatenated plain-text English instructions.
            target_lang: Target SupportedLanguage.

        Returns:
            TranslationEntry with translation, similarity score, and quality flag.
        """
        lang_name = _LANGUAGE_NAMES[target_lang.value]

        # Step 1: Translate English → target language
        translate_prompt = _TRANSLATION_PROMPT_TEMPLATE.format(
            target_language=lang_name,
            text=english_text,
        )
        translation_response = await self._llm.ainvoke(translate_prompt)
        translated_text: str = translation_response.content.strip()

        # Step 2: Back-translate → English
        back_translate_prompt = _BACK_TRANSLATION_PROMPT_TEMPLATE.format(
            source_language=lang_name,
            source_language_upper=lang_name.upper(),
            text=translated_text,
        )
        back_response = await self._llm.ainvoke(back_translate_prompt)
        back_translated_text: str = back_response.content.strip()

        # Step 3: Cosine similarity between original English and back-translated English
        similarity = self._compute_cosine_similarity(english_text, back_translated_text)
        quality_passed = similarity >= _SIMILARITY_THRESHOLD

        if not quality_passed:
            logger.warning(
                "Back-translation quality check FAILED for '%s': similarity=%.3f (threshold=%.2f).",
                target_lang.value,
                similarity,
                _SIMILARITY_THRESHOLD,
            )

        # Step 4: FK grade of translation (informational; no retry for translations)
        fk_grade = self._scorer.aggregate_grade({"content": translated_text})

        # Step 5: Build TranslationEntry — wrap translated text back into content model
        # Use English field names but translated content (structural parity preserved)
        translated_content = PatientInstructionsContent(
            home_care_instructions=translated_text,
            medications=translated_text,
            warning_signs=translated_text,
            follow_up_appointments=translated_text,
            diet_and_activity=translated_text,
            emergency_contact=translated_text,
        )

        return TranslationEntry(
            language_code=target_lang.value,
            content=translated_content,
            back_translation_similarity=round(similarity, 4),
            quality_check_passed=quality_passed,
            flesch_kincaid_grade=round(fk_grade, 2),
        )

    def _compute_cosine_similarity(self, text_a: str, text_b: str) -> float:
        """
        Compute cosine similarity between two texts using sentence embeddings.

        Uses `paraphrase-multilingual-MiniLM-L12-v2` as specified in US-027 Technical Notes.

        Args:
            text_a: Original English text.
            text_b: Back-translated English text.

        Returns:
            Cosine similarity score in range [0.0, 1.0].
        """
        embeddings = self._embedder.encode([text_a, text_b], normalize_embeddings=True)
        similarity: float = float(np.dot(embeddings[0], embeddings[1]))
        return max(0.0, min(1.0, similarity))  # Clamp to [0, 1]

    @staticmethod
    def _content_to_plain_text(content: PatientInstructionsContent) -> str:
        """Concatenate all PatientInstructionsContent sections into a single text block."""
        return "\n\n".join([
            content.home_care_instructions,
            content.medications,
            content.warning_signs,
            content.follow_up_appointments,
            content.diet_and_activity,
            content.emergency_contact,
        ])

    @staticmethod
    def _build_english_entry(
        content: PatientInstructionsContent,
        fk_grade: float,
    ) -> TranslationEntry:
        """Build the English base TranslationEntry (no back-translation needed)."""
        return TranslationEntry(
            language_code=SupportedLanguage.EN.value,
            content=content,
            back_translation_similarity=None,  # N/A for source language
            quality_check_passed=True,          # English base is always the source of truth
            flesch_kincaid_grade=round(fk_grade, 2),
        )
```

### 2. Add `sentence-transformers` to backend requirements

Add to `backend/requirements.txt` (or `pyproject.toml`):

```
sentence-transformers>=2.7.0
```

---

## File Locations

| File | Path |
|---|---|
| `patient_instructions_translator.py` | `backend/agents/documentation/patient_instructions_translator.py` |

---

## Validation Checklist

- [ ] `translate_all()` returns `PatientInstructionsDocument` with 5 entries in `translations` (en, es, fr, zh, pt)
- [ ] English entry in `translations["en"]` has `quality_check_passed=True`
- [ ] Translations issued concurrently (all 4 `ainvoke` calls in `asyncio.gather`)
- [ ] Failed translation for a language stores English fallback content with `quality_check_passed=False`
- [ ] Cosine similarity computed with `paraphrase-multilingual-MiniLM-L12-v2`
- [ ] Similarity < 0.85 → `quality_check_passed=False`; similarity ≥ 0.85 → `True`
- [ ] `sentence-transformers` added to `requirements.txt`
- [ ] Gemini model is `gemini-1.5-flash` (not Pro)

---

## Dependencies

| Dependency | Notes |
|---|---|
| `TASK-001` | `PatientInstructionsContent`, `TranslationEntry`, `PatientInstructionsDocument`, `SupportedLanguage` |
| `TASK-002` | `ReadingLevelScorer` for FK grading of translated text |
| `sentence-transformers>=2.7.0` | New dependency — must be added to requirements |
| `numpy` | Already present in project |
