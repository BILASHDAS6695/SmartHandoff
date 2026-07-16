---
id: TASK-007
title: "Unit Tests — FK Scoring, Language Fallback, and Back-Translation Quality Check"
user_story: US-027
epic: EP-004
sprint: 2
layer: Backend — Testing
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-007: Unit Tests — FK Scoring, Language Fallback, and Back-Translation Quality Check

> **Story:** US-027 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — Testing | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-027 DoD mandates unit tests for:
1. Flesch-Kincaid scoring and simplification retry trigger
2. Language fallback logic (supported + unsupported languages)
3. Back-translation quality check (pass/fail threshold)

All tests use `pytest` with `pytest-asyncio` for async tests and `unittest.mock` for Gemini/sentence-transformer mocking. No real Vertex AI or sentence-transformers calls are made in unit tests.

---

## Acceptance Criteria Addressed

All 4 US-027 scenarios validated by unit tests.

---

## Implementation Steps

### 1. Create `tests/agents/documentation/test_reading_level_scorer.py`

```python
"""
Unit tests for ReadingLevelScorer.

Validates FK grade computation, pass/fail threshold, and simplification prompt generation.
"""
import pytest
from agents.documentation.reading_level_scorer import (
    ReadingLevelScorer,
    FK_GRADE_TARGET,
    ScoringResult,
)


class TestReadingLevelScorer:
    """Tests for Flesch-Kincaid grade scoring."""

    def setup_method(self) -> None:
        self.scorer = ReadingLevelScorer()

    def test_simple_text_passes_grade_target(self) -> None:
        """Simple short sentences should score ≤ 6.0."""
        text = "Take one pill every day. Drink water. Rest at home."
        result = self.scorer.score(text)
        assert isinstance(result, ScoringResult)
        assert result.grade <= FK_GRADE_TARGET
        assert result.passes is True

    def test_complex_medical_text_fails_grade_target(self) -> None:
        """Complex medical jargon should exceed FK grade 6.0."""
        text = (
            "Administer the prescribed antihypertensive medication in accordance with "
            "the recommended pharmacological dosage and titration schedule to mitigate "
            "the risk of cardiovascular complications and cerebrovascular incidents."
        )
        result = self.scorer.score(text)
        assert result.grade > FK_GRADE_TARGET
        assert result.passes is False

    def test_aggregate_grade_empty_returns_zero(self) -> None:
        """aggregate_grade with empty dict must return 0.0 without raising."""
        grade = self.scorer.aggregate_grade({})
        assert grade == 0.0

    def test_aggregate_grade_multiple_sections(self) -> None:
        """aggregate_grade returns float average across sections."""
        sections = {
            "a": "Go home. Rest. Drink fluids.",
            "b": "Call your doctor if you feel worse.",
        }
        grade = self.scorer.aggregate_grade(sections)
        assert isinstance(grade, float)
        assert grade >= 0.0

    def test_build_simplify_prompt_contains_6th_grade(self) -> None:
        """Simplification prompt must reference '6th-grade'."""
        prompt = ReadingLevelScorer.build_simplify_prompt("Some complex text here.")
        assert "6th-grade" in prompt
        assert "Some complex text here." in prompt

    def test_score_all_sections_returns_per_section_results(self) -> None:
        """score_all_sections returns a result for each section key."""
        sections = {"intro": "Hello. Rest. Drink water.", "meds": "Take one tablet daily."}
        results = self.scorer.score_all_sections(sections)
        assert set(results.keys()) == {"intro", "meds"}
        assert all(isinstance(r, ScoringResult) for r in results.values())
```

### 2. Create `tests/agents/documentation/test_language_utils.py`

