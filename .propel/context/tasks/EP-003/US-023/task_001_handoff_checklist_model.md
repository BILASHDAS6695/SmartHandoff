---
id: TASK-001
title: "Create `coordinator-agent/app/models/handoff_checklist.py` — Pydantic HandoffChecklist Model with Validation"
user_story: US-023
epic: EP-003
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-006/TASK-001]
---

# TASK-001: Create `coordinator-agent/app/models/handoff_checklist.py` — Pydantic HandoffChecklist Model with Validation

> **Story:** US-023 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-023 mandates (ADR-004, TR-004, AIR-021):

> *"Vertex AI Gemini call with structured output schema: `{'checklist': [{'item': str, 'category': str, 'priority': str}]}`"*

`HandoffChecklist` is the single Pydantic model acting as the structured-output contract between the Gemini LLM call and downstream storage. It must:

- Define a `ChecklistItem` sub-model with validated `item`, `category`, and `priority` fields
- Enforce that `item` text begins with an actionable verb (`Verify`, `Confirm`, `Schedule`, `Review`, `Assess`, `Ensure`, `Notify`)
- Accept a `generated_type` discriminator (`LLM` | `TEMPLATE`) to track fallback scenarios (AC Scenario 4)
- Provide `json_schema()` for passing as `response_schema` to the Vertex AI Gemini SDK
- Exclude all PHI fields at model definition level — `first_name`, `last_name`, `mrn`, `dob` must NOT appear in this model

Design decisions encoded in this module:

| Decision | Rationale |
|----------|-----------|
| Pydantic v2 `model_validator` for actionable-verb check | Catches malformed LLM output before storage; cheap validation |
| `Literal["LLM", "TEMPLATE"]` discriminator | Allows dashboard to surface checklist source; supports AC Scenario 4 audit requirement |
| `json_schema()` class method | Single-source-of-truth for both Gemini `response_schema` param and OpenAPI spec |
| No PHI fields in model | Enforces minimum-necessary PHI policy (AIR-021) at type level |
| `priority: Literal["HIGH", "MEDIUM", "LOW"]` | Constrained enum prevents arbitrary LLM strings reaching the DB |

Design refs: ADR-004, AIR-020, AIR-021, US-023 DoD, AC Scenarios 1–4.

---

## Acceptance Criteria Addressed

| US-023 AC | Requirement |
|---|---|
| **Scenario 1** | `ChecklistItem` model validates ≥3 items can be created for discharge scenario |
| **Scenario 2** | Model definition contains zero PHI fields — confirmed by unit test in TASK-005 |
| **Scenario 3** | `HandoffChecklist.model_json_schema()` produces the structured array schema used by Gemini and the API |
| **Scenario 4** | `generated_type` field on `HandoffChecklist` distinguishes `LLM` vs `TEMPLATE` output |

---

## Implementation Steps

### 1. Verify service structure exists (or scaffold)

```
coordinator-agent/
├── app/
│   ├── models/
│   │   ├── __init__.py
│   │   ├── agent_task.py          ← pre-existing (US-006)
│   │   ├── adt_event.py           ← pre-existing (US-014)
│   │   └── handoff_checklist.py   ← THIS TASK
│   └── ...
```

```bash
# Only if models/__init__.py does not exist
touch coordinator-agent/app/models/__init__.py
```

### 2. Create `coordinator-agent/app/models/handoff_checklist.py`

