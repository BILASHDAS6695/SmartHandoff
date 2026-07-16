---
id: TASK-005
title: "Implement `GET /api/v1/encounters/{id}/tasks` — Task Status API Endpoint with SLA Fields"
user_story: US-021
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-002, US-006/TASK-004]
---

# TASK-005: Implement `GET /api/v1/encounters/{id}/tasks` — Task Status API Endpoint with SLA Fields

> **Story:** US-021 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-021 Scenario 2 specifies a new read endpoint:

> *"`GET /api/v1/encounters/ENC-001/tasks` returns all 5 tasks with `id`, `agent_type`, `status`, `start_time`, `completed_time`, `sla_threshold_minutes`, and `sla_breached` flag"*
> *"Task status API secured: requires valid staff JWT (EP-011 auth middleware)"*

This task adds the endpoint to the FastAPI backend's `encounters` router. The endpoint:

1. Requires a valid staff JWT (existing `get_current_user` dependency).
2. Queries `AgentTask` records by `encounter_id` from the read replica.
3. Returns a list of `AgentTaskResponse` Pydantic schemas including all seven required fields.
4. Returns `404` if the encounter does not exist (guarded by `get_encounter_or_404` dependency).
5. Populates `sla_threshold_minutes` in the response from `SLAConfig` for tasks where the column is `NULL` (tasks created before TASK-002 migration ran).

---

## Acceptance Criteria Addressed

| US-021 AC | Requirement |
|---|---|
| **Scenario 2** | Returns all tasks for encounter with all 7 required fields including `sla_breached` |
| **DoD** | Endpoint secured with valid staff JWT |

---

## Implementation Steps

### 1. Create `backend/app/schemas/agent_task.py`

```python
"""Pydantic response schemas for AgentTask API endpoints.

US-021 Scenario 2: Response must include id, agent_type, status, start_time,
completed_time, sla_threshold_minutes, sla_breached.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.config.sla_loader import load_sla_config


class AgentTaskResponse(BaseModel):
    """Response schema for a single AgentTask.

    All seven fields required by US-021 Scenario 2 are present.
    `sla_threshold_minutes` is backfilled from SLAConfig if NULL in DB
    (handles tasks created before TASK-002 migration).
    """

    id: UUID
    agent_type: str
    status: str
    start_time: datetime = Field(alias="created_at")
    completed_time: datetime | None = Field(None, alias="completed_at")
    sla_threshold_minutes: int | None
    sla_breached: bool

    model_config = {"populate_by_name": True, "from_attributes": True}

    @model_validator(mode="after")
    def _backfill_sla_threshold(self) -> "AgentTaskResponse":
        """Backfill sla_threshold_minutes from SLAConfig if not yet set in DB."""
        if self.sla_threshold_minutes is None:
            config = load_sla_config()
            self.sla_threshold_minutes = config.threshold_for(self.agent_type)
        return self


class AgentTaskListResponse(BaseModel):
    """Paginated list of AgentTask records for an encounter."""

    encounter_id: UUID
    tasks: list[AgentTaskResponse]
    total: int
```

### 2. Create `backend/app/routers/encounter_tasks.py`