```python
"""
Unit tests for resolve_patient_language().

Validates supported language detection, unsupported language fallback,
and absent communication field handling.
"""
import pytest
from agents.documentation.language_utils import resolve_patient_language
from agents.documentation.patient_instructions_schemas import SupportedLanguage


class TestResolvePatientLanguage:
    """Tests for FHIR Patient.communication language resolution."""

    def _make_fhir_patient(self, lang_code: str) -> dict:
        """Build a minimal FHIR Patient resource with a single preferred language."""
        return {
            "communication": [
                {
                    "language": {
                        "coding": [{"code": lang_code}]
                    },
                    "preferred": True,
                }
            ]
        }

    def test_spanish_returns_es(self) -> None:
        """Spanish patient should resolve to SupportedLanguage.ES without fallback."""
        patient = self._make_fhir_patient("es")
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.ES
        assert fallback is False
        assert requested is None

    def test_french_returns_fr(self) -> None:
        patient = self._make_fhir_patient("fr")
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.FR
        assert fallback is False

    def test_chinese_returns_zh(self) -> None:
        patient = self._make_fhir_patient("zh")
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.ZH
        assert fallback is False

    def test_portuguese_returns_pt(self) -> None:
        patient = self._make_fhir_patient("pt")
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.PT
        assert fallback is False

    def test_japanese_falls_back_to_english(self) -> None:
        """US-027 Scenario 4: Japanese is not supported — must fall back to English."""
        patient = self._make_fhir_patient("ja")
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.EN
        assert fallback is True
        assert requested == "ja"

    def test_absent_communication_returns_english_no_fallback(self) -> None:
        """Patient with no communication field defaults to English without fallback."""
        patient: dict = {}
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.EN
        assert fallback is False
        assert requested is None

    def test_bcp47_subtag_normalised(self) -> None:
        """'zh-CN' should normalise to 'zh' and resolve to SupportedLanguage.ZH."""
        patient = self._make_fhir_patient("zh-CN")
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.ZH
        assert fallback is False

    def test_english_explicit_preference(self) -> None:
        """Explicit 'en' preference resolves to English without fallback."""
        patient = self._make_fhir_patient("en")
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.EN
        assert fallback is False

    def test_malformed_communication_returns_english(self) -> None:
        """Malformed communication field must not raise — returns English."""
        patient = {"communication": [{"language": {}}]}  # Missing 'coding'
        lang, fallback, requested = resolve_patient_language(patient)
        assert lang == SupportedLanguage.EN
```

### 3. Create `tests/agents/documentation/test_patient_instructions_generator.py`

