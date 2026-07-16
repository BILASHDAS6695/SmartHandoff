---
id: TASK-002
title: "Create `prompts/checklist.jinja2` + `config/checklist_templates.yaml` — Prompt Template and Template Fallback Config"
user_story: US-023
epic: EP-003
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-023/TASK-001]
---

# TASK-002: Create `prompts/checklist.jinja2` + `config/checklist_templates.yaml` — Prompt Template and Template Fallback Config

> **Story:** US-023 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-023 mandates (AIR-021, Technical Notes):

> *"Jinja2 prompt template for checklist generation: `prompts/checklist.jinja2` with placeholders for diagnosis codes, unit, transition type"*
> *"Template fallback items stored in `config/checklist_templates.yaml` keyed by transition type"*
> *"Prompt minimum-necessary PHI: use ICD-10 diagnosis codes instead of diagnosis text where possible"*

This task creates two artefacts:

1. **`prompts/checklist.jinja2`** — the LLM prompt template rendered by `ChecklistService` (TASK-003). It accepts only minimum-necessary clinical context (ICD-10 codes, unit, transition type) and explicitly excludes PHI.
2. **`config/checklist_templates.yaml`** — static fallback checklists keyed by ADT transition type, used when the Gemini call exceeds 15 seconds (AC Scenario 4).

Design decisions encoded in these artefacts:

| Decision | Rationale |
|----------|-----------|
| ICD-10 codes, not diagnosis text, in prompt | AIR-021 minimum-necessary PHI — codes are de-identified clinical identifiers |
| Explicit PHI exclusion instruction in system prompt | Defense-in-depth: LLM instructed not to request or generate patient names/MRN |
| YAML fallback keyed by `event_type` (A01/A02/A03) | Transition-specific fallbacks are clinically meaningful; generic fallback exists for unknown codes |
| Jinja2 `{{ variable }}` syntax | Consistent with LangChain `PromptTemplate`; testable in isolation with `jinja2.Environment` |
| Fallback items include `category` and `priority` | Ensures `HandoffChecklist` model validation passes for both LLM and TEMPLATE paths |

Design refs: AIR-020, AIR-021, US-023 DoD, AC Scenarios 2 and 4.

---

## Acceptance Criteria Addressed

| US-023 AC | Requirement |
|---|---|
| **Scenario 1** | Prompt template correctly injects diagnosis codes, unit, and transition type to guide LLM to patient-specific output |
| **Scenario 2** | Prompt template contains zero PHI placeholder variables (`first_name`, `last_name`, `mrn`, `dob`, `phone`) — confirmed by static analysis in TASK-005 |
| **Scenario 4** | YAML template fallback provides ≥3 items for each of A01, A02, A03 transition types; all items pass `ChecklistItem` validation |

---

## Implementation Steps

### 1. Scaffold directory structure

```
coordinator-agent/
├── config/
│   └── checklist_templates.yaml   ← THIS TASK
├── prompts/
│   └── checklist.jinja2           ← THIS TASK
└── app/
    └── ...
```

```bash
mkdir -p coordinator-agent/prompts
mkdir -p coordinator-agent/config
```

### 2. Create `coordinator-agent/prompts/checklist.jinja2`

