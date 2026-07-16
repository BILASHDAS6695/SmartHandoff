---
id: TASK-003
title: "Author Jinja2 Prompt Template `discharge_summary.jinja2` with PHI Minimisation"
user_story: US-025
epic: EP-004
sprint: 2
layer: Backend — AI / Prompt Engineering
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-003: Author Jinja2 Prompt Template `discharge_summary.jinja2` with PHI Minimisation

> **Story:** US-025 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — AI / Prompt Engineering | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

Vertex AI Gemini 1.5 Pro accepts a rendered text prompt before producing structured JSON output. The Jinja2 template is the boundary where the `EncounterContext` (PHI-minimised FHIR data) is transformed into a clinical instruction prompt. This task authors the template and the `PromptRenderer` utility class that renders it.

**PHI Minimisation Rule (Scenario 4):** The template must:
- Accept only `EncounterContext` as input — which already excludes direct identifiers (enforced by TASK-002)
- Reference `encounter.encounter_id` (non-PHI reference key) — NOT patient name, address, phone, SSN, or DOB
- Reference `icd10_code` and `description` from diagnoses — NOT patient-linked demographics
- Log the rendered prompt at `DEBUG` level ONLY to the audit log sink (not the standard application log)

---

## Acceptance Criteria Addressed

| US-025 AC | Requirement |
|---|---|
| **Scenario 3** | Template instructs the model to populate all six mandatory sections |
| **Scenario 4** | Rendered prompt contains ICD-10 codes and generic descriptions; no name/address/phone/SSN |

---

## Implementation Steps

### 1. Create `agents/documentation/prompts/discharge_summary.jinja2`

```jinja2
{#-
  discharge_summary.jinja2
  Prompt template for Vertex AI Gemini 1.5 Pro discharge summary generation.

  Context variable: encounter (EncounterContext dataclass from fhir_fetcher.py)

  PHI Policy:
  - MUST use encounter.encounter_id as the patient reference key
  - MUST use icd10_code + description (not patient demographics)
  - MUST NOT reference patient name, DOB, address, phone, or SSN
  - Rendered output logged at DEBUG level to audit log only (not stdout)
-#}
You are a board-certified hospitalist physician assistant generating a structured clinical discharge summary.
Use only the encounter data provided below. Do not invent clinical details not present in the data.

ENCOUNTER REFERENCE: {{ encounter.encounter_id }}
ENCOUNTER TYPE: {{ encounter.encounter_type }}
ADMISSION REASON: {{ encounter.admission_reason }}
LENGTH OF STAY: {% if encounter.length_of_stay_days is not none %}{{ encounter.length_of_stay_days }} day(s){% else %}Not recorded{% endif %}
DISCHARGE DISPOSITION: {{ encounter.discharge_disposition or "Not specified" }}

DIAGNOSES:
{% for dx in encounter.diagnoses -%}
- [{{ dx.icd10_code }}] {{ dx.description }}{% if dx.is_primary %} (PRIMARY){% endif %}
{% endfor %}

MEDICATIONS AT DISCHARGE:
{% for med in encounter.medications -%}
- {{ med.drug_name }} {{ med.dose }} {{ med.frequency }} ({{ med.route }}){% if med.rxnorm_code %} [RxNorm: {{ med.rxnorm_code }}]{% endif %}
{% endfor %}

{% if encounter.procedures_performed %}
PROCEDURES PERFORMED:
{% for proc in encounter.procedures_performed -%}
- {{ proc }}
{% endfor %}
{% endif %}

---

TASK: Generate a complete structured discharge summary JSON with the following mandatory sections.
All patient-education text (follow_up_instructions, warning_signs, activity_restrictions) must be
written at a reading level ≤ 8th grade. Be specific and actionable.

Return ONLY valid JSON conforming to the DischargeSummarySchema. Do not include any explanatory text
outside the JSON object.

Required JSON structure:
{
  "encounter_id": "<encounter reference>",
  "diagnosis_summary": [{"icd10_code": "...", "description": "...", "is_primary": true|false}],
  "procedures": [{"cpt_code": "...", "description": "...", "date_performed": "..."}],
  "medications_at_discharge": [{"drug_name": "...", "dose": "...", "frequency": "...", "route": "...", "rxnorm_code": "..."}],
  "follow_up_instructions": [{"instruction": "...", "timeframe": "...", "provider_type": "..."}],
  "warning_signs": ["...", "..."],
  "activity_restrictions": ["...", "..."],
  "diet_instructions": ["..."],
  "wound_care_instructions": "..."
}
```

### 2. Create `agents/documentation/prompt_renderer.py`

