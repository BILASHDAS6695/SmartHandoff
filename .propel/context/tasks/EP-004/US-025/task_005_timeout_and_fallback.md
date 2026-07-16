---
id: TASK-005
title: "Implement 25s API Timeout and 28s Template Fallback for `DocumentationAgent`"
user_story: US-025
epic: EP-004
sprint: 2
layer: Backend — AI Agent / Resilience
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-001, TASK-003, TASK-004]
---

# TASK-005: Implement 25s API Timeout and 28s Template Fallback for `DocumentationAgent`

> **Story:** US-025 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — AI Agent / Resilience | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The 30-second SLA (Scenario 1) requires a layered timeout strategy:

| Layer | Threshold | Action |
|-------|-----------|--------|
| Vertex AI API call | 25 seconds | `asyncio.wait_for` raises `asyncio.TimeoutError` |
| Template fallback trigger | 28 seconds | `asyncio.TimeoutError` caught; Jinja2 template generates deterministic summary from FHIR fields |
| SLA boundary | 30 seconds | Document must be created before this deadline |

The 2-second buffer between 28s and 30s provides time for Jinja2 rendering, DB write, and SignalR push.

The fallback template must:
- Produce a complete `DischargeSummarySchema`-conformant output with all six mandatory sections
- Set `generation_type=TEMPLATE` on the resulting document
- Never raise an exception (Scenario 2)
- Use only the `EncounterContext` data — no LLM call

This task wraps the `DocumentationAgent.process()` LLM call from TASK-004 with the timeout/fallback decorator and implements the template fallback renderer.

---

## Acceptance Criteria Addressed

| US-025 AC | Requirement |
|---|---|
| **Scenario 1** | p95 generation latency <30 seconds — enforced by the 25s API timeout |
| **Scenario 2** | Template fallback triggered at 28s; `generation_type=TEMPLATE`; no exception thrown |

---

## Implementation Steps

### 1. Create `agents/documentation/fallback_renderer.py`

The fallback renderer produces a deterministic `DischargeSummarySchema` from the FHIR `EncounterContext` without any LLM call. It uses a separate Jinja2 template for structured deterministic text.

