---
id: TASK-004
title: "Wire Checklist into `AgentTask.metadata` JSONB and Expose via `GET /api/v1/encounters/{id}/tasks`"
user_story: US-023
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-023/TASK-001, US-023/TASK-003, US-006/TASK-001]
---

# TASK-004: Wire Checklist into `AgentTask.metadata` JSONB and Expose via `GET /api/v1/encounters/{id}/tasks`

> **Story:** US-023 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-023 mandates (AC Scenario 3, DoD):

> *"`checklist` field stored as JSONB in `agent_task.metadata` column"*
> *"coordinator `AgentTask` response includes a `checklist` field with the generated items as a structured JSON array"*

This task wires `ChecklistService` into the coordinator agent workflow and ensures the generated `HandoffChecklist` is persisted in `agent_task.metadata["checklist"]` and returned by the existing `GET /api/v1/encounters/{id}/tasks` API endpoint.

Two integration points:

1. **Coordinator Agent (`app/coordinator/agent.py`)** — call `ChecklistService.generate()` after receiving the ADT event; write result into `AgentTask.metadata`
2. **API response schema** — ensure `AgentTask` response serialiser includes the `checklist` field from `metadata` JSONB

Design decisions:

| Decision | Rationale |
|----------|-----------|
| Store checklist in `agent_task.metadata` JSONB (not a separate table) | DR-001: JSONB avoids schema migration for evolving checklist structure; queryable with PostgreSQL JSONB operators |
| `metadata["checklist"]` keyed dict | Consistent with existing `metadata` usage in `AgentTask`; allows other metadata fields to coexist |
| `metadata["generated_type"]` stored alongside | Enables dashboard to surface fallback indicator; no separate column needed |
| API returns checklist from `metadata` | Avoids separate read path; single source of truth |
| No Alembic migration needed | `metadata` column is pre-existing JSONB (US-006); adding sub-keys requires no DDL change |

Design refs: ADR-003, ADR-006, DR-001, US-023 DoD, AC Scenario 3.

---

## Acceptance Criteria Addressed

| US-023 AC | Requirement |
|---|---|
| **Scenario 3** | `GET /api/v1/encounters/ENC-001/tasks` returns coordinator `AgentTask` with `checklist` field as structured JSON array |

---

## Implementation Steps

### 1. Update `coordinator-agent/app/coordinator/agent.py` — integrate ChecklistService

Locate the existing `CoordinatorAgent.process_event()` method (implemented in US-020/TASK-002). Add a checklist generation step after the ADT event is received and the `AgentTask` record is created.

```python
# coordinator-agent/app/coordinator/agent.py
# ------------------------------------------------------------------
# ADD these imports at the top of the file (after existing imports)
# ------------------------------------------------------------------
from app.checklist import ChecklistInput, ChecklistService
from app.models.handoff_checklist import HandoffChecklist

# ------------------------------------------------------------------
# ADD ChecklistService initialisation to CoordinatorAgent.__init__()
# ------------------------------------------------------------------
class CoordinatorAgent:
    def __init__(self, ...):
        # ... existing init code ...
        self._checklist_service = ChecklistService()  # ADD THIS LINE

    # ------------------------------------------------------------------
    # MODIFY process_event() to call checklist generation
    # ------------------------------------------------------------------
    async def process_event(self, event: ADTEvent) -> None:
        # ... existing task creation logic ...

        # Generate checklist after creating the AgentTask record
        checklist_input = ChecklistInput(
            encounter_id=str(event.encounter_id),
            diagnosis_codes=event.diagnosis_codes or [],          # ICD-10 list from ADTEvent
            unit_name=event.unit_name or "Unknown Unit",
            transition_type=event.event_type,                     # e.g. "A03"
            medication_names=event.medication_names or [],        # Generic names only
        )
        checklist: HandoffChecklist = await self._checklist_service.generate(checklist_input)

        # Persist checklist in AgentTask.metadata JSONB
        await self._persist_checklist(agent_task, checklist)

    async def _persist_checklist(
        self,
        agent_task: AgentTask,
        checklist: HandoffChecklist,
    ) -> None:
        """Write generated checklist into agent_task.metadata JSONB.

        Merges checklist data into the existing metadata dict so that
        other metadata fields written by the coordinator are preserved.

        Args:
            agent_task: The ``AgentTask`` ORM instance to update.
            checklist:  Validated ``HandoffChecklist`` from ChecklistService.
        """
        checklist_payload = {
            "checklist": [item.model_dump() for item in checklist.checklist],
            "generated_type": checklist.generated_type,
            "transition_type": checklist.transition_type,
        }

        async with self._db_session() as session:
            # Fetch latest state and merge — avoids clobbering concurrent metadata writes
            await session.execute(
                update(AgentTask)
                .where(AgentTask.id == agent_task.id)
                .values(
                    metadata=AgentTask.metadata.op("||")(
                        json.dumps(checklist_payload)
                    )
                )
            )
            await session.commit()

        logger.info(
            "checklist_persisted",
            extra={
                "agent_task_id": str(agent_task.id),
                "generated_type": checklist.generated_type,
                "item_count": len(checklist.checklist),
            },
        )
```

