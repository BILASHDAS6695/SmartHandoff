---
id: TASK-003
title: "MedicationSummaryGenerator Class + Gemini Flash Prompt"
user_story: US-033
epic: EP-005
sprint: 2
layer: Backend / AI
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-033/TASK-001, US-033/TASK-002, US-030]
---

# TASK-003: `MedicationSummaryGenerator` Class + Gemini Flash Prompt

> **Story:** US-033 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend / AI | **Est:** 4 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This is the core deliverable of US-033. `MedicationSummaryGenerator` takes a reconciliation result produced by US-030, enriches each medication with brand names (TASK-001), calls **Gemini Flash** (not Pro — lower complexity task), and returns a validated `MedicationSummaryOutput` (TASK-002) in plain language the patient can understand.

Gemini Flash is used per US-033 Technical Notes: plain-language rewriting is lower complexity than clinical summary generation. The Gemini call uses JSON output mode with the `MedicationSummaryOutput` schema to guarantee a parseable, structured response.

**Design references:**
- US-033 Definition of Done — `MedicationSummaryGenerator` class, Gemini Flash prompt, output schema
- US-033 AC Scenario 1 — new (purpose + dosing + side effects), stopped, changed sections
- US-033 AC Scenario 2 — brand name enrichment before LLM call
- US-033 Technical Notes — Gemini Flash; dosing format: "Take 1 tablet (500mg) twice daily with food"
- design.md §4.1 — Vertex AI Gemini 1.5 Pro (Flash variant); LangChain `streaming=False` for structured output

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 1 | Gemini Flash generates new / stopped / changed / continued sections |
| AC Scenario 2 | Brand name enrichment applied before LLM prompt construction |

---

## Implementation Steps

### 1. Create `backend/app/agents/medication_reconciliation/summary/generator.py`