```python
"""Router: GET /api/v1/encounters/{encounter_id}/tasks

Returns all AgentTask records for a given encounter with SLA fields.

Security: requires valid staff JWT via get_current_user dependency (EP-011).
DB: reads from replica session (TR-010) — no write operations.

US-021 Scenario 2: Returns tasks with id, agent_type, status, start_time,
completed_time, sla_threshold_minutes, sla_breached.
"""
from __future__ import annotations

import logging
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_staff_user
from app.db.dependencies import get_read_db
from app.models.agent_task import AgentTask
from app.models.encounter import Encounter
from app.schemas.agent_task import AgentTaskListResponse, AgentTaskResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/encounters", tags=["encounters", "tasks"])


async def _get_encounter_or_404(
    encounter_id: UUID,
    db: AsyncSession,
) -> Encounter:
    """Verify the encounter exists; raise 404 if not found."""
    encounter = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Encounter {encounter_id} not found.",
        )
    return encounter


@router.get(
    "/{encounter_id}/tasks",
    response_model=AgentTaskListResponse,
    summary="List all agent tasks for an encounter with SLA status",
    responses={
        200: {"description": "Task list returned successfully"},
        401: {"description": "Missing or invalid JWT"},
        403: {"description": "Insufficient role"},
        404: {"description": "Encounter not found"},
    },
)
async def list_encounter_tasks(
    encounter_id: UUID,
    db: AsyncSession = Depends(get_read_db),
    current_user=Depends(get_current_staff_user),
) -> AgentTaskListResponse:
    """Return all AgentTask records for the specified encounter.

    Requires a valid staff JWT. Uses the read replica for query performance (TR-010).
    Includes sla_threshold_minutes (backfilled from config if NULL) and sla_breached flag.
    """
    # Validate encounter exists
    await _get_encounter_or_404(encounter_id, db)

    stmt = (
        sa.select(AgentTask)
        .where(AgentTask.encounter_id == encounter_id)
        .order_by(AgentTask.created_at.asc())
    )
    result = await db.execute(stmt)
    tasks: list[AgentTask] = list(result.scalars().all())

    logger.info(
        "Tasks fetched: encounter_id=%s count=%d user=%s",
        encounter_id,
        len(tasks),
        current_user.id,
    )

    task_responses = [AgentTaskResponse.model_validate(t) for t in tasks]

    return AgentTaskListResponse(
        encounter_id=encounter_id,
        tasks=task_responses,
        total=len(task_responses),
    )
```

### 3. Register the Router in `backend/app/main.py`

Locate the existing router registration section in `backend/app/main.py` and add:

```python
from app.routers.encounter_tasks import router as encounter_tasks_router

app.include_router(encounter_tasks_router)
```

### 4. Example Response

`GET /api/v1/encounters/3fa85f64-5717-4562-b3fc-2c963f66afa6/tasks`

```json
{
  "encounter_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "tasks": [
    {
      "id": "a1b2c3d4-0001-0000-0000-000000000001",
      "agent_type": "DOCUMENTATION",
      "status": "IN_PROGRESS",
      "start_time": "2026-07-16T08:00:00Z",
      "completed_time": null,
      "sla_threshold_minutes": 30,
      "sla_breached": true
    },
    {
      "id": "a1b2c3d4-0002-0000-0000-000000000002",
      "agent_type": "BED_MANAGEMENT",
      "status": "COMPLETED",
      "start_time": "2026-07-16T08:05:00Z",
      "completed_time": "2026-07-16T08:12:00Z",
      "sla_threshold_minutes": 15,
      "sla_breached": false
    }
  ],
  "total": 2
}
```

---

## Validation Checklist

- [ ] `GET /api/v1/encounters/{id}/tasks` returns `200` with all 7 fields per task
- [ ] Response includes `sla_threshold_minutes` (backfilled from `SLAConfig` if DB column is `NULL`)
- [ ] `sla_breached` reflects current flag value from DB
- [ ] Request without JWT returns `401 Unauthorized`
- [ ] Request with non-staff JWT returns `403 Forbidden`
- [ ] `encounter_id` that does not exist returns `404 Not Found`
- [ ] Query routes to read replica (`get_read_db` dependency)
- [ ] `AgentTaskListResponse.total` equals length of `tasks` list
- [ ] Router registered in `backend/app/main.py`

---

## Files Created / Modified

| Path | Change |
|---|---|
| `backend/app/schemas/agent_task.py` | New — `AgentTaskResponse` and `AgentTaskListResponse` Pydantic schemas |
| `backend/app/routers/encounter_tasks.py` | New — `GET /api/v1/encounters/{encounter_id}/tasks` endpoint |
| `backend/app/main.py` | Register `encounter_tasks_router` |

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `load_sla_config()` for SLA threshold backfill in schema |
| TASK-002 | Task | `sla_threshold_minutes` and `sla_breached` columns on `AgentTask` |
| US-006/TASK-004 | Story | `Encounter` model must exist for 404 guard |
| EP-011 auth middleware | Epic | `get_current_staff_user` dependency |
