"""TaskStatusTransitionService — DB write + SignalR broadcast in one unit.

Sequence per US-022 Scenario 1:
  1. Update AgentTask.status in DB (write session, ACID).
  2. After commit, call SignalRBroadcaster.broadcast_task_updated() (fire-and-forget).

The broadcast is outside the DB transaction to ensure:
  - A SignalR failure never causes DB rollback.
  - Latency of broadcast does not extend the DB transaction lock window.

US-022 DoD: agent calls SignalR broadcast after each status transition.
US-022 Scenario 1: task_updated event reaches Angular within 1s of DB write.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_task import AgentTask, AgentTaskStatus
from app.signalr.broadcaster import SignalRBroadcaster
from app.signalr.schemas import TaskUpdatedPayload

logger = logging.getLogger(__name__)


class TaskStatusTransitionService:
    """Orchestrates AgentTask status transitions with SignalR broadcast.

    Injected into:
      - FastAPI routers (via FastAPI DI).
      - Agent Cloud Run containers (via module-level singleton initialised at startup).
    """

    def __init__(self, broadcaster: SignalRBroadcaster | None) -> None:
        self._broadcaster = broadcaster

    async def transition(
        self,
        db: AsyncSession,
        task: AgentTask,
        new_status: AgentTaskStatus,
    ) -> AgentTask:
        """Transition task to new_status, commit, then broadcast.

        Args:
            db:         Write-capable async session (must NOT be a read replica session).
            task:       ORM instance fetched in the same session (avoids re-fetch).
            new_status: Target status enum value.

        Returns:
            Updated AgentTask instance (post-commit state).

        Raises:
            ValueError: If the transition is not valid per US-021 state machine.
        """
        previous_status = task.status
        _validate_transition(previous_status, new_status)

        task.status = new_status.value
        if new_status in (AgentTaskStatus.COMPLETED, AgentTaskStatus.FAILED):
            task.completed_at = datetime.now(timezone.utc)

        await db.flush()
        await db.commit()
        await db.refresh(task)

        logger.info(
            "AgentTask status transitioned",
            extra={
                "task_id": str(task.id),
                "previous_status": previous_status,
                "new_status": new_status.value,
            },
        )

        # Fire-and-forget: broadcast AFTER commit — errors are swallowed by broadcaster.
        # Convert status strings to enum names for the payload schema
        previous_status_name = AgentTaskStatus(previous_status).name
        new_status_name = new_status.name
        
        payload = TaskUpdatedPayload(
            task_id=task.id,
            encounter_id=task.encounter_id,
            unit_id=task.unit_id,          # denormalised field on AgentTask (see note below)
            role_name=task.target_role,    # denormalised field on AgentTask
            agent_type=task.agent_type,
            previous_status=previous_status_name,
            new_status=new_status_name,
            updated_at=task.completed_at or datetime.now(timezone.utc),
        )
        if self._broadcaster is not None:
            await self._broadcaster.broadcast_task_updated(payload)
        else:
            logger.debug(
                "Skipping SignalR broadcast: broadcaster not configured",
                extra={"task_id": str(task.id), "new_status": new_status_name},
            )

        return task


# Valid state machine transitions per US-021 / US-020.
_VALID_TRANSITIONS: dict[AgentTaskStatus, set[AgentTaskStatus]] = {
    AgentTaskStatus.PENDING: {AgentTaskStatus.IN_PROGRESS},
    AgentTaskStatus.IN_PROGRESS: {
        AgentTaskStatus.COMPLETED,
        AgentTaskStatus.FAILED,
        AgentTaskStatus.PENDING_APPROVAL,
    },
    AgentTaskStatus.FAILED: {AgentTaskStatus.IN_PROGRESS},  # retry path
    AgentTaskStatus.COMPLETED: set(),
    AgentTaskStatus.QUEUED: {AgentTaskStatus.PENDING, AgentTaskStatus.IN_PROGRESS},
    AgentTaskStatus.BLOCKED: {AgentTaskStatus.IN_PROGRESS, AgentTaskStatus.PENDING},
    AgentTaskStatus.PENDING_APPROVAL: {
        AgentTaskStatus.COMPLETED,
        AgentTaskStatus.FAILED,
        AgentTaskStatus.CANCELLED,
    },
    AgentTaskStatus.CANCELLED: set(),
}


def _validate_transition(
    current: str, target: AgentTaskStatus
) -> None:
    """Raise ValueError if the (current → target) transition is not allowed."""
    try:
        current_enum = AgentTaskStatus(current)
    except ValueError:
        raise ValueError(f"Invalid current status: {current}")
    
    allowed = _VALID_TRANSITIONS.get(current_enum, set())
    if target not in allowed:
        raise ValueError(
            f"Invalid AgentTask transition: {current} → {target.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