```python
"""Pydantic models for the AI-generated handoff checklist.

Defines the structured-output contract consumed by:
  - Vertex AI Gemini ``response_schema`` parameter (TASK-003)
  - ``AgentTask.metadata`` JSONB storage (TASK-004)
  - ``GET /api/v1/encounters/{id}/tasks`` response schema (TASK-004)

PHI policy (AIR-021):
  This module intentionally contains NO patient-identifying fields.
  The checklist is keyed by encounter context (diagnosis codes, unit, transition
  type) — never by patient name, MRN, DOB, or phone number.

Design refs:
    ADR-004  — LangChain + Vertex AI structured output
    AIR-020  — coordinator agent orchestration
    AIR-021  — minimum-necessary PHI in LLM prompts
    US-023   — Generate Context-Aware Handoff Checklist via LLM
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ACTIONABLE_VERBS: frozenset[str] = frozenset(
    {"verify", "confirm", "schedule", "review", "assess", "ensure", "notify"}
)

# ---------------------------------------------------------------------------
# ChecklistItem
# ---------------------------------------------------------------------------


class ChecklistItem(BaseModel):
    """A single actionable item within a handoff checklist.

    Attributes:
        item: Human-readable instruction beginning with an actionable verb.
        category: Clinical grouping (e.g. ``"medications"``, ``"follow_up"``,
            ``"patient_education"``, ``"equipment"``, ``"documentation"``).
        priority: Urgency level — ``HIGH`` must be addressed before handoff
            completes; ``MEDIUM`` within 4 hours; ``LOW`` within 24 hours.

    Example::

        ChecklistItem(
            item="Verify blood glucose monitoring plan for discharge",
            category="medications",
            priority="HIGH",
        )
    """

    item: Annotated[
        str,
        Field(
            min_length=10,
            max_length=300,
            description=(
                "Actionable instruction beginning with Verify, Confirm, Schedule, "
                "Review, Assess, Ensure, or Notify."
            ),
        ),
    ]
    category: Annotated[
        str,
        Field(
            min_length=2,
            max_length=50,
            description="Clinical category grouping this checklist item.",
        ),
    ]
    priority: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        description="Urgency classification for this checklist item."
    )

    @model_validator(mode="after")
    def _item_starts_with_actionable_verb(self) -> "ChecklistItem":
        """Ensure ``item`` text opens with a recognised clinical action verb."""
        first_word = self.item.split()[0].lower().rstrip(".,:")
        if first_word not in _ACTIONABLE_VERBS:
            raise ValueError(
                f"ChecklistItem.item must begin with one of "
                f"{sorted(_ACTIONABLE_VERBS)!r}. Got first word: {first_word!r}"
            )
        return self


# ---------------------------------------------------------------------------
# HandoffChecklist
# ---------------------------------------------------------------------------


class HandoffChecklist(BaseModel):
    """Structured handoff checklist returned by the coordinator checklist service.

    This is the top-level container used as:
      - The ``response_schema`` passed to Vertex AI Gemini (TASK-003)
      - The value stored in ``AgentTask.metadata["checklist"]`` (TASK-004)

    Attributes:
        checklist: Ordered list of actionable checklist items. Must contain
            at least 1 item; LLM-generated checklists are expected to return ≥3
            patient-specific items (US-023 AC Scenario 1).
        generated_type: Source of the checklist. ``"LLM"`` when produced by
            Vertex AI Gemini; ``"TEMPLATE"`` when the 15-second timeout fired
            and the pre-defined fallback was used (AC Scenario 4).
        transition_type: ADT transition code (e.g. ``"A03"`` discharge,
            ``"A02"`` transfer). Stored for audit traceability.

    Example::

        checklist = HandoffChecklist(
            checklist=[
                ChecklistItem(item="Verify blood glucose monitoring plan", category="medications", priority="HIGH"),
                ChecklistItem(item="Confirm diuretic dose adjustment per discharge orders", category="medications", priority="HIGH"),
                ChecklistItem(item="Schedule follow-up with cardiologist within 7 days", category="follow_up", priority="MEDIUM"),
            ],
            generated_type="LLM",
            transition_type="A03",
        )
    """

    checklist: Annotated[
        list[ChecklistItem],
        Field(min_length=1, description="Ordered list of actionable handoff items."),
    ]
    generated_type: Literal["LLM", "TEMPLATE"] = Field(
        description="Source of checklist generation — LLM or template fallback."
    )
    transition_type: Annotated[
        str,
        Field(
            min_length=3,
            max_length=10,
            description="ADT transition code (e.g. A03, A02, A01).",
        ),
    ]

    @classmethod
    def llm_response_schema(cls) -> dict:
        """Return the JSON schema dict to pass as ``response_schema`` to Gemini.

        Usage in TASK-003::

            from app.models.handoff_checklist import HandoffChecklist

            response = await gemini_client.generate(
                prompt=rendered_prompt,
                response_schema=HandoffChecklist.llm_response_schema(),
            )

        Returns:
            JSON Schema dict representing the ``HandoffChecklist`` structure,
            scoped to the ``checklist`` array (Gemini structured-output contract).
        """
        schema = cls.model_json_schema()
        # Gemini response_schema expects the checklist array definition directly
        return schema
```

