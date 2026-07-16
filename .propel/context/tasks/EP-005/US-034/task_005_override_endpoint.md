---
id: TASK-005
title: "Implement `PATCH /api/v1/encounters/{id}/tasks/{task_id}/override` Manual Completion Endpoint"
user_story: US-034
epic: EP-005
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-034/TASK-001, US-030/TASK-005]
---

# TASK-005: Implement `PATCH /api/v1/encounters/{id}/tasks/{task_id}/override` Manual Completion Endpoint

> **Story:** US-034 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-034 Scenario 4 requires:

> *"Given a charge pharmacist manually marks a reconciliation as `REVIEWED_MANUALLY` via the API"*
> *"When `PATCH /api/v1/encounters/{id}/tasks/{task_id}/override` is called"*
> *"Then `AgentTask.sla_escalation_sent_at` is cleared; `AgentTask.status=COMPLETED`; no further escalations fire for this task."*

RBAC: only `charge_pharmacist` or `pharmacy_supervisor` roles may call this endpoint (US-034 Technical Notes).

This endpoint:
1. Validates the caller role is `charge_pharmacist` or `pharmacy_supervisor`.
2. Loads the `AgentTask` by `task_id` — validates it belongs to the given `encounter_id`.
3. Verifies `agent_type = 'MEDICATION_RECONCILIATION'` (this endpoint is scoped to med rec only).
4. Sets `AgentTask.status = COMPLETED`, `AgentTask.completed_at = NOW()`, `AgentTask.sla_escalation_sent_at = NULL`.
5. Writes an `AuditLog` record with `action=TASK_MANUALLY_OVERRIDDEN`, `actor_id`, `encounter_id`, `task_id`, `note` (from request body).
6. Returns `HTTP 200` with the updated task representation.

**Design references:**
- US-034 Scenario 4 — override clears `sla_escalation_sent_at`, sets `status=COMPLETED`
- US-034 Technical Notes — RBAC: `charge_pharmacist` or `pharmacy_supervisor` only
- design.md §3.3 — RBAC enforcer in FastAPI middleware stack
- US-030/TASK-005 — medications router pattern to follow

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 4 | `sla_escalation_sent_at` cleared; `status=COMPLETED`; no further escalations fire |
| DoD | `PATCH /api/v1/encounters/{id}/tasks/{task_id}/override` endpoint for manual completion |
| DoD | Override endpoint RBAC: only `charge_pharmacist` or `pharmacy_supervisor` role may override |

---

## Implementation Steps

### 1. Add request/response schemas to `backend/app/api/v1/schemas/tasks.py`

```python
class TaskOverrideRequest(BaseModel):
    """Request body for PATCH /api/v1/encounters/{id}/tasks/{task_id}/override.

    US-034 Scenario 4: manual completion by charge pharmacist.
    """

    note: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Free-text justification for manual override (stored in audit log).",
        examples=["Reconciliation completed offline with attending; documented in EHR."],
    )


class TaskOverrideResponse(BaseModel):
    """Response body for successful task override."""

    task_id: UUID
    encounter_id: UUID
    agent_type: str
    status: str  # COMPLETED
    completed_at: datetime
    sla_escalation_sent_at: datetime | None  # always None after override
    overridden_by: UUID  # actor_id
    note: str
```

### 2. Add repository method to `backend/app/repositories/agent_task_repository.py`

Add `override_task` as a surgical addition — do not modify existing methods:

```python
async def override_task(
    self,
    *,
    task_id: UUID,
    encounter_id: UUID,
    actor_id: UUID,
    note: str,
    session: AsyncSession,
) -> AgentTask:
    """Mark a MEDICATION_RECONCILIATION AgentTask as COMPLETED via manual override.

    Clears ``sla_escalation_sent_at`` so no further escalations fire (US-034 Scenario 4).

    Args:
        task_id: UUID of the AgentTask to override.
        encounter_id: UUID of the encounter — validates task ownership.
        actor_id: UUID of the calling user (charge pharmacist / pharmacy supervisor).
        note: Free-text justification stored in audit log.
        session: Write session.

    Returns:
        The updated ``AgentTask`` instance.

    Raises:
        TaskNotFoundError: If the task does not exist or does not belong to the encounter.
        InvalidTaskTypeError: If the task is not a MEDICATION_RECONCILIATION task.
        TaskAlreadyCompletedError: If the task is already COMPLETED.
    """
    stmt = sa.select(AgentTask).where(
        AgentTask.id == task_id,
        AgentTask.encounter_id == encounter_id,
    )
    result = await session.execute(stmt)
    task: AgentTask | None = result.scalar_one_or_none()

    if task is None:
        raise TaskNotFoundError(task_id=task_id, encounter_id=encounter_id)
    if task.agent_type != "MEDICATION_RECONCILIATION":
        raise InvalidTaskTypeError(task_id=task_id, agent_type=task.agent_type)
    if task.status == AgentTaskStatus.COMPLETED:
        raise TaskAlreadyCompletedError(task_id=task_id)

    now = datetime.now(tz=timezone.utc)
    task.status = AgentTaskStatus.COMPLETED
    task.completed_at = now
    task.sla_escalation_sent_at = None  # US-034 Scenario 4: clear escalation flag

    await session.flush()
    return task
```

