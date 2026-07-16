---
id: TASK-006
title: "Integrate `PatientInstructionsGenerator` into `DocumentationAgent` Pipeline"
user_story: US-027
epic: EP-004
sprint: 2
layer: Backend — AI Agent
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-001, TASK-003, TASK-004, TASK-005, US-025 TASK-004]
---

# TASK-006: Integrate `PatientInstructionsGenerator` into `DocumentationAgent` Pipeline

> **Story:** US-027 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — AI Agent | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

`PatientInstructionsGenerator` (TASK-003) and `PatientInstructionsTranslator` (TASK-004) are standalone components. This task wires them into the existing `DocumentationAgent.process_event()` pipeline (US-025 TASK-004) so that after a discharge summary `Document` record is created, patient instructions are automatically generated, translated, and persisted.

**Pipeline sequence after this task:**
1. `DocumentationAgent` generates `DischargeSummarySchema` (existing — US-025)
2. `DocumentRepository.create_discharge_document()` creates the `Document` record (existing — US-025 TASK-006)
3. **NEW:** `PatientInstructionsGenerator.generate()` produces English instructions with FK enforcement
4. **NEW:** `PatientInstructionsTranslator.translate_all()` translates into 4 languages with quality check
5. **NEW:** `DocumentRepository.save_patient_instructions()` persists translations to the Document record

Steps 3–5 run after step 2 completes; failure in steps 3–5 must not roll back the discharge summary.

---

## Acceptance Criteria Addressed

| US-027 AC | Requirement |
|---|---|
| **Scenario 3** | Patient instructions generated in preferred language; English stored as fallback |
| **Scenario 4** | Unsupported language falls back to English with `language_fallback=True` |

---

## Implementation Steps

### 1. Update `agents/documentation/agent.py` — inject new components

```python
# In DocumentationAgent.__init__(), add new dependencies:

from agents.documentation.patient_instructions_generator import PatientInstructionsGenerator
from agents.documentation.patient_instructions_translator import PatientInstructionsTranslator

class DocumentationAgent(BaseAgent):

    def __init__(
        self,
        fhir_client: FHIRClient,
        document_repository: DocumentRepository,
        project_id: str,
        location: str = "us-central1",
    ) -> None:
        super().__init__(subscription_id=self.SUBSCRIPTION_ID)

        # Existing from US-025
        self._fetcher = FHIREncounterFetcher(fhir_client)
        self._renderer = PromptRenderer()
        self._doc_repo = document_repository
        self._llm = ChatVertexAI(...)  # existing

        # NEW — US-027
        self._instructions_generator = PatientInstructionsGenerator(
            project_id=project_id, location=location
        )
        self._instructions_translator = PatientInstructionsTranslator(
            project_id=project_id, location=location
        )
```

### 2. Update `DocumentationAgent.process_event()` — call patient instructions pipeline

Add steps 3–5 after the existing discharge summary ORM write. Wrap in a separate try/except to prevent patient instructions failure from rolling back the discharge summary:

```python
async def process_event(self, event: ADTEvent) -> None:
    """
    Process an ADT event: generate discharge summary and patient instructions.

    Discharge summary generation is the primary outcome (US-025).
    Patient instructions generation is a secondary outcome (US-027).
    Failure in patient instructions generation is logged but does not raise,
    preserving the discharge summary record.
    """
    # --- Existing US-025 pipeline ---
    fhir_encounter = await self._fetcher.fetch(event.encounter_id)
    fhir_patient = await self._fetcher.fetch_patient(event.patient_id)
    prompt_text = self._renderer.render(fhir_encounter)

    discharge_summary: DischargeSummarySchema = await self._call_llm_with_fallback(
        prompt_text, event
    )
    document = await self._doc_repo.create_discharge_document(
        encounter_id=event.encounter_id,
        patient_id=event.patient_id,
        summary=discharge_summary,
    )
    # --- End existing US-025 pipeline ---

    # --- NEW US-027 pipeline: patient instructions ---
    await self._generate_patient_instructions(
        document_id=document.id,
        discharge_summary=discharge_summary,
        fhir_patient=fhir_patient,
    )

async def _generate_patient_instructions(
    self,
    document_id: int,
    discharge_summary: DischargeSummarySchema,
    fhir_patient: dict,
) -> None:
    """
    Generate and persist patient instructions (US-027).

    Designed to be called after the discharge summary Document record is committed.
    Failures are caught and logged — they do not propagate to the Pub/Sub consumer
    to avoid nacking the event and causing retry storms.

    Args:
        document_id: PK of the newly-created Document record.
        discharge_summary: Structured discharge summary from US-025 pipeline.
        fhir_patient: Raw FHIR Patient resource for language detection.
    """
    try:
        # Step 3: Generate English instructions with FK enforcement
        instructions_doc = await self._instructions_generator.generate(
            discharge_summary=discharge_summary,
            fhir_patient=fhir_patient,
        )

        # Step 4: Translate into 4 non-English languages with quality check
        instructions_doc = await self._instructions_translator.translate_all(
            instructions_doc
        )

        # Step 5: Persist to Document.translations and Document.metadata
        await self._doc_repo.save_patient_instructions(
            document_id=document_id,
            instructions_doc=instructions_doc,
        )

        logger.info(
            "Patient instructions generated and saved for document %d "
            "(primary_lang=%s, fallback=%s, fk_grade=%.2f).",
            document_id,
            instructions_doc.primary_language,
            instructions_doc.language_fallback,
            instructions_doc.primary_flesch_kincaid_grade,
        )

    except Exception:
        logger.exception(
            "Patient instructions generation failed for document %d — "
            "discharge summary record is unaffected.",
            document_id,
        )
```

---

## File Locations

| File | Path |
|---|---|
| `agent.py` (update) | `backend/agents/documentation/agent.py` |

---

## Validation Checklist

- [ ] `DocumentationAgent.__init__()` instantiates `PatientInstructionsGenerator` and `PatientInstructionsTranslator`
- [ ] `_generate_patient_instructions()` is called after `create_discharge_document()` succeeds
- [ ] Exception in `_generate_patient_instructions()` is caught and logged — does not re-raise
- [ ] `process_event()` completes and ACKs the Pub/Sub message even if patient instructions fail
- [ ] `fhir_patient` dict is passed from FHIR fetch and forwarded to `generate()`
- [ ] `save_patient_instructions()` called with the new document's PK

---

## Dependencies

| Dependency | Notes |
|---|---|
| `TASK-003` | `PatientInstructionsGenerator` |
| `TASK-004` | `PatientInstructionsTranslator` |
| `TASK-005` | `DocumentRepository.save_patient_instructions()` |
| `US-025 TASK-004` | `DocumentationAgent` base to extend |
