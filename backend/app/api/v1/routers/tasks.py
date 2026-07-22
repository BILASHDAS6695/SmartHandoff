"""Agent task resource router — RBAC-protected endpoints."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth.jwt import TokenClaims
from app.core.auth.rbac import require_permission

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(
    current_user: Annotated[TokenClaims, Depends(require_permission("agent_task", "list"))],
) -> dict:
    """List agent tasks — requires agent_task:list permission."""
    return {"tasks": [], "user": current_user.sub}


@router.get("/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    current_user: Annotated[TokenClaims, Depends(require_permission("agent_task", "read"))],
) -> dict:
    """Get a single agent task — requires agent_task:read permission."""
    return {"task_id": str(task_id), "user": current_user.sub}