```jinja2
{#
  checklist.jinja2 — Handoff Checklist Generation Prompt
  =========================================================
  Renders the system + user prompt for Vertex AI Gemini to generate a
  patient-specific handoff checklist.

  TEMPLATE VARIABLES (all required):
    diagnosis_codes   : list[str]  — ICD-10 codes (e.g. ["E11.9", "I50.9"])
    unit_name         : str        — Care unit name (e.g. "ICU", "Med-Surg 4B")
    transition_type   : str        — ADT code label (e.g. "DISCHARGE", "TRANSFER", "ADMISSION")
    medication_names  : list[str]  — Generic drug names only (e.g. ["Metformin", "Furosemide"])

  PHI POLICY (AIR-021):
    This template intentionally omits patient-identifying fields.
    DO NOT add: patient_name, mrn, dob, phone, email, address, ssn.
    ICD-10 codes and generic drug names are the maximum clinical context permitted.

  Design refs:
    AIR-021  — minimum-necessary PHI in LLM prompts
    ADR-004  — LangChain + Vertex AI Gemini structured output
    US-023   — Generate Context-Aware Handoff Checklist via LLM
#}
You are a clinical care coordinator assistant. Your role is to generate a concise, actionable handoff checklist for nursing staff.

IMPORTANT SAFETY RULES:
- Do NOT include any patient-identifying information in your response (no names, dates of birth, MRN, phone numbers).
- Every checklist item MUST begin with one of these action verbs: Verify, Confirm, Schedule, Review, Assess, Ensure, Notify.
- Generate items that are specific to the provided clinical context.

CLINICAL CONTEXT:
- Transition Type: {{ transition_type }}
- Care Unit: {{ unit_name }}
- Diagnosis Codes (ICD-10): {{ diagnosis_codes | join(", ") }}
{% if medication_names %}
- Active Medications: {{ medication_names | join(", ") }}
{% endif %}

TASK:
Generate a handoff checklist tailored to the above clinical context. The checklist must:
1. Contain at least 3 items directly relevant to the diagnosis codes provided.
2. Cover medications, follow-up care, patient education, and equipment/documentation as applicable.
3. Classify each item with a category (e.g. medications, follow_up, patient_education, equipment, documentation, safety).
4. Assign a priority: HIGH (must complete before handoff), MEDIUM (within 4 hours), LOW (within 24 hours).

Respond ONLY with the structured JSON matching the schema provided. Do not include explanations or markdown formatting.
```

### 3. Create `coordinator-agent/config/checklist_templates.yaml`

```yaml
# checklist_templates.yaml
# =========================
# Static fallback handoff checklists keyed by ADT transition type.
# Used when the Vertex AI Gemini call exceeds the 15-second timeout (US-023 AC Scenario 4).
#
# Each entry maps to an ADT event_type code:
#   A01  — Admission
#   A02  — Transfer
#   A03  — Discharge
#   DEFAULT — Unknown or unmapped transition type
#
# All items must satisfy ChecklistItem validation:
#   - item starts with an actionable verb (Verify, Confirm, Schedule, Review, Assess, Ensure, Notify)
#   - priority is one of: HIGH, MEDIUM, LOW
#   - category is a non-empty string
#
# Design refs: US-023 DoD, AC Scenario 4, AIR-021

A01:
  - item: "Verify patient identification and allergy documentation is complete"
    category: "documentation"
    priority: "HIGH"
  - item: "Confirm admission orders are signed and entered in EHR"
    category: "documentation"
    priority: "HIGH"
  - item: "Assess patient orientation and neurological baseline on arrival"
    category: "safety"
    priority: "HIGH"
  - item: "Review current medication list and reconcile with admission orders"
    category: "medications"
    priority: "HIGH"
  - item: "Ensure fall risk assessment and bed alarm are activated"
    category: "safety"
    priority: "MEDIUM"
  - item: "Notify care team of any pending lab or imaging results from ED"
    category: "documentation"
    priority: "MEDIUM"
  - item: "Confirm IV access patency and document insertion site date"
    category: "equipment"
    priority: "MEDIUM"
  - item: "Schedule dietitian consult if nutritional risk identified"
    category: "follow_up"
    priority: "LOW"

A02:
  - item: "Verify receiving unit has been notified and bed is ready"
    category: "documentation"
    priority: "HIGH"
  - item: "Confirm all active orders have been transferred to receiving unit"
    category: "documentation"
    priority: "HIGH"
  - item: "Review current vital signs and document pre-transfer baseline"
    category: "safety"
    priority: "HIGH"
  - item: "Ensure all IV lines, drains, and tubes are secured for transport"
    category: "equipment"
    priority: "HIGH"
  - item: "Confirm monitoring equipment is available during transport"
    category: "equipment"
    priority: "HIGH"
  - item: "Notify receiving nurse of isolation precautions, if applicable"
    category: "safety"
    priority: "MEDIUM"
  - item: "Verify medication administration record is current and reconciled"
    category: "medications"
    priority: "MEDIUM"
  - item: "Assess patient's understanding of the reason for transfer"
    category: "patient_education"
    priority: "LOW"

A03:
  - item: "Verify discharge prescriptions are printed and reviewed with patient"
    category: "medications"
    priority: "HIGH"
  - item: "Confirm follow-up appointment is scheduled with primary care provider"
    category: "follow_up"
    priority: "HIGH"
  - item: "Review discharge instructions with patient and confirm comprehension"
    category: "patient_education"
    priority: "HIGH"
  - item: "Ensure patient has transportation arranged for safe discharge"
    category: "safety"
    priority: "HIGH"
  - item: "Confirm any home health or DME orders have been placed and confirmed"
    category: "follow_up"
    priority: "MEDIUM"
  - item: "Notify pharmacy of any controlled substance prescriptions requiring processing"
    category: "medications"
    priority: "MEDIUM"
  - item: "Verify patient education materials are provided in preferred language"
    category: "patient_education"
    priority: "MEDIUM"
  - item: "Schedule specialist follow-up if indicated by discharge diagnosis"
    category: "follow_up"
    priority: "LOW"

DEFAULT:
  - item: "Verify current medication list is accurate and reconciled"
    category: "medications"
    priority: "HIGH"
  - item: "Confirm care plan goals and pending tasks are communicated to receiving team"
    category: "documentation"
    priority: "HIGH"
  - item: "Assess patient safety risks and document in handoff note"
    category: "safety"
    priority: "HIGH"
  - item: "Review all active orders for completeness and accuracy"
    category: "documentation"
    priority: "MEDIUM"
  - item: "Notify relevant specialists of patient status change"
    category: "follow_up"
    priority: "LOW"
```

