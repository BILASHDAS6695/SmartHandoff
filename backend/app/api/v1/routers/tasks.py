"""Agent task resource router — RBAC-protected endpoints.

US-034/TASK-005: Manual task override endpoint for charge pharmacists.
"""
from __future__ import annotations

import uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import require_role
from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission
from app.db.deps import get_read_db, get_write_db
from app.models.agent_task import AgentTask
from app.repositories.agent_task_repository import (
    AgentTaskRepository,
    InvalidTaskTypeError,
    TaskAlreadyCompletedError,
    TaskNotFoundError,
)
from app.schemas.agent_task import AgentTaskResponse
from app.schemas.task_override import TaskOverrideRequest, TaskOverrideResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])

# US-034 Technical Notes: Only charge_pharmacist and pharmacy_supervisor can override
_OVERRIDE_ALLOWED_ROLES = ["CHARGE_PHARMACIST", "PHARMACY_SUPERVISOR"]


@router.get("", response_model=list[AgentTaskResponse])
async def list_tasks(
    current_user: Annotated[TokenClaims, Depends(require_permission("agent_task", "list"))],
    status: str | None = Query(None, description="Optional status filter"),
    db: AsyncSession = Depends(get_read_db),
) -> list[AgentTaskResponse]:
    """List agent tasks across all encounters — requires agent_task:list permission."""
    stmt = sa.select(AgentTask).order_by(AgentTask.created_at.desc())
    if status:
        stmt = stmt.where(AgentTask.status == status.upper())
    result = await db.execute(stmt)
    tasks: list[AgentTask] = list(result.scalars().all())
    return [AgentTaskResponse.model_validate(task) for task in tasks]


@router.get("/{task_id}", response_model=AgentTaskResponse)
async def get_task(
    task_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("agent_task", "read"))],
    db: AsyncSession = Depends(get_read_db),
) -> AgentTaskResponse:
    """Get a single agent task — requires agent_task:read permission."""
    task = await db.get(AgentTask, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found.",
        )
    return AgentTaskResponse.model_validate(task)


@router.patch(
    "/encounters/{encounter_id}/override/{task_id}",
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
        422: {"description": "Task is not a MEDICATION_RECONCILIATION task"},
    },
)
async def override_task(
    encounter_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskOverrideRequest,
    current_user: Annotated[TokenClaims, Depends(require_role(_OVERRIDE_ALLOWED_ROLES))],
    db: AsyncSession = Depends(get_write_db),
) -> TaskOverrideResponse:
    """PATCH /api/v1/tasks/encounters/{encounter_id}/override/{task_id}

    RBAC: CHARGE_PHARMACIST or PHARMACY_SUPERVISOR only (US-034 Technical Notes).
    
    US-034 Scenario 4: Charge pharmacist manually marks reconciliation as reviewed.
    Clears sla_escalation_sent_at to prevent further SLA escalations for this task.
    """
    repo = AgentTaskRepository()
    try:
        task = await repo.override_task(
            task_id=task_id,
            encounter_id=encounter_id,
            actor_id=uuid.UUID(current_user.sub),
            note=body.note,
            session=db,
        )
    except TaskNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found for this encounter",
        )
    except InvalidTaskTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Override only supported for MEDICATION_RECONCILIATION tasks; got {exc.agent_type}",
        )
    except TaskAlreadyCompletedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task is already completed",
        )

    return TaskOverrideResponse(
        task_id=task.id,
        encounter_id=task.encounter_id,
        agent_type=task.agent_type,
        status=task.status.value,
        completed_at=task.completed_at,
        sla_escalation_sent_at=task.sla_escalation_sent_at,
        overridden_by=uuid.UUID(current_user.sub),
        note=body.note,
    )
