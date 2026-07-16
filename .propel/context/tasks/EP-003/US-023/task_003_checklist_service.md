---
id: TASK-003
title: "Create `coordinator-agent/app/checklist/checklist_service.py` — ChecklistService with Gemini Structured Output, 15s Timeout, and Template Fallback"
user_story: US-023
epic: EP-003
sprint: 2
layer: Backend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-023/TASK-001, US-023/TASK-002]
---

# TASK-003: Create `coordinator-agent/app/checklist/checklist_service.py` — ChecklistService with Gemini Structured Output, 15s Timeout, and Template Fallback

> **Story:** US-023 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-023 mandates (ADR-004, TR-004, AIR-021):

> *"Vertex AI Gemini call with structured output schema … 15-second timeout on Gemini call; template fallback with pre-defined items per transition type"*

`ChecklistService` is the single orchestration class responsible for:

1. Rendering `prompts/checklist.jinja2` with minimum-necessary clinical context (TASK-002)
2. Calling Vertex AI Gemini with `response_schema=HandoffChecklist.llm_response_schema()` for structured JSON output
3. Enforcing a **15-second** `asyncio.wait_for` timeout — on expiry, loading the fallback from `config/checklist_templates.yaml`
4. Returning a validated `HandoffChecklist` instance annotated with `generated_type="LLM"` or `generated_type="TEMPLATE"`

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `asyncio.wait_for(timeout=15)` | US-023 AC Scenario 4 — exact 15s contract; async-native; no blocking |
| `response_schema` Gemini parameter | ADR-004 — structured output enforced at API level; no fragile JSON regex parsing |
| Jinja2 `Environment(loader=FileSystemLoader)` | Template loaded once at service init; not re-read on every call |
| YAML fallback loaded at service init | Eliminates file I/O on the hot fallback path; loaded once, cached in memory |
| `ChecklistInput` Pydantic model | Validates caller-supplied context before prompt rendering; rejects PHI fields |
| Minimum-necessary PHI: `ChecklistInput` has no `patient_name`/`mrn`/`dob` | AIR-021 compliance enforced at type level |

Design refs: ADR-004, TR-004, AIR-020, AIR-021, US-023 DoD, AC Scenarios 1–4.

---

## Acceptance Criteria Addressed

| US-023 AC | Requirement |
|---|---|
| **Scenario 1** | `ChecklistService.generate()` returns `HandoffChecklist` with ≥3 patient-specific items for discharge scenario |
| **Scenario 2** | `ChecklistInput` model has no PHI fields; PHI audit unit test (TASK-005) confirms no PHI in rendered prompt |
| **Scenario 4** | On Gemini timeout: `asyncio.TimeoutError` caught; fallback YAML loaded; `HandoffChecklist` returned with `generated_type="TEMPLATE"` |

---

## Implementation Steps

### 1. Scaffold `checklist` sub-package

```
coordinator-agent/
└── app/
    └── checklist/
        ├── __init__.py
        └── checklist_service.py   ← THIS TASK
```

```bash
mkdir -p coordinator-agent/app/checklist
touch coordinator-agent/app/checklist/__init__.py
```

### 2. Create `coordinator-agent/app/checklist/__init__.py`

```python
"""Checklist sub-package — AI-generated handoff checklist orchestration.

Exports:
    ChecklistService — generates HandoffChecklist via Gemini or template fallback.
    ChecklistInput   — PHI-safe input model for checklist generation context.

Design refs:
    ADR-004  — LangChain + Vertex AI structured output
    AIR-021  — minimum-necessary PHI
    US-023   — Generate Context-Aware Handoff Checklist via LLM
"""
from app.checklist.checklist_service import ChecklistInput, ChecklistService

__all__ = ["ChecklistInput", "ChecklistService"]
```

### 3. Create `coordinator-agent/app/checklist/checklist_service.py`

