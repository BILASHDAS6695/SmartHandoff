---
id: TASK-026-004
title: "Integrate `CompletenessValidator` into `DocumentationAgent.process()` as Post-Generation Step"
user_story: US-026
epic: EP-004
sprint: 2
layer: Backend — AI Agent
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-025, TASK-026-001, TASK-026-002, TASK-026-003]
---

# TASK-026-004: Integrate `CompletenessValidator` into `DocumentationAgent.process()` as Post-Generation Step

> **Story:** US-026 | **Epic:** EP-004 | **Sprint:** 2 | **Layer:** Backend — AI Agent | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

The `DocumentationAgent` (US-025) generates discharge summaries via Vertex AI Gemini and persists them via `DocumentRepository.create_discharge_document()`. This task wires the completeness validation step immediately after the DB write, within the same `process()` execution.

The sequence is:
1. **Generate** — Gemini/template produces `DischargeSummarySchema` (US-025)
2. **Persist** — `DocumentRepository.create_discharge_document()` writes `Document` row with `status=PENDING_REVIEW` (US-025)
3. **Validate** ← **this task** — `CompletenessValidator.validate()` inspects the schema dict
4. **Update** ← **this task** — `DocumentRepository.update_completeness()` writes `completeness_status` and `missing_fields`; reverts `status` to `DRAFT` if INCOMPLETE

The validator is instantiated once at agent startup (not per message) to avoid re-reading the YAML on every event.

---

## Acceptance Criteria Addressed

| US-026 AC | Requirement |
|---|---|
| **Scenario 1** | Complete doc → `completeness_status=COMPLETE`, `status=PENDING_REVIEW`, appears in review queue |
| **Scenario 2** | Missing field → `completeness_status=INCOMPLETE`, `status=DRAFT`, NOT in review queue |
| **Scenario 3** | Validator reads from config — no code change required for new required fields |

---

## Implementation Steps

### 1. Update `backend/agents/documentation/agent.py`

Wire the validator into `DocumentationAgent.__init__()` and `process()`:

```python
# backend/agents/documentation/agent.py

# --- Add to imports ---
from agents.documentation.completeness_validator import CompletenessValidator

# --- Update __init__() ---
def __init__(
    self,
    fhir_client: FHIRClient,
    document_repository: DocumentRepository,
    project_id: str,
    location: str = "us-central1",
) -> None:
    super().__init__(subscription_id=self.SUBSCRIPTION_ID)

    self._fetcher = FHIREncounterFetcher(fhir_client)
    self._renderer = PromptRenderer()
    self._doc_repo = document_repository

    # Instantiated once — reads YAML config at startup, cached for agent lifetime
    self._completeness_validator = CompletenessValidator()

    # ... existing LLM setup unchanged ...
```

```python
# --- Update process() method ---
async def process(self, event: ADTEvent) -> None:
    """
    Process an ADT event: generate discharge summary, persist, and validate completeness.

    Sequence:
      1. Fetch FHIR encounter context
      2. Render prompt and call Gemini (or template fallback)
      3. Persist Document with status=PENDING_REVIEW
      4. Run completeness validation
      5. Update Document with completeness_status and revert to DRAFT if INCOMPLETE

    Args:
        event: Parsed ADT event from Pub/Sub (A03 or A02).
    """
    if event.event_type not in _SUPPORTED_EVENT_TYPES:
        logger.debug("DocumentationAgent: skipping unsupported event_type=%s", event.event_type)
        return

    encounter_id: str = event.encounter_id
    logger.info("DocumentationAgent.process: start encounter_id=%s", encounter_id)

    # Step 1 & 2: FHIR fetch + generate (US-025 — unchanged)
    context = await self._fetcher.fetch(encounter_id)
    prompt = self._renderer.render(context)
    summary: DischargeSummarySchema = await self._generate_summary(prompt, encounter_id)

    # Step 3: Persist document (status=PENDING_REVIEW at this point)
    document = await self._doc_repo.create_discharge_document(
        encounter_id=encounter_id,
        summary=summary,
    )

    # Step 4: Run completeness validation (US-026)
    result = self._completeness_validator.validate(summary.model_dump())

    # Step 5: Persist validation result; status reverted to DRAFT if INCOMPLETE
    document = await self._doc_repo.update_completeness(document=document, result=result)

    logger.info(
        "DocumentationAgent.process: complete encounter_id=%s "
        "completeness_status=%s missing_fields=%s document_status=%s",
        encounter_id,
        document.completeness_status,
        document.missing_fields,
        document.status,
    )
```

> **Important:** The completeness validation step must always run — even if the summary was template-generated (fallback path from US-025 TASK-005). The validator is document-type-agnostic and works on any `dict`.

### 2. Verify `_generate_summary()` returns `DischargeSummarySchema`

Ensure the AI path and template fallback path both return a `DischargeSummarySchema` instance (established in US-025). The `model_dump()` call in step 4 requires a Pydantic model — do not pass raw dicts.

---

## File Targets

| Action | Path |
|--------|------|
| **Update** | `backend/agents/documentation/agent.py` |

---

## Definition of Done

- [ ] `CompletenessValidator` instantiated once in `DocumentationAgent.__init__()` (not per-event)
- [ ] `validate()` called with `summary.model_dump()` in `process()` after the DB write
- [ ] `update_completeness()` called immediately after `validate()`
- [ ] Structured log line emitted at INFO level with `completeness_status`, `missing_fields`, `document_status`
- [ ] Both AI-generation and template-fallback paths flow through the validator
- [ ] No `try/except` that silently swallows validator errors — validator failures propagate to BaseAgent retry

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-025 | Story | `DocumentationAgent` and `DocumentRepository.create_discharge_document()` must exist |
| TASK-026-002 | Task | `CompletenessValidator` class |
| TASK-026-003 | Task | `DocumentRepository.update_completeness()` method and `Document` schema columns |