### 3. Add audit log write to `agent_task_repository.py`

Append to `override_task` after `await session.flush()`:

```python
    audit = AuditLog(
        action="TASK_MANUALLY_OVERRIDDEN",
        actor_id=actor_id,
        resource_type="agent_task",
        resource_id=task_id,
        encounter_id=encounter_id,
        note=note,
        timestamp=now,
    )
    session.add(audit)
    await session.commit()
    await session.refresh(task)
    return task
```

### 4. Add FastAPI router handler to `backend/app/api/v1/tasks.py`

If `tasks.py` does not exist, create it and register in `backend/app/api/v1/__init__.py`.

```python
"""Task management endpoints — US-034."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_write_db, require_roles
from app.api.v1.schemas.tasks import TaskOverrideRequest, TaskOverrideResponse
from app.repositories.agent_task_repository import (
    AgentTaskRepository,
    InvalidTaskTypeError,
    TaskAlreadyCompletedError,
    TaskNotFoundError,
)

router = APIRouter(prefix="/encounters/{encounter_id}/tasks", tags=["tasks"])

_OVERRIDE_ALLOWED_ROLES = {"charge_pharmacist", "pharmacy_supervisor"}


@router.patch(
    "/{task_id}/override",
    response_model=TaskOverrideResponse,
    status_code=status.HTTP_200_OK,
    summary="Manual task override (charge pharmacist / pharmacy supervisor only)",
    description=(
        "Marks a MEDICATION_RECONCILIATION AgentTask as COMPLETED via manual override. "
        "Clears sla_escalation_sent_at to stop further escalations (US-034)."
    ),
    responses={
        403: {"description": "Caller role not permitted to override tasks"},
        404: {"description": "Task not found for this encounter"},
        409: {"description": "Task is already completed"},
    },
)
async def override_task(
    encounter_id: UUID,
    task_id: UUID,
    body: TaskOverrideRequest,
    current_user=Depends(require_roles(_OVERRIDE_ALLOWED_ROLES)),
    db: AsyncSession = Depends(get_write_db),
) -> TaskOverrideResponse:
    """PATCH /api/v1/encounters/{encounter_id}/tasks/{task_id}/override

    RBAC: charge_pharmacist or pharmacy_supervisor only (US-034 Technical Notes).
    """
    repo = AgentTaskRepository()
    try:
        task = await repo.override_task(
            task_id=task_id,
            encounter_id=encounter_id,
            actor_id=current_user.id,
            note=body.note,
            session=db,
        )
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found for this encounter")
    except InvalidTaskTypeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Override only supported for MEDICATION_RECONCILIATION tasks; got {exc.agent_type}",
        )
    except TaskAlreadyCompletedError:
        raise HTTPException(status_code=409, detail="Task is already completed")

    return TaskOverrideResponse(
        task_id=task.id,
        encounter_id=task.encounter_id,
        agent_type=task.agent_type,
        status=task.status.value,
        completed_at=task.completed_at,
        sla_escalation_sent_at=task.sla_escalation_sent_at,
        overridden_by=current_user.id,
        note=body.note,
    )
```

### 5. Register the router in `backend/app/api/v1/__init__.py`

```python
from app.api.v1.tasks import router as tasks_router
api_router.include_router(tasks_router)
```

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/api/v1/schemas/tasks.py` | **New** — `TaskOverrideRequest`, `TaskOverrideResponse` |
| `backend/app/repositories/agent_task_repository.py` | Surgical: add `override_task()` + custom exception classes |
| `backend/app/api/v1/tasks.py` | **New** — `PATCH /{task_id}/override` route |
| `backend/app/api/v1/__init__.py` | Register `tasks_router` |

---

## Definition of Done Checklist

- [ ] `PATCH /api/v1/encounters/{encounter_id}/tasks/{task_id}/override` returns HTTP 200 on success
- [ ] `AgentTask.status = COMPLETED`, `completed_at = NOW()`, `sla_escalation_sent_at = None` after override
- [ ] `AuditLog` record written with `action=TASK_MANUALLY_OVERRIDDEN`, `actor_id`, `note`
- [ ] HTTP 403 if caller role is neither `charge_pharmacist` nor `pharmacy_supervisor`
- [ ] HTTP 404 if task not found or does not belong to the encounter
- [ ] HTTP 409 if task is already `COMPLETED`
- [ ] HTTP 422 if task is not a `MEDICATION_RECONCILIATION` task
- [ ] OpenAPI `summary`, `description`, `tags=["tasks"]`, response examples present
