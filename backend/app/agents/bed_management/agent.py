"""BedManagementAgent — processes ADT events and updates bed status.

Subscribes to the ``adt-events`` Pub/Sub topic via ``bed-mgmt-agent-sub``.
Handles A01 (admit), A02 (transfer), and A03 (discharge) events, writing
bed status changes to the primary DB and triggering a CONCURRENTLY
materialised-view refresh via the BedBoardRefreshService (TASK-002).

Design refs:
    US-035 AC Scenarios 1, 2
    design.md §3.1  — Bed Management Agent responsibility
    design.md §3.2  — Agent container pattern
    ADR-001         — dedicated Pub/Sub subscription per agent
    ADR-004         — LangChain agent framework; Pydantic structured output
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.agents.bed_management.schemas import BedStatus, BedStatusUpdateResult
from app.agents.bed_management.status_machine import resolve_target_status
from app.exceptions import BedStatusTransitionError
from app.models.bed import Bed


logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """Raised for transient failures that should trigger retry logic."""
    pass


class BedManagementAgent(BaseAgent):
    """Processes A01/A02/A03 ADT events and updates bed status.

    Inherits Pub/Sub consumption, retry, DLQ handling, and cancellation
    flag checking from ``BaseAgent`` (US-024).

    Args:
        db_session_factory: Async SQLAlchemy session factory (write session).
        refresh_service: ``BedBoardRefreshService`` instance (TASK-002).
        housekeeping_notifier: ``HousekeepingNotifier`` instance (TASK-004).
        prediction_service: ``DischargePredictionService`` instance (US-036 TASK-004) — optional.
    """

    HANDLED_EVENT_TYPES = frozenset({"A01", "A02", "A03"})

    def __init__(
        self,
        db_session_factory: Any,
        refresh_service: Any,
        housekeeping_notifier: Any,
        prediction_service: Any | None = None,
    ) -> None:
        super().__init__(subscription_id="bed-mgmt-agent-sub")
        self._db_session_factory = db_session_factory
        self._refresh_service = refresh_service
        self._housekeeping_notifier = housekeeping_notifier
        self._prediction_service = prediction_service

    def can_handle(self, event_type: str) -> bool:
        """Return True if this agent can process the given ADT event type."""
        return event_type in self.HANDLED_EVENT_TYPES

    async def process(self, message: dict[str, Any]) -> BedStatusUpdateResult:
        """Handle a single ADT event message from Pub/Sub.

        Args:
            message: Decoded Pub/Sub message payload containing at minimum
                ``event_type``, ``encounter_id``, ``bed_id``, and for A02
                also ``previous_bed_id``.

        Returns:
            ``BedStatusUpdateResult`` describing the completed transition.

        Raises:
            RetryableError: On transient DB failures.
            BedStatusTransitionError: On invalid state transitions (non-retryable).
        """
        event_type: str = message["event_type"]
        encounter_id: str = message["encounter_id"]

        if event_type not in self.HANDLED_EVENT_TYPES:
            logger.debug(
                "Skipping unhandled event type=%s encounter_id=%s",
                event_type,
                encounter_id,
            )
            return None  # type: ignore[return-value]

        logger.info(
            "Processing event_type=%s encounter_id=%s",
            event_type,
            encounter_id,
        )

        async with self._db_session_factory() as session:
            try:
                result = await self._handle_event(session, event_type, encounter_id, message)
                await session.commit()
            except BedStatusTransitionError:
                # Non-retryable: log and ack (do not DLQ for invalid transitions)
                logger.warning(
                    "Invalid bed status transition encounter_id=%s event_type=%s",
                    encounter_id,
                    event_type,
                )
                await session.rollback()
                raise
            except Exception as exc:
                await session.rollback()
                raise RetryableError(f"DB error processing {event_type}: {exc}") from exc

        # Post-commit side effects (non-transactional)
        await self._refresh_service.refresh_async()
        result = result.model_copy(update={"mv_refresh_triggered": True})

        if event_type == "A03":
            await self._housekeeping_notifier.notify(
                bed_id=result.bed_id,
                encounter_id=encounter_id,
            )
            result = result.model_copy(update={"housekeeping_notification_published": True})

        # US-036 TASK-004: Trigger discharge time prediction update (AC Scenario 3)
        # Called outside the main bed-status transaction so a prediction failure
        # never rolls back the bed status write.
        if self._prediction_service is not None and event_type in ("A01", "A02", "A03"):
            async with self._db_session_factory() as pred_session:
                await self._prediction_service.update_prediction(
                    session=pred_session,
                    encounter_id=encounter_id,
                    refresh_service=self._refresh_service,
                )

        return result

    async def _handle_event(
        self,
        session: AsyncSession,
        event_type: str,
        encounter_id: str,
        message: dict[str, Any],
    ) -> BedStatusUpdateResult:
        """Dispatch to the appropriate event handler.

        A02 requires updating two beds: the previous bed (→ DIRTY) and the
        new assigned bed (→ OCCUPIED).
        """
        if event_type == "A02":
            return await self._handle_transfer(session, encounter_id, message)
        return await self._handle_single_bed_transition(
            session, event_type, encounter_id, message
        )

    async def _handle_single_bed_transition(
        self,
        session: AsyncSession,
        event_type: str,
        encounter_id: str,
        message: dict[str, Any],
    ) -> BedStatusUpdateResult:
        """Handle A01 or A03 — single bed status update."""
        bed_id: str = message["bed_id"]
        bed = await self._fetch_bed(session, bed_id)
        current_status = BedStatus(bed.status)
        target_status = resolve_target_status(event_type, current_status)

        await session.execute(
            update(Bed)
            .where(Bed.id == uuid.UUID(bed_id))
            .values(status=target_status.value.lower())
        )

        return BedStatusUpdateResult(
            bed_id=bed_id,
            previous_status=current_status,
            new_status=target_status,
            encounter_id=encounter_id,
            event_type=event_type,
        )

    async def _handle_transfer(
        self,
        session: AsyncSession,
        encounter_id: str,
        message: dict[str, Any],
    ) -> BedStatusUpdateResult:
        """Handle A02 — mark previous bed DIRTY, new bed OCCUPIED."""
        previous_bed_id: str = message["previous_bed_id"]
        new_bed_id: str = message["bed_id"]

        # Previous bed → DIRTY
        await session.execute(
            update(Bed)
            .where(Bed.id == uuid.UUID(previous_bed_id))
            .values(status=BedStatus.DIRTY.value.lower())
        )
        # New bed → OCCUPIED
        await session.execute(
            update(Bed)
            .where(Bed.id == uuid.UUID(new_bed_id))
            .values(status=BedStatus.OCCUPIED.value.lower())
        )

        return BedStatusUpdateResult(
            bed_id=new_bed_id,
            previous_status=BedStatus.OCCUPIED,
            new_status=BedStatus.OCCUPIED,
            encounter_id=encounter_id,
            event_type="A02",
        )

    async def _fetch_bed(self, session: AsyncSession, bed_id: str) -> Bed:
        """Load bed record; raises RetryableError if not found."""
        result = await session.execute(select(Bed).where(Bed.id == uuid.UUID(bed_id)))
        bed = result.scalar_one_or_none()
        if bed is None:
            raise RetryableError(f"Bed not found: {bed_id}")
        return bed