```python
"""
Unit tests for PatientInstructionsGenerator.

Mocks Gemini Flash LLM calls. Validates FK retry logic, language detection,
and PatientInstructionsDocument structure.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.documentation.patient_instructions_generator import PatientInstructionsGenerator
from agents.documentation.patient_instructions_schemas import (
    PatientInstructionsContent,
    PatientInstructionsDocument,
    SupportedLanguage,
)
from agents.documentation.schemas import DischargeSummarySchema


def _make_mock_content(simple: bool = True) -> PatientInstructionsContent:
    """Return a PatientInstructionsContent stub."""
    text = (
        "Go home. Rest. Drink water. Call your doctor if you feel worse."
        if simple
        else (
            "Upon cessation of hospitalisation, the patient is advised to maintain "
            "strict pharmacological compliance with the prescribed antihypertensive regimen."
        )
    )
    return PatientInstructionsContent(
        home_care_instructions=text,
        medications="Take one pill each morning with food.",
        warning_signs="Call 911 if you cannot breathe.",
        follow_up_appointments="Call your doctor in 7 days.",
        diet_and_activity="Walk 10 minutes per day.",
        emergency_contact="Call 911 for emergencies.",
    )


def _make_discharge_summary() -> DischargeSummarySchema:
    """Return a minimal DischargeSummarySchema stub."""
    return DischargeSummarySchema(
        diagnoses=[],
        medications_at_discharge=[],
        procedures=[],
        follow_up_instructions="Follow up in 1 week.",
        warning_signs="Chest pain, shortness of breath.",
        activity_restrictions="No heavy lifting.",
    )


@pytest.fixture
def generator() -> PatientInstructionsGenerator:
    return PatientInstructionsGenerator(project_id="test-project")


class TestPatientInstructionsGenerator:
    """Tests for English instruction generation and FK retry."""

    @pytest.mark.asyncio
    async def test_generate_returns_document_with_empty_translations(
        self, generator: PatientInstructionsGenerator
    ) -> None:
        """generate() returns PatientInstructionsDocument with empty translations dict."""
        mock_content = _make_mock_content(simple=True)

        with patch.object(generator, "_generate_english_with_retry", new=AsyncMock(
            return_value=(mock_content, 4.5)
        )):
            result = await generator.generate(
                discharge_summary=_make_discharge_summary(),
                fhir_patient={},
            )

        assert isinstance(result, PatientInstructionsDocument)
        assert result.translations == {}
        assert result.primary_flesch_kincaid_grade == 4.5

    @pytest.mark.asyncio
    async def test_japanese_patient_sets_fallback(
        self, generator: PatientInstructionsGenerator
    ) -> None:
        """US-027 Scenario 4: Japanese patient triggers language_fallback=True."""
        mock_content = _make_mock_content()
        fhir_patient = {
            "communication": [{"language": {"coding": [{"code": "ja"}]}, "preferred": True}]
        }

        with patch.object(generator, "_generate_english_with_retry", new=AsyncMock(
            return_value=(mock_content, 3.0)
        )):
            result = await generator.generate(
                discharge_summary=_make_discharge_summary(),
                fhir_patient=fhir_patient,
            )

        assert result.language_fallback is True
        assert result.requested_language == "ja"
        assert result.primary_language == SupportedLanguage.EN.value

    @pytest.mark.asyncio
    async def test_spanish_patient_sets_primary_language_es(
        self, generator: PatientInstructionsGenerator
    ) -> None:
        """US-027 Scenario 3: Spanish patient sets primary_language='es'."""
        mock_content = _make_mock_content()
        fhir_patient = {
            "communication": [{"language": {"coding": [{"code": "es"}]}, "preferred": True}]
        }

        with patch.object(generator, "_generate_english_with_retry", new=AsyncMock(
            return_value=(mock_content, 3.5)
        )):
            result = await generator.generate(
                discharge_summary=_make_discharge_summary(),
                fhir_patient=fhir_patient,
            )

        assert result.primary_language == "es"
        assert result.language_fallback is False
        assert result.requested_language is None
```

### 4. Create `tests/agents/documentation/test_patient_instructions_translator.py`