```python
"""ChecklistService — orchestrates AI-generated handoff checklist via Vertex AI Gemini.

Responsibilities:
  1. Render ``prompts/checklist.jinja2`` with minimum-necessary clinical context.
  2. Call Vertex AI Gemini with ``response_schema`` for structured JSON output.
  3. Enforce 15-second timeout; fall back to ``config/checklist_templates.yaml`` on expiry.
  4. Return a validated ``HandoffChecklist`` with ``generated_type`` set appropriately.

PHI policy (AIR-021):
  ``ChecklistInput`` accepts only ICD-10 diagnosis codes, generic medication names,
  unit name, and transition type. Patient-identifying fields (name, MRN, DOB, phone)
  are explicitly excluded from both the input model and the rendered prompt.

Environment variables:
  GOOGLE_CLOUD_PROJECT      — GCP project ID for Vertex AI
  VERTEX_AI_LOCATION        — Vertex AI region (default: us-central1)
  GEMINI_MODEL_ID           — Gemini model identifier (default: gemini-1.5-pro)
  CHECKLIST_LLM_TIMEOUT_SEC — LLM call timeout in seconds (default: 15)

Design refs:
    ADR-004, TR-004, AIR-020, AIR-021, US-023 DoD, AC Scenarios 1–4
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from typing import Annotated

import jinja2
import yaml
from pydantic import BaseModel, Field

from app.models.handoff_checklist import ChecklistItem, HandoffChecklist

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SEC: int = 15
_DEFAULT_GEMINI_MODEL: str = "gemini-1.5-pro"
_DEFAULT_VERTEX_LOCATION: str = "us-central1"

_SERVICE_ROOT = pathlib.Path(__file__).parent.parent.parent  # coordinator-agent/
_PROMPTS_DIR = _SERVICE_ROOT / "prompts"
_TEMPLATES_PATH = _SERVICE_ROOT / "config" / "checklist_templates.yaml"

# ADT event_type → YAML key mapping
_TRANSITION_KEY_MAP: dict[str, str] = {
    "A01": "A01",
    "A02": "A02",
    "A03": "A03",
}

# ---------------------------------------------------------------------------
# ChecklistInput — PHI-safe input model
# ---------------------------------------------------------------------------


class ChecklistInput(BaseModel):
    """Minimum-necessary clinical context for checklist generation.

    PHI policy (AIR-021):
        This model intentionally omits patient-identifying fields.
        DO NOT add: patient_name, first_name, last_name, mrn, dob, phone, email.

    Attributes:
        encounter_id:      Encounter UUID — used only for logging/tracing, not injected into LLM prompt.
        diagnosis_codes:   ICD-10 codes (e.g. ``["E11.9", "I50.9"]``).
        unit_name:         Care unit name (e.g. ``"ICU"``).
        transition_type:   ADT code (e.g. ``"A03"``).
        medication_names:  Generic drug names only (e.g. ``["Metformin", "Furosemide"]``).
    """

    encounter_id: Annotated[
        str,
        Field(description="Encounter UUID for audit logging (not injected into LLM prompt)."),
    ]
    diagnosis_codes: Annotated[
        list[str],
        Field(min_length=1, description="ICD-10 diagnosis codes."),
    ]
    unit_name: Annotated[
        str,
        Field(min_length=2, max_length=100, description="Care unit name."),
    ]
    transition_type: Annotated[
        str,
        Field(min_length=3, max_length=10, description="ADT event code (A01/A02/A03)."),
    ]
    medication_names: list[str] = Field(
        default_factory=list,
        description="Generic medication names — no PHI.",
    )


# ---------------------------------------------------------------------------
# ChecklistService
# ---------------------------------------------------------------------------


class ChecklistService:
    """Generates a ``HandoffChecklist`` via Vertex AI Gemini or template fallback.

    Args:
        project_id:   GCP project ID. Defaults to ``GOOGLE_CLOUD_PROJECT`` env var.
        location:     Vertex AI region. Defaults to ``VERTEX_AI_LOCATION`` env var or ``us-central1``.
        model_id:     Gemini model ID. Defaults to ``GEMINI_MODEL_ID`` env var or ``gemini-1.5-pro``.
        timeout_sec:  LLM call timeout in seconds. Defaults to ``CHECKLIST_LLM_TIMEOUT_SEC`` env var or 15.

    Example::

        service = ChecklistService()
        checklist = await service.generate(
            ChecklistInput(
                encounter_id="ENC-001",
                diagnosis_codes=["E11.9", "I50.9"],
                unit_name="Med-Surg 4B",
                transition_type="A03",
                medication_names=["Metformin", "Furosemide"],
            )
        )
        assert checklist.generated_type in ("LLM", "TEMPLATE")
    """

    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        model_id: str | None = None,
        timeout_sec: int | None = None,
    ) -> None:
        self._project_id = project_id or os.environ["GOOGLE_CLOUD_PROJECT"]
        self._location = location or os.environ.get("VERTEX_AI_LOCATION", _DEFAULT_VERTEX_LOCATION)
        self._model_id = model_id or os.environ.get("GEMINI_MODEL_ID", _DEFAULT_GEMINI_MODEL)
        self._timeout_sec = int(
            timeout_sec or os.environ.get("CHECKLIST_LLM_TIMEOUT_SEC", _DEFAULT_TIMEOUT_SEC)
        )

        # Load Jinja2 template once at init — not on every call
        self._jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(_PROMPTS_DIR)),
            autoescape=False,  # Clinical text — no HTML escaping needed
            undefined=jinja2.StrictUndefined,  # Fail fast on missing variables
        )
        self._prompt_template = self._jinja_env.get_template("checklist.jinja2")

        # Load YAML fallback templates once at init
        self._fallback_templates: dict[str, list[dict]] = yaml.safe_load(
            _TEMPLATES_PATH.read_text()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self, context: ChecklistInput) -> HandoffChecklist:
        """Generate a handoff checklist for the given clinical context.

        Attempts a Vertex AI Gemini structured-output call. If the call does
        not complete within ``timeout_sec`` seconds, falls back to the
        pre-defined YAML template for the given ``transition_type``.

        Args:
            context: ``ChecklistInput`` with ICD-10 codes, unit, transition type.
                     Must NOT contain PHI fields (enforced by model definition).

        Returns:
            ``HandoffChecklist`` with ``generated_type="LLM"`` on success, or
            ``generated_type="TEMPLATE"`` on timeout/fallback.
        """
        try:
            checklist = await asyncio.wait_for(
                self._call_gemini(context),
                timeout=self._timeout_sec,
            )
            logger.info(
                "checklist_generated_llm",
                extra={
                    "encounter_id": context.encounter_id,
                    "transition_type": context.transition_type,
                    "item_count": len(checklist.checklist),
                },
            )
            return checklist

        except asyncio.TimeoutError:
            logger.warning(
                "checklist_llm_timeout_fallback",
                extra={
                    "encounter_id": context.encounter_id,
                    "transition_type": context.transition_type,
                    "timeout_sec": self._timeout_sec,
                },
            )
            return self._load_template_fallback(context)

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "checklist_llm_error_fallback",
                extra={
                    "encounter_id": context.encounter_id,
                    "transition_type": context.transition_type,
                    "error": str(exc),
                },
            )
            return self._load_template_fallback(context)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call_gemini(self, context: ChecklistInput) -> HandoffChecklist:
        """Render prompt and call Vertex AI Gemini with structured output schema.

        Args:
            context: Validated ``ChecklistInput`` — no PHI fields.

        Returns:
            ``HandoffChecklist`` parsed from Gemini structured JSON response.

        Raises:
            Exception: Any Vertex AI / network exception propagates to caller
                       for fallback handling in ``generate()``.
        """
        # Lazy import — avoids load penalty when service is not used
        import vertexai  # type: ignore[import]
        from vertexai.generative_models import GenerativeModel, GenerationConfig  # type: ignore[import]

        prompt_text = self._prompt_template.render(
            diagnosis_codes=context.diagnosis_codes,
            unit_name=context.unit_name,
            transition_type=context.transition_type,
            medication_names=context.medication_names,
        )

        # Initialise Vertex AI (idempotent — safe to call multiple times)
        vertexai.init(project=self._project_id, location=self._location)

        model = GenerativeModel(self._model_id)
        response_schema = HandoffChecklist.llm_response_schema()

        # Run synchronous Vertex AI call in thread pool to avoid blocking event loop
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: model.generate_content(
                prompt_text,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0.3,  # Low temperature for clinical reliability
                    max_output_tokens=2048,
                ),
            ),
        )

        raw_json: dict = json.loads(response.text)
        checklist_items = [ChecklistItem(**item) for item in raw_json.get("checklist", [])]

        return HandoffChecklist(
            checklist=checklist_items,
            generated_type="LLM",
            transition_type=context.transition_type,
        )

    def _load_template_fallback(self, context: ChecklistInput) -> HandoffChecklist:
        """Load pre-defined checklist items from YAML for the given transition type.

        Args:
            context: ``ChecklistInput`` — only ``transition_type`` is used for lookup.

        Returns:
            ``HandoffChecklist`` with ``generated_type="TEMPLATE"``.
        """
        yaml_key = _TRANSITION_KEY_MAP.get(context.transition_type, "DEFAULT")
        raw_items: list[dict] = self._fallback_templates.get(
            yaml_key, self._fallback_templates["DEFAULT"]
        )
        checklist_items = [ChecklistItem(**item) for item in raw_items]

        return HandoffChecklist(
            checklist=checklist_items,
            generated_type="TEMPLATE",
            transition_type=context.transition_type,
        )
```