```python
"""
Jinja2 prompt renderer for the Documentation Agent.

Renders the discharge_summary.jinja2 template with PHI-minimised
EncounterContext data. Logs rendered output at DEBUG level to the
audit log sink only — never to the application stdout log.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from agents.documentation.fhir_fetcher import EncounterContext

_TEMPLATES_DIR = Path(__file__).parent / "prompts"

# Audit logger: writes to a separate audit sink (Cloud Logging label: audit=true)
_audit_logger = logging.getLogger("audit.documentation_agent")

# Application logger: PHI-safe — must never log rendered prompt
_logger = logging.getLogger(__name__)


class PromptRenderer:
    """
    Renders Jinja2 prompt templates with PHI-minimised encounter context.

    Attributes:
        _env: Jinja2 Environment configured with StrictUndefined to catch
              template variable mismatches at render time.
    """

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            undefined=StrictUndefined,
            autoescape=False,  # Plain-text prompt; HTML escaping would corrupt clinical text
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_discharge_summary(self, encounter: EncounterContext) -> str:
        """
        Render the discharge summary prompt for a given EncounterContext.

        The rendered prompt is logged at DEBUG level ONLY via the audit logger.
        It is never written to the application log (stdout/stderr).

        Args:
            encounter: PHI-minimised encounter context from FHIREncounterFetcher.

        Returns:
            Rendered prompt string ready for the Vertex AI Gemini API call.

        Raises:
            jinja2.UndefinedError: If the template references a variable not
                present in the EncounterContext (caught by StrictUndefined).
        """
        template = self._env.get_template("discharge_summary.jinja2")
        rendered = template.render(encounter=encounter)

        # Audit log: DEBUG level, routed to audit sink only
        _audit_logger.debug(
            "Discharge summary prompt rendered",
            extra={
                "encounter_id": encounter.encounter_id,
                "prompt_char_length": len(rendered),
                # Full rendered prompt: audit log only, never stdout
                "prompt_preview_audit_only": rendered if os.getenv("AUDIT_LOG_FULL_PROMPT", "false") == "true" else "[REDACTED — set AUDIT_LOG_FULL_PROMPT=true to enable]",
            },
        )
        _logger.info(
            "Prompt rendered for encounter",
            extra={"encounter_id": encounter.encounter_id, "char_length": len(rendered)},
        )
        return rendered
```

### 3. Unit Tests — `tests/agents/documentation/test_prompt_renderer.py`

```python
import pytest
from agents.documentation.fhir_fetcher import (
    EncounterContext, DiagnosisContext, MedicationContext,
)
from agents.documentation.prompt_renderer import PromptRenderer

PHI_STRINGS = ["John", "Doe", "123 Main St", "555-1234", "123-45-6789", "01/01/1960"]


@pytest.fixture
def sample_context():
    return EncounterContext(
        encounter_id="ENC-001",
        admission_reason="Acute heart failure exacerbation",
        encounter_type="inpatient",
        discharge_disposition="Home",
        length_of_stay_days=4,
        diagnoses=[DiagnosisContext(icd10_code="I50.9", description="Heart failure, unspecified", is_primary=True)],
        medications=[MedicationContext(drug_name="lisinopril", dose="10 mg", frequency="once daily", route="oral", rxnorm_code="29046")],
    )


def test_rendered_prompt_contains_encounter_id(sample_context):
    renderer = PromptRenderer()
    prompt = renderer.render_discharge_summary(sample_context)
    assert "ENC-001" in prompt


def test_rendered_prompt_contains_icd10_code(sample_context):
    renderer = PromptRenderer()
    prompt = renderer.render_discharge_summary(sample_context)
    assert "I50.9" in prompt


def test_rendered_prompt_contains_no_phi(sample_context):
    renderer = PromptRenderer()
    prompt = renderer.render_discharge_summary(sample_context)
    for phi_value in PHI_STRINGS:
        assert phi_value not in prompt, f"PHI string '{phi_value}' found in rendered prompt"


def test_rendered_prompt_contains_all_required_sections_instructions(sample_context):
    renderer = PromptRenderer()
    prompt = renderer.render_discharge_summary(sample_context)
    required_section_mentions = [
        "diagnosis_summary", "medications_at_discharge",
        "follow_up_instructions", "warning_signs", "activity_restrictions",
    ]
    for section in required_section_mentions:
        assert section in prompt, f"Section '{section}' not referenced in prompt template"
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `backend/agents/documentation/prompts/discharge_summary.jinja2` |
| **Create** | `backend/agents/documentation/prompt_renderer.py` |
| **Create** | `backend/tests/agents/documentation/test_prompt_renderer.py` |

---

## Definition of Done

- [ ] `discharge_summary.jinja2` references `encounter.encounter_id` (not patient name) as the reference key
- [ ] Template renders all six mandatory section instructions in the JSON structure specification
- [ ] `PromptRenderer` uses `StrictUndefined` — missing context variables raise at render time, not silently
- [ ] Rendered prompt logged at `DEBUG` via `audit.documentation_agent` logger only (not application stdout)
- [ ] PHI test asserts no patient name, address, phone, or SSN strings appear in rendered output
- [ ] All 4 unit tests pass

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `DischargeSummarySchema` section names used in template JSON structure |
| TASK-002 | Task | `EncounterContext` is the template context variable |
| jinja2 | Library | Already in `pyproject.toml` as LangChain transitive dependency |