```python
"""
Unit tests for PatientInstructionsTranslator.

Mocks Gemini Flash and sentence-transformers. Validates back-translation
similarity threshold enforcement and concurrent translation.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.documentation.patient_instructions_translator import (
    PatientInstructionsTranslator,
    _SIMILARITY_THRESHOLD,
)
from agents.documentation.patient_instructions_schemas import (
    PatientInstructionsContent,
    PatientInstructionsDocument,
    SupportedLanguage,
)


def _make_instructions_doc() -> PatientInstructionsDocument:
    content = PatientInstructionsContent(
        home_care_instructions="Rest at home.",
        medications="Take one pill daily.",
        warning_signs="Call 911 for chest pain.",
        follow_up_appointments="See your doctor in 7 days.",
        diet_and_activity="Walk 10 minutes daily.",
        emergency_contact="Call 911.",
    )
    return PatientInstructionsDocument(
        primary_language="en",
        primary_content=content,
        primary_flesch_kincaid_grade=4.2,
        translations={},
        language_fallback=False,
        requested_language=None,
    )


@pytest.fixture
def translator() -> PatientInstructionsTranslator:
    return PatientInstructionsTranslator(project_id="test-project")


class TestPatientInstructionsTranslator:
    """Tests for back-translation quality check and translation coverage."""

    @pytest.mark.asyncio
    async def test_translate_all_produces_5_language_entries(
        self, translator: PatientInstructionsTranslator
    ) -> None:
        """translate_all() must populate translations for en, es, fr, zh, pt."""
        mock_llm_response = MagicMock()
        mock_llm_response.content = "Translated text here."

        with (
            patch.object(translator._llm, "ainvoke", new=AsyncMock(return_value=mock_llm_response)),
            patch.object(translator, "_compute_cosine_similarity", return_value=0.92),
        ):
            result = await translator.translate_all(_make_instructions_doc())

        assert set(result.translations.keys()) == {"en", "es", "fr", "zh", "pt"}

    @pytest.mark.asyncio
    async def test_high_similarity_sets_quality_passed_true(
        self, translator: PatientInstructionsTranslator
    ) -> None:
        """Cosine similarity ≥ 0.85 → quality_check_passed=True."""
        mock_llm_response = MagicMock()
        mock_llm_response.content = "Texto traducido."

        with (
            patch.object(translator._llm, "ainvoke", new=AsyncMock(return_value=mock_llm_response)),
            patch.object(translator, "_compute_cosine_similarity", return_value=0.91),
        ):
            result = await translator.translate_all(_make_instructions_doc())

        for lang in ["es", "fr", "zh", "pt"]:
            assert result.translations[lang].quality_check_passed is True

    @pytest.mark.asyncio
    async def test_low_similarity_sets_quality_passed_false(
        self, translator: PatientInstructionsTranslator
    ) -> None:
        """US-027 Scenario 2: Cosine similarity < 0.85 → quality_check_passed=False."""
        mock_llm_response = MagicMock()
        mock_llm_response.content = "Poorly translated text."

        with (
            patch.object(translator._llm, "ainvoke", new=AsyncMock(return_value=mock_llm_response)),
            patch.object(translator, "_compute_cosine_similarity", return_value=0.72),
        ):
            result = await translator.translate_all(_make_instructions_doc())

        for lang in ["es", "fr", "zh", "pt"]:
            assert result.translations[lang].quality_check_passed is False
            assert result.translations[lang].back_translation_similarity == pytest.approx(0.72, abs=0.001)

    @pytest.mark.asyncio
    async def test_english_entry_always_passes(
        self, translator: PatientInstructionsTranslator
    ) -> None:
        """English base entry in translations must always have quality_check_passed=True."""
        mock_llm_response = MagicMock()
        mock_llm_response.content = "Some translation."

        with (
            patch.object(translator._llm, "ainvoke", new=AsyncMock(return_value=mock_llm_response)),
            patch.object(translator, "_compute_cosine_similarity", return_value=0.50),
        ):
            result = await translator.translate_all(_make_instructions_doc())

        assert result.translations["en"].quality_check_passed is True

    def test_compute_cosine_similarity_clamped_between_0_and_1(
        self, translator: PatientInstructionsTranslator
    ) -> None:
        """_compute_cosine_similarity result must always be in [0.0, 1.0]."""
        import numpy as np
        with patch.object(translator._embedder, "encode", return_value=np.array([[1.0, 0.0], [1.0, 0.0]])):
            sim = translator._compute_cosine_similarity("text a", "text b")
        assert 0.0 <= sim <= 1.0
```

---

## File Locations

| File | Path |
|---|---|
| `test_reading_level_scorer.py` | `backend/tests/agents/documentation/test_reading_level_scorer.py` |
| `test_language_utils.py` | `backend/tests/agents/documentation/test_language_utils.py` |
| `test_patient_instructions_generator.py` | `backend/tests/agents/documentation/test_patient_instructions_generator.py` |
| `test_patient_instructions_translator.py` | `backend/tests/agents/documentation/test_patient_instructions_translator.py` |

---

## Validation Checklist

- [ ] All tests pass with `pytest -v tests/agents/documentation/`
- [ ] No real Vertex AI or sentence-transformers calls made (all mocked)
- [ ] FK scorer tests cover both pass and fail threshold
- [ ] Language fallback tested for at least: `ja` (unsupported), `es` (supported), absent field, `zh-CN` BCP-47 subtag
- [ ] Back-translation tests cover similarity ≥ 0.85 (pass) and < 0.85 (fail)
- [ ] English entry in translations always `quality_check_passed=True`
- [ ] `pytest-asyncio` used for all `async def` test functions

---

## Dependencies

| Dependency | Notes |
|---|---|
| `pytest>=8.0` | Already in dev requirements |
| `pytest-asyncio>=0.23` | Required for async tests |
| `TASK-001` | Schemas under test |
| `TASK-002` | `ReadingLevelScorer` under test |
| `TASK-003` | `PatientInstructionsGenerator` under test |
| `TASK-004` | `PatientInstructionsTranslator` under test |
