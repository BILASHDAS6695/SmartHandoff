"""EncounterOrchestratorService — turns ADT events and alerts into agent tasks.

This service closes the gap between ADT/alert ingestion and the live dashboard:
  1. Decides which AgentTask rows to create for an ADT event type.
  2. Persists tasks inside an ACID transaction.
  3. Broadcasts a ``task_updated`` SignalR event for each new task **after**
     the DB commit so the Angular dashboard shows live status immediately.

Design refs:
    US-020/US-021 — Agent task lifecycle and state machine
    US-022        — SignalR broadcast after DB write
    US-048        — Real-time dashboard updates
"""
from __future__ import annotations

import logging
from typing import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.sla_loader import load_sla_config
from app.models.agent_task import AgentTask, AgentTaskStatus
from app.models.encounter import Encounter
from app.services.agent_task_factory import AGENT_ROLE_MAP, AgentTaskFactory
from app.signalr.broadcaster import SignalRBroadcaster
from app.signalr.schemas import TaskUpdatedPayload

logger = logging.getLogger(__name__)


class EncounterOrchestratorService:
    """Orchestrate AgentTask creation and broadcast for ADT-driven workflows."""

    def __init__(
        self,
        factory: AgentTaskFactory | None = None,
        broadcaster: SignalRBroadcaster | None = None,
    ) -> None:
        self._factory = factory or AgentTaskFactory()
        self._broadcaster = broadcaster

    async def create_tasks_for_adt_event(
        self,
        db: AsyncSession,
        encounter: Encounter,
        event_type: str | None,
        blocked: bool = False,
        blocked_reason: str | None = None,
    ) -> list[AgentTask]:
        """Create and persist AgentTasks for an ADT event, then broadcast them.

        Idempotent: only creates tasks for agent types that do not already exist
        for this encounter. Existing tasks are left untouched.

        Args:
            db: Write-capable async session.
            encounter: The encounter that received the ADT event.
            event_type: HL7 ADT event type, e.g. ``A01``.
            blocked: If True, tasks are created in BLOCKED status.
            blocked_reason: Reason for blocking (required when blocked=True).

        Returns:
            List of persisted AgentTask rows (newly created only).
        """
        desired = self._factory.create_tasks_for_adt_event(
            encounter=encounter,
            event_type=event_type,
            blocked=blocked,
            blocked_reason=blocked_reason,
        )

        existing_types = await self._existing_agent_types(db, encounter.id)
        missing = [t for t in desired if t.agent_type not in existing_types]

        if not missing:
            logger.info(
                "No new agent tasks to create for encounter=%s event_type=%s",
                encounter.id,
                event_type,
            )
            return []

        for task in missing:
            db.add(task)

        await db.flush()
        await db.commit()

        # Refresh tasks so generated IDs are populated for the broadcast payload.
        for task in missing:
            await db.refresh(task)

        logger.info(
            "Created %d agent tasks for encounter=%s event_type=%s",
            len(missing),
            encounter.id,
            event_type,
            extra={"task_ids": [str(t.id) for t in missing]},
        )

        await self._broadcast_new_tasks(missing)
        return missing

    async def ensure_task_for_alert(
        self,
        db: AsyncSession,
        encounter: Encounter,
        agent_type: str,
    ) -> tuple[AgentTask | None, bool]:
        """Ensure an agent task exists for a given alert; create one if missing.

        Used by pharmacist alert creation to guarantee a medication_reconciliation
        task is present before the alert is surfaced on the dashboard.

        Args:
            db: Write-capable async session.
            encounter: The encounter that owns the alert.
            agent_type: Agent type to ensure, e.g. ``medication_reconciliation``.

        Returns:
            Tuple of (task, created). ``created`` is True only when a new task
            row was inserted; False when an existing task was returned.
        """
        existing = await self._get_existing_task(db, encounter.id, agent_type)
        if existing:
            return existing, False

        sla_config = load_sla_config()
        task = AgentTask(
            encounter_id=encounter.id,
            agent_type=agent_type,
            status=AgentTaskStatus.PENDING.value,
            unit_id=encounter.unit or "unknown",
            target_role=AGENT_ROLE_MAP.get(agent_type, "unassigned"),
            sla_threshold_minutes=sla_config.threshold_for(agent_type.upper()),
            sla_breached=False,
        )
        db.add(task)
        await db.flush()
        await db.commit()
        await db.refresh(task)

        logger.info(
            "Created %s task for alert on encounter=%s",
            agent_type,
            encounter.id,
        )

        await self._broadcast_new_tasks([task])
        return task, True

    async def _existing_agent_types(
        self, db: AsyncSession, encounter_id: UUID
    ) -> set[str]:
        """Return the set of agent_type values already persisted for encounter."""
        stmt = sa.select(AgentTask.agent_type).where(
            AgentTask.encounter_id == encounter_id
        )
        result = await db.execute(stmt)
        return set(result.scalars().all())

    async def _get_existing_task(
        self,
        db: AsyncSession,
        encounter_id: UUID,
        agent_type: str,
    ) -> AgentTask | None:
        """Return a single existing task for encounter + agent_type, if any."""
        stmt = sa.select(AgentTask).where(
            AgentTask.encounter_id == encounter_id,
            AgentTask.agent_type == agent_type,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _broadcast_new_tasks(self, tasks: Sequence[AgentTask]) -> None:
        """Fire task_updated SignalR events for newly created tasks."""
        if self._broadcaster is None:
            logger.debug(
                "No SignalR broadcaster configured; skipping task creation broadcast"
            )
            return

        for task in tasks:
            payload = TaskUpdatedPayload(
                task_id=task.id,
                encounter_id=task.encounter_id,
                unit_id=task.unit_id,
                role_name=task.target_role,
                agent_type=task.agent_type.upper(),
                previous_status="PENDING",
                new_status="PENDING",
                updated_at=task.created_at,
            )
            try:
                await self._broadcaster.broadcast_task_updated(payload)
            except Exception:
                logger.exception(
                    "Failed to broadcast task_created event for task=%s",
                    task.id,
                )