```python
"""
Template fallback renderer for DocumentationAgent.

Produces a deterministic DischargeSummarySchema from EncounterContext
when the Vertex AI Gemini call exceeds the 25-second timeout.
No LLM call is made. Output is fully deterministic.
"""
from __future__ import annotations

import logging
from typing import List

from agents.documentation.fhir_fetcher import EncounterContext
from agents.documentation.schemas import (
    DiagnosisEntry,
    DischargeSummarySchema,
    FollowUpInstruction,
    GenerationType,
    MedicationEntry,
    ProcedureEntry,
)

logger = logging.getLogger(__name__)


class TemplateFallbackRenderer:
    """
    Generates a structured DischargeSummarySchema from EncounterContext
    using deterministic field mapping — no LLM call.

    Used when Vertex AI Gemini exceeds the 25-second API timeout.
    All mandatory sections are populated with structured FHIR data or
    safe clinical defaults. Output generation_type is set to TEMPLATE.
    """

    def render(self, encounter: EncounterContext) -> DischargeSummarySchema:
        """
        Produce a template-based DischargeSummarySchema.

        Args:
            encounter: PHI-minimised FHIR encounter context.

        Returns:
            DischargeSummarySchema with generation_type=TEMPLATE.
            Never raises an exception.
        """
        logger.warning(
            "Using template fallback for discharge summary (AI timeout)",
            extra={"encounter_id": encounter.encounter_id},
        )

        return DischargeSummarySchema(
            encounter_id=encounter.encounter_id,
            generation_type=GenerationType.TEMPLATE,
            diagnosis_summary=self._map_diagnoses(encounter),
            procedures=self._map_procedures(encounter),
            medications_at_discharge=self._map_medications(encounter),
            follow_up_instructions=self._default_follow_up(),
            warning_signs=self._default_warning_signs(),
            activity_restrictions=self._default_activity_restrictions(encounter),
        )

    # -------------------------------------------------------------------------
    # Section mappers
    # -------------------------------------------------------------------------

    def _map_diagnoses(self, encounter: EncounterContext) -> List[DiagnosisEntry]:
        if not encounter.diagnoses:
            return [DiagnosisEntry(icd10_code="Z99.89", description="Condition details to be completed by physician", is_primary=True)]
        return [
            DiagnosisEntry(
                icd10_code=dx.icd10_code,
                description=dx.description,
                is_primary=dx.is_primary,
            )
            for dx in encounter.diagnoses
        ]

    def _map_medications(self, encounter: EncounterContext) -> List[MedicationEntry]:
        if not encounter.medications:
            return [MedicationEntry(drug_name="As prescribed", dose="As directed", frequency="As directed", route="oral")]
        return [
            MedicationEntry(
                drug_name=med.drug_name,
                dose=med.dose,
                frequency=med.frequency,
                route=med.route,
                rxnorm_code=med.rxnorm_code,
            )
            for med in encounter.medications
        ]

    def _map_procedures(self, encounter: EncounterContext) -> List[ProcedureEntry]:
        return [ProcedureEntry(description=proc) for proc in encounter.procedures_performed]

    def _default_follow_up(self) -> List[FollowUpInstruction]:
        return [
            FollowUpInstruction(
                instruction="Follow up with your primary care physician.",
                timeframe="within 7 days",
                provider_type="primary care physician",
            ),
            FollowUpInstruction(
                instruction="Contact your care team if your condition worsens.",
                timeframe="immediately if symptoms worsen",
            ),
        ]

    def _default_warning_signs(self) -> List[str]:
        return [
            "Call 911 or go to the emergency room if you have chest pain or trouble breathing.",
            "Call your doctor if you have a fever over 101°F (38.3°C).",
            "Call your doctor if your symptoms get worse or you have new symptoms.",
        ]

    def _default_activity_restrictions(self, encounter: EncounterContext) -> List[str]:
        los = encounter.length_of_stay_days or 0
        if los >= 3:
            return [
                "Rest at home for at least 2-3 days after discharge.",
                "Avoid strenuous activity until cleared by your doctor.",
                "Do not drive if you are taking narcotic pain medication.",
            ]
        return [
            "Resume normal activities gradually as tolerated.",
            "Avoid heavy lifting (over 10 lbs) until cleared by your doctor.",
        ]
```

### 2. Update `agents/documentation/agent.py` — Add Timeout Wrapper

Modify `DocumentationAgent.process()` in `agent.py` (from TASK-004) to wrap the LLM call with the layered timeout strategy:

```python
import asyncio
from agents.documentation.fallback_renderer import TemplateFallbackRenderer

# In DocumentationAgent.__init__:
self._fallback_renderer = TemplateFallbackRenderer()

# Replace the "Step 3: Invoke Gemini" block in process() with:

# Step 3: Invoke Gemini 1.5 Pro with 25-second timeout
start_ms = time.monotonic_ns() // 1_000_000
try:
    summary: DischargeSummarySchema = await asyncio.wait_for(
        self._chain.ainvoke(prompt_text),
        timeout=25.0,  # TR-004: 25s API timeout, 2s buffer before 28s fallback trigger
    )
    summary.generation_type = GenerationType.AI

except asyncio.TimeoutError:
    # 28-second boundary: AI timed out — fall back to deterministic template rendering
    logger.warning(
        "Gemini API timeout — activating template fallback",
        extra={"encounter_id": encounter_id, "timeout_seconds": 25},
    )
    summary = self._fallback_renderer.render(encounter_context)

except Exception as exc:
    # Unexpected LLM error — fall back rather than losing the document
    logger.error(
        "Gemini API error — activating template fallback",
        extra={"encounter_id": encounter_id, "error": str(exc)},
        exc_info=True,
    )
    summary = self._fallback_renderer.render(encounter_context)

summary.generation_duration_ms = (time.monotonic_ns() // 1_000_000) - start_ms
```

### 3. Unit Tests — `tests/agents/documentation/test_fallback_renderer.py`