---

## Validation

Run from `coordinator-agent/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/checklist/checklist_service.py').read_text())
print('Syntax check: PASSED')
"

# 2. Import check
python -c "
from app.checklist import ChecklistService, ChecklistInput
print('Import check: PASSED')
"

# 3. ChecklistInput rejects PHI fields
python -c "
from app.checklist import ChecklistInput
import inspect
fields = ChecklistInput.model_fields.keys()
phi = {'first_name','last_name','mrn','dob','phone','email','patient_name'}
violations = phi & set(fields)
assert not violations, f'PHI fields in ChecklistInput: {violations}'
print('PHI field audit on ChecklistInput: PASSED')
"

# 4. Template fallback returns TEMPLATE type (no Gemini required)
python -c "
import asyncio, os
os.environ.setdefault('GOOGLE_CLOUD_PROJECT', 'test-project')
from app.checklist import ChecklistService, ChecklistInput

svc = ChecklistService()
fallback = svc._load_template_fallback(
    ChecklistInput(
        encounter_id='ENC-001',
        diagnosis_codes=['E11.9'],
        unit_name='ICU',
        transition_type='A03',
        medication_names=['Metformin'],
    )
)
assert fallback.generated_type == 'TEMPLATE'
assert len(fallback.checklist) >= 3
print(f'Fallback returned TEMPLATE with {len(fallback.checklist)} items: PASSED')
"

# 5. Timeout triggers fallback (mock asyncio.wait_for)
python -c "
import asyncio, os, unittest.mock
os.environ.setdefault('GOOGLE_CLOUD_PROJECT', 'test-project')
from app.checklist import ChecklistService, ChecklistInput

svc = ChecklistService(timeout_sec=1)

async def slow_gemini(ctx):
    await asyncio.sleep(10)

async def run():
    with unittest.mock.patch.object(svc, '_call_gemini', slow_gemini):
        result = await svc.generate(
            ChecklistInput(
                encounter_id='ENC-002',
                diagnosis_codes=['I50.9'],
                unit_name='CCU',
                transition_type='A02',
            )
        )
    assert result.generated_type == 'TEMPLATE', f'Expected TEMPLATE, got {result.generated_type}'
    print(f'Timeout fallback to TEMPLATE: PASSED')

asyncio.run(run())
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `coordinator-agent/app/checklist/__init__.py` |
| CREATE | `coordinator-agent/app/checklist/checklist_service.py` |

---

## Definition of Done Checklist

- [ ] `ChecklistInput` model defines `encounter_id`, `diagnosis_codes`, `unit_name`, `transition_type`, `medication_names` — zero PHI fields
- [ ] `ChecklistService.__init__()` loads Jinja2 template and YAML fallback once at construction
- [ ] `generate()` calls `_call_gemini()` wrapped in `asyncio.wait_for(timeout=15)`
- [ ] On `asyncio.TimeoutError`: `_load_template_fallback()` called; `HandoffChecklist.generated_type = "TEMPLATE"`
- [ ] On LLM success: `HandoffChecklist.generated_type = "LLM"`
- [ ] `_call_gemini()` uses `response_schema=HandoffChecklist.llm_response_schema()` via `GenerationConfig`
- [ ] Vertex AI SDK call runs in `loop.run_in_executor()` — does not block the event loop
- [ ] Structured log fields: `encounter_id`, `transition_type`, `item_count` — no PHI
- [ ] All 5 validation scripts pass cleanly