```python
"""MedicationSummaryGenerator — converts reconciliation results into a patient-readable
medication change summary using Gemini Flash.

Workflow:
  1. Receive a ReconciliationResult (from US-030).
  2. Enrich each medication with RxNav brand names via BrandNameEnricher (TASK-001).
  3. Build a structured Gemini Flash prompt from the enriched medication list.
  4. Call Vertex AI Gemini Flash with JSON output mode.
  5. Validate response against MedicationSummaryOutput schema (TASK-002).
  6. Return validated MedicationSummaryOutput.

Design refs:
    US-033 Definition of Done  — MedicationSummaryGenerator class
    US-033 AC Scenario 1       — new/stopped/changed/continued sections with purpose + dosing
    US-033 AC Scenario 2       — brand name enrichment before LLM call
    US-033 Technical Notes     — Gemini Flash; JSON output mode; dosing format
    design.md §4.1             — LangChain + Vertex AI (Gemini Flash); structured output via Pydantic
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agents.medication_reconciliation.brand_name.enricher import BrandNameEnricher
from app.agents.medication_reconciliation.summary.schema import MedicationSummaryOutput

logger = logging.getLogger(__name__)

# Gemini Flash — lower-cost model for plain-language rewriting tasks
_GEMINI_MODEL = "gemini-1.5-flash"
_TEMPERATURE = 0.2  # low temperature for consistent, factual output
_MAX_OUTPUT_TOKENS = 2048


_SYSTEM_PROMPT = """\
You are a patient education specialist helping hospital patients understand their
discharge medications. Write in plain, friendly English at a 6th-grade reading level.
Avoid medical jargon. Use the drug's brand name in parentheses after the generic name
where provided. Return your response as valid JSON only — no markdown, no explanation.
"""

_USER_PROMPT_TEMPLATE = """\
A patient is being discharged from hospital. Their medication changes are listed below.
Write a patient-friendly medication summary with four sections: "new", "stopped",
"changed", and "continued".

For each NEW medication include:
  - generic_name, brand_name (if provided), dose, dosing_instructions
    (format: "Take X tablet(s) (Xmg) [frequency] [with/without food]"),
    purpose (e.g. "to lower your blood pressure"),
    common_side_effects (up to 3 plain-language items)

For each STOPPED medication include:
  - generic_name, brand_name (if provided), dose, reason (if known, else null)

For each CHANGED medication include:
  - generic_name, brand_name (if provided), previous_dose, new_dose,
    dosing_instructions, reason (if known, else null)

For each CONTINUED medication include:
  - generic_name, brand_name (if provided), dose, dosing_instructions, purpose,
    common_side_effects (may be empty list)

Medication changes:
{medication_changes_json}

Return a JSON object with keys: "new", "stopped", "changed", "continued".
Each key maps to a list of medication objects as described above.
"""


class MedicationSummaryGenerator:
    """Generates a patient-readable medication change summary using Gemini Flash.

    Args:
        enricher: ``BrandNameEnricher`` for RxNav brand name lookups.
        project: GCP project ID for Vertex AI.
        location: GCP region for Vertex AI (default ``"us-central1"``).
    """

    def __init__(
        self,
        enricher: BrandNameEnricher,
        project: str,
        location: str = "us-central1",
    ) -> None:
        self._enricher = enricher
        self._llm = ChatVertexAI(
            model_name=_GEMINI_MODEL,
            project=project,
            location=location,
            temperature=_TEMPERATURE,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
        )

    async def generate(
        self, reconciliation_result: dict[str, Any]
    ) -> MedicationSummaryOutput:
        """Generate a plain-language medication summary from a reconciliation result.

        Args:
            reconciliation_result: Dict produced by the medication reconciliation
                agent (US-030). Expected keys: ``new``, ``stopped``, ``changed``,
                ``continued`` — each a list of medication dicts with at minimum
                ``generic_name``, ``rxcui``, and ``dose`` fields.

        Returns:
            Validated ``MedicationSummaryOutput`` instance.

        Raises:
            ValueError: If Gemini returns invalid JSON or schema validation fails.
        """
        enriched = await self._enrich_medications(reconciliation_result)
        prompt = _USER_PROMPT_TEMPLATE.format(
            medication_changes_json=json.dumps(enriched, indent=2)
        )
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]
        response = await self._llm.ainvoke(messages)
        raw_json = response.content.strip()

        try:
            parsed = json.loads(raw_json)
            return MedicationSummaryOutput.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.error(
                "MedicationSummaryGenerator: schema validation failed — %s | raw=%s",
                exc,
                raw_json[:500],
            )
            raise ValueError(
                f"Gemini Flash returned an invalid medication summary: {exc}"
            ) from exc

    async def _enrich_medications(
        self, reconciliation_result: dict[str, Any]
    ) -> dict[str, Any]:
        """Enrich all medications in the reconciliation result with brand names.

        Args:
            reconciliation_result: Raw reconciliation result dict.

        Returns:
            Deep copy of the reconciliation result with ``brand_name`` fields
            added to each medication entry.
        """
        enriched: dict[str, list[dict[str, Any]]] = {}
        for category in ("new", "stopped", "changed", "continued"):
            medications = reconciliation_result.get(category, [])
            enriched_meds: list[dict[str, Any]] = []
            for med in medications:
                rxcui = med.get("rxcui", "")
                generic_name = med.get("generic_name", med.get("name", ""))
                if rxcui:
                    result = await self._enricher.enrich(rxcui, generic_name)
                    enriched_meds.append({**med, "brand_name": result.brand_name})
                else:
                    enriched_meds.append({**med, "brand_name": None})
            enriched[category] = enriched_meds
        return enriched
```

---

## File Checklist

| File | Action |
|------|--------|
| `backend/app/agents/medication_reconciliation/summary/generator.py` | Create |

---

## Validation

- [ ] `MedicationSummaryGenerator.generate()` returns a `MedicationSummaryOutput` instance
- [ ] Gemini Flash model name is `gemini-1.5-flash` (not Pro)
- [ ] Brand name enrichment (`_enrich_medications`) called before prompt construction
- [ ] `ValueError` raised if Gemini returns unparseable JSON (no silent swallowing)
- [ ] Temperature = 0.2 (deterministic factual output)
- [ ] System prompt instructs 6th-grade reading level and JSON-only output
- [ ] Dosing instructions use the prescribed format: "Take X tablet(s) (Xmg) [frequency]"

---

## Definition of Done

- [ ] `generator.py` implemented and peer-reviewed
- [ ] Imports `BrandNameEnricher` from TASK-001 and `MedicationSummaryOutput` from TASK-002
- [ ] LangChain `ainvoke` used for async Vertex AI call
- [ ] Module-level docstring with `Design refs` complete
- [ ] Unit tests written in TASK-006
