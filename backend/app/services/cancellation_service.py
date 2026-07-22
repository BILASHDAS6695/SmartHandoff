"""Cancellation service — handles A11, A12, A13 ADT cancellation events.

Atomically reverts encounter status and cancels all non-terminal agent tasks
within a single SQLAlchemy async session (one transaction boundary).

Public API:
  CancellationService.handle_cancel_admit(encounter_id, db)
      A11: ADMITTED → PRE_ADMISSION; cancel pending/in-progress AgentTasks;
      soft-cancel all documents linked to the encounter.

  CancellationService.handle_cancel_transfer(encounter_id, db)
      A12: TRANSFERRED → ADMITTED; revert unit to previous_unit;
      cancel in-progress agent tasks.

  CancellationService.handle_cancel_discharge(encounter_id, db)
      A13: DISCHARGED → ADMITTED; soft-cancel discharge documents
      (status=CANCELLED, content retained); permit re-admission.

  CancellationService.cancel_agent_tasks(encounter_id, db) -> int
      Bulk-update all non-terminal AgentTask records to CANCELLED.
      Returns the number of rows updated.

Transaction contract:
  Each public method executes within a SINGLE database transaction.
  The caller must commit (session.commit()) after the method returns.
  If any step raises, the caller's transaction must be rolled back.

PHI safety (ADR-007):
  No PHI fields (patient name, MRN, DOB) are read or logged.
  Only encounter_id (UUID), task_id (UUID), and status strings are used.

Design refs:
    FR-006   — handle A11, A12, A13; halt in-progress agent workflows
    DR-005   — soft deletes; no hard delete on encounter or document records
    DR-023   — encounter state machine: invalid transitions rejected (409)
    US-015   — SC-1, SC-2, SC-3, DoD
    US-006   — encounter, agent_task, document ORM models
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import EncounterNotFoundError
from app.models.agent_task import AgentTask, AgentTaskStatus, AGENT_TASK_TERMINAL_STATUSES
from app.models.document import Document, DocumentStatus
from app.models.encounter import Encounter, EncounterStatus

logger = logging.getLogger(__name__)

# Non-terminal statuses — the values that cancel_agent_tasks targets
_NON_TERMINAL_STATUS_VALUES: list[str] = [
    s.value for s in AgentTaskStatus if s not in AGENT_TASK_TERMINAL_STATUSES
]

# Session flag used to authorise the DISCHARGED → ADMITTED A13 transition
_A13_FLAG = "allow_a13_cancel_discharge"


@dataclass(frozen=True, slots=True)
class CancellationResult:
    """Immutable result returned by CancellationService public methods."""

    encounter_id: UUID
    event_type: str          # "A11" | "A12" | "A13"
    tasks_cancelled: int
    docs_cancelled: int


class CancellationService:
    """Service for processing ADT cancellation events (A11, A12, A13).

    All public methods accept an ``AsyncSession`` and must be called within
    an active transaction context.  The caller is responsible for committing
    or rolling back the transaction.
    """

    # ------------------------------------------------------------------
    # A11: Cancel Admit
    # ------------------------------------------------------------------

    async def handle_cancel_admit(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> CancellationResult:
        """Handle A11 — cancel admit.

        Transitions: ADMITTED → PRE_ADMISSION.
        Cancels all non-terminal AgentTask records for the encounter.
        Soft-cancels any documents linked to the encounter.

        Args:
            encounter_id: UUID of the encounter being cancelled.
            db: Active SQLAlchemy async session (caller owns transaction).

        Returns:
            CancellationResult with event_type="A11", counts of cancelled tasks/docs.

        Raises:
            EncounterNotFoundError: If encounter_id does not exist.
            EncounterStateTransitionError: If encounter status is not ADMITTED.
        """
        encounter = await self._get_encounter(encounter_id, db)
        encounter.transition_to(EncounterStatus.PRE_ADMISSION)

        tasks_cancelled = await self.cancel_agent_tasks(encounter_id, db)
        docs_cancelled = await self._soft_cancel_documents(encounter_id, db)

        logger.info(
            "cancellation_service.a11_handled",
            extra={
                "encounter_id": str(encounter_id),
                "tasks_cancelled": tasks_cancelled,
                "docs_cancelled": docs_cancelled,
                "new_status": EncounterStatus.PRE_ADMISSION.value,
                "event_type": "A11",
            },
        )
        return CancellationResult(
            encounter_id=encounter_id,
            event_type="A11",
            tasks_cancelled=tasks_cancelled,
            docs_cancelled=docs_cancelled,
        )

    # ------------------------------------------------------------------
    # A12: Cancel Transfer
    # ------------------------------------------------------------------

    async def handle_cancel_transfer(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> CancellationResult:
        """Handle A12 — cancel transfer.

        Transitions: TRANSFERRED → ADMITTED.
        Reverts encounter.unit to encounter.previous_unit.
        Cancels in-progress agent tasks.

        Args:
            encounter_id: UUID of the encounter being reverted.
            db: Active SQLAlchemy async session.

        Returns:
            CancellationResult with event_type="A12".

        Raises:
            EncounterNotFoundError: If encounter_id does not exist.
            EncounterStateTransitionError: If encounter status is not TRANSFERRED.
        """
        encounter = await self._get_encounter(encounter_id, db)
        previous_unit = encounter.previous_unit

        encounter.transition_to(EncounterStatus.ADMITTED)
        encounter.unit = previous_unit  # revert unit to pre-transfer value

        tasks_cancelled = await self.cancel_agent_tasks(encounter_id, db)

        logger.info(
            "cancellation_service.a12_handled",
            extra={
                "encounter_id": str(encounter_id),
                "reverted_to_unit": str(previous_unit) if previous_unit else None,
                "tasks_cancelled": tasks_cancelled,
                "event_type": "A12",
            },
        )
        return CancellationResult(
            encounter_id=encounter_id,
            event_type="A12",
            tasks_cancelled=tasks_cancelled,
            docs_cancelled=0,
        )

    # ------------------------------------------------------------------
    # A13: Cancel Discharge
    # ------------------------------------------------------------------

    async def handle_cancel_discharge(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> CancellationResult:
        """Handle A13 — cancel discharge.

        Transitions: DISCHARGED → ADMITTED.
        Soft-cancels discharge document records (status=CANCELLED, content
        retained — DoD requirement: no hard delete).

        The A13 state machine flag is set on the session before the transition
        to satisfy the existing encounter state machine guard in
        ``encounter_statemachine.py``.

        Args:
            encounter_id: UUID of the encounter being reverted.
            db: Active SQLAlchemy async session.

        Returns:
            CancellationResult with event_type="A13".

        Raises:
            EncounterNotFoundError: If encounter_id does not exist.
            EncounterStateTransitionError: If encounter status is not DISCHARGED.
        """
        encounter = await self._get_encounter(encounter_id, db)

        # Authorise the DISCHARGED → ADMITTED transition via session flag
        db.info[_A13_FLAG] = str(encounter_id)
        encounter.transition_to(EncounterStatus.ADMITTED)

        docs_cancelled = await self._soft_cancel_documents(encounter_id, db)

        logger.info(
            "cancellation_service.a13_handled",
            extra={
                "encounter_id": str(encounter_id),
                "new_status": EncounterStatus.ADMITTED.value,
                "docs_cancelled": docs_cancelled,
                "event_type": "A13",
            },
        )
        return CancellationResult(
            encounter_id=encounter_id,
            event_type="A13",
            tasks_cancelled=0,
            docs_cancelled=docs_cancelled,
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def cancel_agent_tasks(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> int:
        """Bulk-update all non-terminal AgentTask records to CANCELLED.

        Uses a single UPDATE statement for efficiency; avoids row-by-row
        fetching.  Excludes tasks already in a terminal status
        (COMPLETED, CANCELLED, FAILED) to maintain idempotency.

        Args:
            encounter_id: UUID of the encounter whose tasks are to be cancelled.
            db: Active SQLAlchemy async session.

        Returns:
            Number of rows updated (0 if no non-terminal tasks exist).
        """
        result = await db.execute(
            update(AgentTask)
            .where(
                AgentTask.encounter_id == encounter_id,
                AgentTask.status.in_(_NON_TERMINAL_STATUS_VALUES),
            )
            .values(status=AgentTaskStatus.CANCELLED.value)
            .execution_options(synchronize_session="fetch")
        )
        rows_updated: int = result.rowcount
        return rows_updated

    async def _soft_cancel_documents(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> int:
        """Soft-cancel all non-cancelled Document records for an encounter.

        Sets Document.status = CANCELLED.  Document.content is NEVER modified
        (DoD: "Cancelled documents retain their content — no hard delete").

        Args:
            encounter_id: UUID of the encounter whose documents are soft-cancelled.
            db: Active SQLAlchemy async session.

        Returns:
            Number of document records updated.
        """
        result = await db.execute(
            update(Document)
            .where(
                Document.encounter_id == encounter_id,
                Document.status != DocumentStatus.CANCELLED.value,
            )
            .values(status=DocumentStatus.CANCELLED.value)
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount

    async def _get_encounter(
        self,
        encounter_id: UUID,
        db: AsyncSession,
    ) -> Encounter:
        """Fetch encounter by ID; raise EncounterNotFoundError if missing."""
        result = await db.execute(
            select(Encounter).where(Encounter.id == encounter_id)
        )
        encounter = result.scalar_one_or_none()
        if encounter is None:
            raise EncounterNotFoundError(encounter_id=encounter_id)
        return encounter
