---
id: TASK-006
title: "Code Review and Definition of Done Sign-off for US-023"
user_story: US-023
epic: EP-003
sprint: 2
layer: Quality Assurance
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-023/TASK-001, US-023/TASK-002, US-023/TASK-003, US-023/TASK-004, US-023/TASK-005]
---

# TASK-006: Code Review and Definition of Done Sign-off for US-023

> **Story:** US-023 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Quality Assurance | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-023 DoD mandates:

> *"Code reviewed and approved"*

This task formalises the review gate for all artefacts delivered in TASK-001 through TASK-005 before the story can be marked `Done`. The reviewer validates functional correctness, PHI compliance, security posture, and architectural alignment.

---

## Acceptance Criteria Addressed

| US-023 AC | Requirement |
|---|---|
| **All Scenarios** | All AC scenarios verified via test results and manual walkthrough |
| **DoD** | All DoD checklist items confirmed complete |

---

## Review Checklist

### Functional Correctness

- [ ] `HandoffChecklist` + `ChecklistItem` models instantiate cleanly for LLM and TEMPLATE paths
- [ ] `ChecklistService.generate()` returns ≥3 items for discharge scenario (E11.9, I50.9)
- [ ] 15-second timeout enforced — fallback returns `generated_type="TEMPLATE"` (validated by `test_checklist_service.py`)
- [ ] Checklist stored in `agent_task.metadata["checklist"]` as JSONB array
- [ ] `GET /api/v1/encounters/{id}/tasks` response includes `checklist` and `checklist_generated_type` fields

### PHI Compliance (AIR-021 Mandatory Gate)

- [ ] `ChecklistInput` model has zero PHI fields (`first_name`, `last_name`, `mrn`, `dob`, `phone`, `email`)
- [ ] Rendered `checklist.jinja2` prompt does not contain PHI field names or `encounter_id` value
- [ ] `test_checklist_phi_audit.py` passes — both tests green
- [ ] Structured log fields in `ChecklistService` contain only `encounter_id` (UUID), `transition_type`, `item_count` — no patient data

### Security Posture (OWASP / HIPAA)

- [ ] No patient PHI injected into Vertex AI LLM prompt (ICD-10 codes only)
- [ ] Vertex AI API key / credentials sourced from GCP Secret Manager (not hardcoded)
- [ ] `CHECKLIST_LLM_TIMEOUT_SEC` configurable via environment variable — no magic constant in business logic
- [ ] YAML template file does not contain patient-specific data — only generic clinical instructions

### Architectural Alignment

- [ ] `ChecklistService` follows single-responsibility principle — no DB access, no Pub/Sub logic
- [ ] Jinja2 template loaded once at `__init__` (not per request) — TR-004 performance requirement
- [ ] YAML fallback loaded once at `__init__` (not per request) — eliminates fallback-path I/O
- [ ] `response_schema` passed to Gemini via `GenerationConfig` — structured output, not regex parsing (ADR-004)
- [ ] Vertex AI SDK call wrapped in `loop.run_in_executor()` — event loop not blocked

### Code Quality

- [ ] All new files have module-level docstrings explaining purpose and design refs
- [ ] No commented-out code blocks
- [ ] No `print()` statements — only `logger.*` calls with structured fields
- [ ] `requirements.txt` updated with new dependencies: `jinja2`, `pyyaml`, `google-cloud-aiplatform` (if not already present)
- [ ] `pytest tests/unit/ -v` — 0 failures, ≥25 tests passing

### Definition of Done Final Checklist

- [ ] TASK-001: `HandoffChecklist` model created and validated
- [ ] TASK-002: `prompts/checklist.jinja2` and `config/checklist_templates.yaml` created and validated
- [ ] TASK-003: `ChecklistService` implemented with Gemini call, timeout, fallback
- [ ] TASK-004: `AgentTask.metadata` JSONB stores checklist; API endpoint returns `checklist` field
- [ ] TASK-005: All unit tests pass — PHI audit, model validation, service behaviour, fallback coverage
- [ ] TASK-006: Code review completed and approved by a second engineer

---

## Dependency Graph

```
TASK-001 (HandoffChecklist model)
    └── TASK-002 (Jinja2 template + YAML config)
        └── TASK-003 (ChecklistService)
            ├── TASK-004 (Wire into AgentTask + API)
            └── TASK-005 (Unit tests — depends on TASK-001, 002, 003)
                └── TASK-006 (Code review sign-off)
```

---

## Files Reviewed

| Task | Files |
|------|-------|
| TASK-001 | `coordinator-agent/app/models/handoff_checklist.py`, `coordinator-agent/app/models/__init__.py` |
| TASK-002 | `coordinator-agent/prompts/checklist.jinja2`, `coordinator-agent/config/checklist_templates.yaml` |
| TASK-003 | `coordinator-agent/app/checklist/checklist_service.py`, `coordinator-agent/app/checklist/__init__.py` |
| TASK-004 | `coordinator-agent/app/coordinator/agent.py`, `backend/app/schemas/agent_task.py` |
| TASK-005 | `coordinator-agent/tests/unit/test_handoff_checklist_model.py`, `coordinator-agent/tests/unit/test_checklist_phi_audit.py`, `coordinator-agent/tests/unit/test_checklist_service.py` |

---

## Definition of Done Checklist

- [ ] All functional review items checked and approved
- [ ] PHI compliance gate passed — no PHI in prompt, no PHI in model, audit tests green
- [ ] Security posture review passed — no hardcoded secrets, no PHI in LLM call
- [ ] Code quality review passed — no print statements, structured logging, docstrings present
- [ ] `pytest tests/unit/ -v` run by reviewer — 0 failures confirmed
- [ ] Story US-023 status updated to `Done` after all items above are checked