> **Note:** The exact method signature and session management pattern should follow the existing `CoordinatorAgent` implementation from US-020/TASK-002. Use the same `_db_session()` context manager or `AsyncSession` injection pattern already in place.

### 2. Update `AgentTaskResponse` API schema — add `checklist` field

Locate the existing `AgentTaskResponse` Pydantic response model in the FastAPI backend (typically `backend/app/schemas/agent_task.py` or equivalent path established in US-006).

```python
# backend/app/schemas/agent_task.py  (MODIFY existing file)

from typing import Any
from app.models.handoff_checklist import ChecklistItem  # ADD

class AgentTaskResponse(BaseModel):
    # ... existing fields (id, encounter_id, task_type, status, created_at, etc.) ...

    # ADD: checklist fields sourced from metadata JSONB
    checklist: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "AI-generated or template handoff checklist items. "
            "Present on coordinator tasks for encounters with ADT events."
        ),
    )
    checklist_generated_type: str | None = Field(
        default=None,
        description="Source of checklist: 'LLM' or 'TEMPLATE' (fallback).",
    )
```

### 3. Update `AgentTask` serialiser — populate `checklist` from `metadata`

In the FastAPI endpoint or repository layer that serialises `AgentTask` ORM objects to `AgentTaskResponse`, add extraction of the checklist from `metadata`:

```python
# In the serialiser / response mapper (endpoint or repository):

def _to_response(task: AgentTask) -> AgentTaskResponse:
    metadata: dict = task.metadata or {}
    return AgentTaskResponse(
        # ... existing field mappings ...
        checklist=metadata.get("checklist"),
        checklist_generated_type=metadata.get("generated_type"),
    )
```

### 4. Verify `GET /api/v1/encounters/{id}/tasks` returns checklist

The existing endpoint (implemented in US-006 or US-020) should now return the `checklist` field automatically via the updated `AgentTaskResponse` schema. No route change is needed — only the response model update from Step 2.

---

## Validation

Run from project root (requires database and coordinator running locally or in test mode):

```bash
# 1. AgentTaskResponse schema includes checklist field
python -c "
from backend.app.schemas.agent_task import AgentTaskResponse
fields = AgentTaskResponse.model_fields.keys()
assert 'checklist' in fields, 'checklist field missing from AgentTaskResponse'
assert 'checklist_generated_type' in fields, 'checklist_generated_type missing'
print('AgentTaskResponse schema check: PASSED')
"

# 2. Checklist payload serialises to JSON correctly
python -c "
from app.models.handoff_checklist import HandoffChecklist, ChecklistItem
checklist = HandoffChecklist(
    checklist=[
        ChecklistItem(item='Verify discharge prescription reviewed', category='medications', priority='HIGH'),
        ChecklistItem(item='Confirm follow-up appointment scheduled', category='follow_up', priority='MEDIUM'),
        ChecklistItem(item='Review patient education materials provided', category='patient_education', priority='LOW'),
    ],
    generated_type='LLM',
    transition_type='A03',
)
payload = [item.model_dump() for item in checklist.checklist]
assert len(payload) == 3
assert all('item' in i and 'category' in i and 'priority' in i for i in payload)
print('Checklist JSONB payload structure: PASSED')
"

# 3. JSONB merge operator preserves existing metadata keys
python -c "
import json
existing = {'task_type': 'coordinator', 'sla_deadline': '2026-07-16T10:00:00Z'}
new_checklist = {'checklist': [{'item': 'Verify labs', 'category': 'documentation', 'priority': 'HIGH'}], 'generated_type': 'TEMPLATE'}
# Simulate PostgreSQL || JSONB merge
merged = {**existing, **new_checklist}
assert 'task_type' in merged
assert 'checklist' in merged
print('JSONB metadata merge preserves existing keys: PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| MODIFY | `coordinator-agent/app/coordinator/agent.py` |
| MODIFY | `backend/app/schemas/agent_task.py` |
| MODIFY | `backend/app/api/v1/encounters.py` (serialiser, if applicable) |

---

## Definition of Done Checklist

- [ ] `CoordinatorAgent.__init__()` instantiates `ChecklistService`
- [ ] `CoordinatorAgent.process_event()` calls `ChecklistService.generate()` with PHI-safe `ChecklistInput`
- [ ] `_persist_checklist()` writes checklist to `agent_task.metadata` using PostgreSQL JSONB merge (`||` operator)
- [ ] Existing metadata fields are preserved — JSONB merge does not overwrite unrelated keys
- [ ] `AgentTaskResponse` schema includes `checklist: list[dict] | None` and `checklist_generated_type: str | None`
- [ ] `GET /api/v1/encounters/{id}/tasks` response includes populated `checklist` field for coordinator tasks
- [ ] Structured log `checklist_persisted` contains `agent_task_id`, `generated_type`, `item_count` — no PHI
- [ ] All 3 validation scripts pass cleanly