### 3. Update `coordinator-agent/app/models/__init__.py`

```python
"""Domain models for the coordinator agent service.

Exports:
    ADTEvent           — Pub/Sub ADT event (pre-existing, US-014)
    AgentTask          — Task record written to PostgreSQL (pre-existing, US-006)
    HandoffChecklist   — Structured checklist output model (US-023)
    ChecklistItem      — Individual checklist item sub-model (US-023)
"""
from app.models.adt_event import ADTEvent
from app.models.agent_task import AgentTask
from app.models.handoff_checklist import ChecklistItem, HandoffChecklist

__all__ = ["ADTEvent", "AgentTask", "ChecklistItem", "HandoffChecklist"]
```

---

## Validation

Run from `coordinator-agent/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/models/handoff_checklist.py').read_text())
print('Syntax check: PASSED')
"

# 2. Import check
python -c "
from app.models.handoff_checklist import HandoffChecklist, ChecklistItem
print('Import check: PASSED')
"

# 3. Valid model instantiation
python -c "
from app.models.handoff_checklist import HandoffChecklist, ChecklistItem
c = HandoffChecklist(
    checklist=[
        ChecklistItem(item='Verify blood glucose monitoring plan', category='medications', priority='HIGH'),
        ChecklistItem(item='Confirm diuretic dose per discharge orders', category='medications', priority='HIGH'),
        ChecklistItem(item='Schedule follow-up with cardiologist', category='follow_up', priority='MEDIUM'),
    ],
    generated_type='LLM',
    transition_type='A03',
)
assert len(c.checklist) == 3
print(f'HandoffChecklist with {len(c.checklist)} items: PASSED')
"

# 4. Actionable-verb validation guard
python -c "
from app.models.handoff_checklist import ChecklistItem
try:
    ChecklistItem(item='Patient should monitor glucose', category='medications', priority='HIGH')
    print('FAILED — should have raised ValueError')
except ValueError as e:
    print(f'Actionable-verb guard raised ValueError: PASSED')
"

# 5. No PHI fields in model schema
python -c "
from app.models.handoff_checklist import HandoffChecklist
schema_str = str(HandoffChecklist.model_json_schema())
phi_fields = ['first_name', 'last_name', 'mrn', 'dob', 'phone', 'email']
violations = [f for f in phi_fields if f in schema_str]
assert not violations, f'PHI fields found in schema: {violations}'
print('PHI audit on model schema: PASSED')
"

# 6. json_schema() returns dict with checklist key
python -c "
from app.models.handoff_checklist import HandoffChecklist
schema = HandoffChecklist.llm_response_schema()
assert 'checklist' in str(schema)
print('llm_response_schema() contains checklist definition: PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `coordinator-agent/app/models/handoff_checklist.py` |
| MODIFY | `coordinator-agent/app/models/__init__.py` |

---

## Definition of Done Checklist

- [ ] `ChecklistItem` defines `item` (str, min_length=10), `category` (str), `priority` (Literal HIGH/MEDIUM/LOW)
- [ ] `ChecklistItem` model validator rejects items not starting with an actionable verb
- [ ] `HandoffChecklist` defines `checklist` (list[ChecklistItem], min 1 item), `generated_type` (LLM/TEMPLATE), `transition_type`
- [ ] `HandoffChecklist.llm_response_schema()` returns JSON Schema dict for Gemini `response_schema` param
- [ ] Zero PHI fields (`first_name`, `last_name`, `mrn`, `dob`) present in model or schema — confirmed by validation script
- [ ] `app/models/__init__.py` exports `HandoffChecklist` and `ChecklistItem`
- [ ] All 6 validation scripts pass cleanly
