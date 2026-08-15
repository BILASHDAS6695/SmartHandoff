"""BoardingAlertPublisher — dispatches boarding alerts to Pub/Sub with idempotency.

Receives ``BoardingCandidate`` instances from ``BoardingMonitor`` and, for each
un-alerted encounter, publishes a ``BoardingAlertPayload`` to the
``notification-requests`` Pub/Sub topic, then sets ``boarding_alert_sent_at``
on the encounter record.

Idempotency strategy:
    1. In-memory check: ``candidate.already_alerted`` (fast path, no DB hit).
    2. DB-level guard: UPDATE ... WHERE boarding_alert_sent_at IS NULL ensures
       exactly-once write even under concurrent monitor instances.

Design refs:
    US-038 AC Scenario 1   — priority=IMMEDIATE, payload structure
    US-038 AC Scenario 4   — idempotency; boarding_alert_sent_at set after publish
    US-038 TASK-003        — BoardingAlertPublisher implementation
    design.md §7.5 AIR-040 — notification-requests topic; idempotency_key attribute
    BR-020                 — no PHI in Pub/Sub payloads (patient_id is opaque UUID)
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from google.cloud import pubsub_v1
except Exception:  # pragma: no cover - google-cloud-pubsub may be absent in local dev
    pubsub_v1 = None  # type: ignore[assignment]

from app.agents.bed_management.boarding_schemas import (
    BoardingAlertPayload,
    BoardingCandidate,
)
from app.models.encounter import Encounter
from app.signalr.schemas import BoardingAlertPayload as SignalRBoardingAlertPayload

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = logging.getLogger(__name__)

# Type alias for the session factory injected at construction time
SessionFactory = Callable[[], "Coroutine[Any, Any, AsyncSession]"]


class BoardingAlertPublisher:
    """Publishes ED boarding alerts to ``notification-requests`` with idempotency.

    Args:
        pubsub_client: Initialised ``google.cloud.pubsub_v1.PublisherClient``.
        db_session_factory: Async context manager factory returning an ``AsyncSession``
                            scoped to the write (primary) DB.
        project_id: GCP project ID for topic path construction.
        topic_path: Override for the Pub/Sub topic path. Defaults to
                    ``projects/{project_id}/topics/notification-requests``.
        signalr_broadcaster: Optional SignalR broadcaster to push an in-app
            notification to bed managers in real time (local dev / test).

    Design refs:
        US-038 TASK-003 — BoardingAlertPublisher class definition
        US-038 AC Scenario 1 — priority=IMMEDIATE, all required fields
        US-038 AC Scenario 4 — idempotency via boarding_alert_sent_at
    """

    def __init__(
        self,
        pubsub_client: pubsub_v1.PublisherClient | None,
        db_session_factory: SessionFactory,
        project_id: str,
        topic_path: str | None = None,
        signalr_broadcaster: Any | None = None,
    ) -> None:
        self._client = pubsub_client
        self._session_factory = db_session_factory
        self._signalr_broadcaster = signalr_broadcaster
        if topic_path:
            self._topic_path = topic_path
        elif pubsub_v1 is not None:
            self._topic_path = pubsub_v1.PublisherClient.topic_path(
                project_id, "notification-requests"
            )
        else:
            self._topic_path = f"projects/{project_id}/topics/notification-requests"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch_alerts(self, candidates: list[BoardingCandidate]) -> None:
        """Dispatch boarding alerts for all un-alerted candidates.

        Args:
            candidates: List produced by ``BoardingMonitor._detect_boarding_candidates()``.
                        May contain already-alerted encounters (idempotency check filters them).

        Design ref:
            US-038 TASK-003 — dispatch_alerts() method with idempotency filtering
        """
        for candidate in candidates:
            # Fast-path idempotency check (no DB round-trip needed when field is set)
            if candidate.already_alerted:
                logger.debug(
                    "Skipping boarding alert for encounter %s — already sent at %s.",
                    candidate.encounter_id,
                    candidate.boarding_alert_sent_at,
                )
                continue
            await self._publish_single(candidate)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _publish_single(self, candidate: BoardingCandidate) -> None:
        """Publish one boarding alert and record the send timestamp in the DB.

        Order of operations:
            1. Build the payload.
            2. Publish to Pub/Sub (non-transactional side effect).
            3. Write boarding_alert_sent_at to DB — WHERE boarding_alert_sent_at IS NULL
               ensures exactly-once even under concurrent monitor instances (DB-level guard).

        If Pub/Sub publish fails, no DB write is made so the next cycle will retry.

        Args:
            candidate: Un-alerted boarding candidate.

        Design refs:
            US-038 TASK-003 — _publish_single() with Pub/Sub + DB write
            US-038 AC Scenario 4 — DB-level idempotency guard
        """
        payload = BoardingAlertPayload(
            patient_id=candidate.patient_id,
            encounter_id=candidate.encounter_id,
            ed_arrival_time=candidate.ed_arrival_time.isoformat(),
            minutes_elapsed=candidate.minutes_elapsed,
            target_unit=candidate.target_unit,
            idempotency_key=candidate.idempotency_key,
        )

        # --- Pub/Sub publish (skipped if no client — local dev fallback) ---
        if self._client is not None:
            message_data = json.dumps(payload.model_dump()).encode("utf-8")
            attributes = {
                "notification_type": "ED_BOARDING_ALERT",
                "priority": "IMMEDIATE",
                "idempotency_key": candidate.idempotency_key,
            }
            try:
                future = self._client.publish(
                    self._topic_path, data=message_data, **attributes
                )
                message_id = future.result(timeout=10)
                logger.info(
                    "Boarding alert published: encounter=%s message_id=%s minutes_elapsed=%d",
                    candidate.encounter_id,
                    message_id,
                    candidate.minutes_elapsed,
                )
            except Exception:
                logger.exception(
                    "Failed to publish boarding alert for encounter %s — will retry next cycle.",
                    candidate.encounter_id,
                )
                return  # Do NOT write boarding_alert_sent_at — allow retry next cycle
        else:
            logger.info(
                "Boarding alert (local fallback) for encounter %s — Pub/Sub client not configured.",
                candidate.encounter_id,
            )

        # --- DB write (exactly-once guard) ---
        now_utc = datetime.now(UTC)
        async with self._session_factory() as session:  # type: AsyncSession
            # Parse encounter_id as UUID for query
            try:
                encounter_uuid = uuid.UUID(candidate.encounter_id)
            except ValueError:
                logger.error(
                    "Invalid encounter_id format: %s — skipping DB write.",
                    candidate.encounter_id,
                )
                return

            result = await session.execute(
                update(Encounter)
                .where(
                    Encounter.id == encounter_uuid,
                    Encounter.boarding_alert_sent_at.is_(None),  # DB-level idempotency
                )
                .values(boarding_alert_sent_at=now_utc)
                .returning(Encounter.id)
            )
            updated_id = result.scalar_one_or_none()
            if updated_id is None:
                # Another instance already wrote boarding_alert_sent_at — safe to ignore
                logger.info(
                    "boarding_alert_sent_at already set by concurrent instance for encounter %s.",
                    candidate.encounter_id,
                )
            else:
                logger.info(
                    "boarding_alert_sent_at set to %s for encounter %s.",
                    now_utc.isoformat(),
                    candidate.encounter_id,
                )
            await session.commit()

        # --- SignalR in-app notification (best-effort; local dev fallback) ---
        if self._signalr_broadcaster is not None:
            try:
                await self._signalr_broadcaster.broadcast_boarding_alert(
                    SignalRBoardingAlertPayload(
                        alert_id=candidate.idempotency_key,
                        encounter_id=candidate.encounter_id,
                        patient_unit=candidate.current_location or "ED",
                        minutes_elapsed=candidate.minutes_elapsed,
                        severity="HIGH",
                        title="ED Boarding Alert",
                        message=(
                            f"Patient has been waiting in {candidate.current_location or 'ED'} "
                            f"for {candidate.minutes_elapsed} minutes."
                        ),
                    )
                )
            except Exception as exc:
                logger.warning("SignalR boarding alert broadcast failed: %s", exc)