---

## Validation

Run from `coordinator-agent/`:

```bash
# 1. Jinja2 template renders without errors
python -c "
import jinja2, pathlib
env = jinja2.Environment(loader=jinja2.FileSystemLoader('prompts'))
tmpl = env.get_template('checklist.jinja2')
rendered = tmpl.render(
    diagnosis_codes=['E11.9', 'I50.9'],
    unit_name='Med-Surg 4B',
    transition_type='DISCHARGE',
    medication_names=['Metformin', 'Furosemide'],
)
print('Jinja2 render: PASSED')
print(f'Rendered length: {len(rendered)} chars')
"

# 2. PHI fields absent from rendered prompt
python -c "
import jinja2, pathlib
env = jinja2.Environment(loader=jinja2.FileSystemLoader('prompts'))
tmpl = env.get_template('checklist.jinja2')
rendered = tmpl.render(
    diagnosis_codes=['E11.9', 'I50.9'],
    unit_name='ICU',
    transition_type='TRANSFER',
    medication_names=['Heparin'],
)
phi_terms = ['first_name', 'last_name', 'mrn', 'dob', 'date_of_birth', 'phone', 'email']
violations = [t for t in phi_terms if t in rendered.lower()]
assert not violations, f'PHI terms found in rendered prompt: {violations}'
print('PHI audit on rendered prompt: PASSED')
"

# 3. YAML fallback loads and validates all items
python -c "
import yaml
from app.models.handoff_checklist import ChecklistItem

with open('config/checklist_templates.yaml') as f:
    templates = yaml.safe_load(f)

for transition, items in templates.items():
    for item_data in items:
        ci = ChecklistItem(**item_data)
    print(f'Transition {transition}: {len(items)} items — PASSED')
"

# 4. All transition types present
python -c "
import yaml
with open('config/checklist_templates.yaml') as f:
    templates = yaml.safe_load(f)
required_keys = {'A01', 'A02', 'A03', 'DEFAULT'}
missing = required_keys - set(templates.keys())
assert not missing, f'Missing transition keys: {missing}'
print(f'All required transition keys present {sorted(templates.keys())}: PASSED')
"

# 5. Each transition type has ≥3 items
python -c "
import yaml
with open('config/checklist_templates.yaml') as f:
    templates = yaml.safe_load(f)
for key, items in templates.items():
    assert len(items) >= 3, f'{key} has only {len(items)} items, need ≥3'
    print(f'{key}: {len(items)} items ≥ 3 — PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `coordinator-agent/prompts/checklist.jinja2` |
| CREATE | `coordinator-agent/config/checklist_templates.yaml` |

---

## Definition of Done Checklist

- [ ] `prompts/checklist.jinja2` renders without error given `diagnosis_codes`, `unit_name`, `transition_type`, `medication_names`
- [ ] Rendered prompt contains zero PHI placeholder variables — confirmed by validation script #2
- [ ] `config/checklist_templates.yaml` contains entries for A01, A02, A03, and DEFAULT transition types
- [ ] Each transition type contains ≥3 checklist items
- [ ] All YAML items pass `ChecklistItem` Pydantic validation (actionable verb, valid priority)
- [ ] All 5 validation scripts pass cleanly
