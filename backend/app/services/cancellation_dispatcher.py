"""Post-commit dispatcher for ADT cancellation side effects.

Publishes a ``WORKFLOW_CANCELLED`` Pub/Sub event and broadcasts a SignalR
``ENCOUNTER_CANCELLED`` notification after the database transaction for an
ADT cancellation event (A11, A12, or A13) has committed successfully.

IMPORTANT: This module must NEVER be called inside a database transaction.
The dispatcher performs best-effort I/O; failures are logged but do not
roll back the committed DB state.

Pub/Sub message spec (``WORKFLOW_CANCELLED``):
  topic        : adt-events  (same topic as all ADT events — ADR-001)
  ordering_key : str(encounter_id)
  attributes:
    message_type   = "WORKFLOW_CANCELLED"
    event_type     = "A11" | "A12" | "A13"
    encounter_id   = str(UUID)
    iso_timestamp  = ISO-8601 UTC string
  body         : UTF-8 JSON — {"encounter_id": str, "event_type": str,
                                "tasks_cancelled": int, "docs_cancelled": int}

SignalR payload spec (``ENCOUNTER_CANCELLED``):
  group   : "encounter-{encounter_id}"
  event   : "ENCOUNTER_CANCELLED"
  payload :
    { "event": "ENCOUNTER_CANCELLED",
      "encounter_id": str(UUID),
      "event_type": "A11" | "A12" | "A13",
      "reason": "Cancellation event {event_type} received" }

PHI safety (BR-020):
  Neither the Pub/Sub attributes nor the SignalR payload contain PHI fields
  (patient name, MRN, DOB). Only encounter_id (UUID) and event_type are used.

Design refs:
    ADR-001  — all ADT events (including WORKFLOW_CANCELLED) on adt-events topic
    AIR-001  — MLLP ACK within 200ms; dispatcher is post-commit background task
    FR-006   — A11/A12/A13 triggers halt of agent workflows
    NFR-006  — SignalR latency ≤1 second
    TR-015   — best-effort post-commit; failures logged, not fatal
    US-015   — SC-1 (SignalR), Technical Notes (Pub/Sub WORKFLOW_CANCELLED)
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.services.cancellation_service import CancellationResult

logger = logging.getLogger(__name__)


class CancellationDispatcher:
    """Dispatches post-commit side effects for ADT cancellation events.

    Both Pub/Sub publish and SignalR broadcast run concurrently via
    ``asyncio.gather``.  Individual failures are caught and logged at ERROR
    level; neither failure raises from ``dispatch_post_commit``.

    Args:
        publisher: Object with an async ``publish_raw(ordering_key, attributes, data)``
                   method.  Accepts the ``ADTEventPublisher`` (hl7-listener) or
                   any compatible mock.
        hub:       ``SignalRHub`` instance for broadcasting to care team dashboard.

    Example::

        dispatcher = CancellationDispatcher(publisher=publisher, hub=hub)
        # Call after session.commit() — NEVER inside a transaction:
        await dispatcher.dispatch_post_commit(result)
    """

    def __init__(
        self,
        publisher: object,
        hub: object,
    ) -> None:
        self._publisher = publisher
        self._hub = hub

    async def dispatch_post_commit(
        self,
        result: "CancellationResult",
    ) -> None:
        """Concurrently publish Pub/Sub event and broadcast SignalR notification.

        Designed to be called after ``await session.commit()``.
        Failures in either side effect are logged at ERROR level but do not
        raise — the DB state is already durable.

        Args:
            result: ``CancellationResult`` from ``CancellationService``.
        """
        await asyncio.gather(
            self._publish_workflow_cancelled(result),
            self._broadcast_signalr(result),
            return_exceptions=True,  # absorb exceptions from either coroutine
        )

    # ------------------------------------------------------------------
    # Pub/Sub
    # ------------------------------------------------------------------

    async def _publish_workflow_cancelled(
        self,
        result: "CancellationResult",
    ) -> None:
        """Publish ``WORKFLOW_CANCELLED`` message to ``adt-events`` topic."""
        if self._publisher is None:
            # Sprint 1 stub: publisher not yet wired; skip silently (EP-002)
            logger.debug(
                "cancellation_dispatcher.pubsub_skipped_no_publisher",
                extra={"encounter_id": str(result.encounter_id)},
            )
            return

        iso_now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        attributes = {
            "message_type":  "WORKFLOW_CANCELLED",
            "event_type":    result.event_type,
            "encounter_id":  str(result.encounter_id),
            "iso_timestamp": iso_now,
        }
        body = json.dumps(
            {
                "encounter_id":    str(result.encounter_id),
                "event_type":      result.event_type,
                "tasks_cancelled": result.tasks_cancelled,
                "docs_cancelled":  result.docs_cancelled,
            }
        ).encode("utf-8")

        try:
            await self._publisher.publish_raw(
                ordering_key=str(result.encounter_id),
                attributes=attributes,
                data=body,
            )
            logger.info(
                "cancellation_dispatcher.pubsub_published",
                extra={
                    "encounter_id": str(result.encounter_id),
                    "event_type":   result.event_type,
                    "message_type": "WORKFLOW_CANCELLED",
                },
            )
        except Exception:
            logger.exception(
                "cancellation_dispatcher.pubsub_publish_failed",
                extra={"encounter_id": str(result.encounter_id)},
            )

    # ------------------------------------------------------------------
    # SignalR
    # ------------------------------------------------------------------

    async def _broadcast_signalr(
        self,
        result: "CancellationResult",
    ) -> None:
        """Broadcast ``ENCOUNTER_CANCELLED`` event to care team dashboard."""
        group = f"encounter-{result.encounter_id}"
        payload = {
            "event":        "ENCOUNTER_CANCELLED",
            "encounter_id": str(result.encounter_id),
            "event_type":   result.event_type,
            "reason":       f"Cancellation event {result.event_type} received",
        }
        try:
            await self._hub.send_to_group(
                group=group,
                event="ENCOUNTER_CANCELLED",
                payload=payload,
            )
            logger.info(
                "cancellation_dispatcher.signalr_broadcast",
                extra={
                    "encounter_id": str(result.encounter_id),
                    "group":        group,
                    "event_type":   result.event_type,
                },
            )
        except Exception:
            logger.exception(
                "cancellation_dispatcher.signalr_broadcast_failed",
                extra={"encounter_id": str(result.encounter_id)},
            )