```python
import pytest
from agents.documentation.fallback_renderer import TemplateFallbackRenderer
from agents.documentation.fhir_fetcher import (
    EncounterContext, DiagnosisContext, MedicationContext,
)
from agents.documentation.schemas import GenerationType


@pytest.fixture
def sample_context():
    return EncounterContext(
        encounter_id="ENC-001",
        admission_reason="Diabetes management",
        encounter_type="inpatient",
        discharge_disposition="Home",
        length_of_stay_days=3,
        diagnoses=[DiagnosisContext(icd10_code="E11.9", description="Type 2 diabetes", is_primary=True)],
        medications=[MedicationContext(drug_name="metformin", dose="500 mg", frequency="twice daily", route="oral")],
    )


def test_fallback_renders_without_exception(sample_context):
    renderer = TemplateFallbackRenderer()
    result = renderer.render(sample_context)
    assert result is not None


def test_fallback_generation_type_is_template(sample_context):
    renderer = TemplateFallbackRenderer()
    result = renderer.render(sample_context)
    assert result.generation_type == GenerationType.TEMPLATE


def test_fallback_all_mandatory_sections_populated(sample_context):
    renderer = TemplateFallbackRenderer()
    result = renderer.render(sample_context)
    assert len(result.diagnosis_summary) >= 1
    assert len(result.medications_at_discharge) >= 1
    assert len(result.follow_up_instructions) >= 1
    assert len(result.warning_signs) >= 1
    assert len(result.activity_restrictions) >= 1


def test_fallback_maps_fhir_diagnoses(sample_context):
    renderer = TemplateFallbackRenderer()
    result = renderer.render(sample_context)
    assert result.diagnosis_summary[0].icd10_code == "E11.9"


def test_fallback_maps_fhir_medications(sample_context):
    renderer = TemplateFallbackRenderer()
    result = renderer.render(sample_context)
    assert result.medications_at_discharge[0].drug_name == "metformin"


@pytest.mark.asyncio
async def test_agent_activates_fallback_on_timeout(mock_doc_repo):
    """Integration: agent falls back when chain.ainvoke times out."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from agents.documentation.agent import DocumentationAgent

    async def slow_invoke(_):
        await asyncio.sleep(30)  # Simulate timeout

    with patch("agents.documentation.agent.ChatVertexAI"):
        agent = DocumentationAgent(
            fhir_client=MagicMock(),
            document_repository=mock_doc_repo,
            project_id="test-project",
        )
        agent._chain = MagicMock()
        agent._chain.ainvoke = slow_invoke
        agent._fetcher.fetch = AsyncMock(
            return_value=EncounterContext(
                encounter_id="ENC-001",
                admission_reason="Test",
                encounter_type="inpatient",
                discharge_disposition=None,
                length_of_stay_days=1,
                diagnoses=[DiagnosisContext("E11.9", "Diabetes", True)],
                medications=[MedicationContext("metformin", "500 mg", "twice daily", "oral")],
            )
        )
        agent._renderer.render_discharge_summary = MagicMock(return_value="prompt")

        await agent.process({"event_type": "A03", "encounter_id": "ENC-001", "occurred_at": "2026-07-14T10:00:00Z"})

    call_kwargs = mock_doc_repo.create_discharge_document.call_args.kwargs
    assert call_kwargs["summary"].generation_type == GenerationType.TEMPLATE
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/agents/documentation/fallback_renderer.py` |
| **Update** | `backend/agents/documentation/agent.py` (add timeout wrapper to `process()`) |
| **Create** | `backend/tests/agents/documentation/test_fallback_renderer.py` |

---

## Definition of Done

- [ ] `asyncio.wait_for(..., timeout=25.0)` wraps the `_chain.ainvoke()` call
- [ ] `asyncio.TimeoutError` caught; `TemplateFallbackRenderer.render()` called; no exception propagated
- [ ] Unexpected LLM errors also fall back to template (defence-in-depth)
- [ ] `TemplateFallbackRenderer.render()` sets `generation_type=GenerationType.TEMPLATE`
- [ ] All six mandatory sections populated in fallback output
- [ ] 6 unit tests pass; timeout integration test confirms `generation_type=TEMPLATE` after simulated 30s delay

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `DischargeSummarySchema`, `GenerationType`, section models |
| TASK-002 | Task | `EncounterContext` used by fallback renderer |
| TASK-003 | Task | `PromptRenderer` used in `process()` before the timeout block |
| TASK-004 | Task | `agent.py` `process()` method modified in this task |
