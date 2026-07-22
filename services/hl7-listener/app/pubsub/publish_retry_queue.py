"""Bounded in-memory retry queue for ADT events that failed Pub/Sub publish.

Holds ``ADTEvent`` objects when the Pub/Sub API is transiently unavailable
after 3 retry attempts by ``ADTEventPublisher``.  A background asyncio task
periodically re-attempts publishing queued events.

Queue behaviour:
  - Maximum capacity: 200 events (``maxlen`` on the underlying deque).
  - When full, the **oldest** entry is silently evicted (it is already
    triggering alerts; the newest event takes priority for ordering).
  - Background flush interval: 30 seconds.
  - On Cloud Run SIGTERM, ``stop()`` signals the flush loop to exit cleanly
    and logs any remaining unprocessed entries (TR-017).

Alerting:
  - Structured log ``pubsub_retry_queue_enqueued`` emitted on each
    ``enqueue()`` call.  Cloud Monitoring parses this as a counter metric
    ``pubsub_retry_queue_depth`` to trigger a P1 alert (unprocessed ADT
    events affect patient care workflows).

Sprint 1 trade-off:
  - If the Cloud Run instance is terminated while events are in this queue,
    those events are lost.  This is acceptable for Sprint 1; Phase 2 will
    persist retry events to the Pub/Sub DLQ topic (TR-015).

Design refs:
    SC-3     — retry queue after all publish retries exhausted
    TR-015   — dead-letter / zero message loss policy
    TR-017   — graceful shutdown: drain retry queue on SIGTERM
    ADR-001  — event-driven architecture: all ADT events must reach Pub/Sub
"""
from __future__ import annotations

import asyncio
import datetime
import logging
from collections import deque
from typing import Awaitable, Callable, NamedTuple, TYPE_CHECKING

if TYPE_CHECKING:
    from app.parser.models import ADTEvent

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL_SECONDS: float = 30.0
_MAX_QUEUE_SIZE: int = 200


# ---------------------------------------------------------------------------
# Queue entry type
# ---------------------------------------------------------------------------


class _QueueEntry(NamedTuple):
    """Immutable container for a queued ADT event pending Pub/Sub publish."""

    event: "ADTEvent"
    enqueued_at: datetime.datetime
    failure_count: int


# ---------------------------------------------------------------------------
# PublishRetryQueue
# ---------------------------------------------------------------------------


class PublishRetryQueue:
    """Bounded in-memory retry queue for failed Pub/Sub ADT event publishes.

    Args:
        publish_fn: Async callable ``(ADTEvent) -> None`` used to re-publish
            queued events.  Typically ``ADTEventPublisher.publish`` — injected
            to break the circular import between publisher and queue.
        flush_interval: Seconds between background flush attempts.
            Default ``_FLUSH_INTERVAL_SECONDS`` (30 s).

    Example::

        retry_queue = PublishRetryQueue(publish_fn=publisher.publish)
        await retry_queue.start()          # begins background flush task

        # In publisher, after all retries exhausted:
        await retry_queue.enqueue(event)

        # On shutdown:
        await retry_queue.stop()
    """

    def __init__(
        self,
        publish_fn: Callable[["ADTEvent"], Awaitable[None]],
        flush_interval: float = _FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._publish_fn = publish_fn
        self._flush_interval = flush_interval
        self._queue: deque[_QueueEntry] = deque(maxlen=_MAX_QUEUE_SIZE)
        self._stop_event: asyncio.Event = asyncio.Event()
        self._flush_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background flush task.

        Must be called once during application startup before the first
        MLLP connection is accepted.
        """
        self._stop_event.clear()
        self._flush_task = asyncio.create_task(
            self._flush_loop(), name="pubsub_retry_queue_flush"
        )
        logger.info("publish_retry_queue_started")

    async def stop(self) -> None:
        """Signal the background flush task to exit and await its completion.

        Call during SIGTERM handling (TR-017).  Logs any events still in the
        queue that will be lost on instance termination (Sprint 1 trade-off).
        """
        self._stop_event.set()
        if self._flush_task is not None:
            try:
                await asyncio.wait_for(self._flush_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "pubsub_retry_queue_flush_task_timeout",
                    extra={"timeout_seconds": 10.0},
                )

        remaining = len(self._queue)
        if remaining:
            logger.warning(
                "publish_retry_queue_shutdown_with_pending",
                extra={"remaining_events": remaining},
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, event: "ADTEvent") -> None:
        """Add ``event`` to the retry queue.

        Structured log ``pubsub_retry_queue_enqueued`` is emitted so Cloud
        Monitoring can track queue depth for alerting.

        Args:
            event: ``ADTEvent`` that failed all Pub/Sub publish retries.
        """
        entry = _QueueEntry(
            event=event,
            enqueued_at=datetime.datetime.now(tz=datetime.timezone.utc),
            failure_count=1,
        )
        self._queue.append(entry)
        logger.error(
            "pubsub_retry_queue_enqueued",
            extra={
                "encounter_id": str(event.encounter_id),
                "event_type": event.event_type.value,
                "queue_depth": len(self._queue),
            },
        )

    def depth(self) -> int:
        """Return the number of events currently in the retry queue."""
        return len(self._queue)

    # ------------------------------------------------------------------
    # Background flush loop
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Periodically drain the retry queue by re-publishing events.

        Runs until ``stop()`` is called.  Each flush cycle attempts to
        publish every queued event; successfully published events are
        removed.  Failed events remain in the queue for the next cycle.
        """
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._flush_interval,
                )
                # Stop event fired — do one final flush then exit
                if self._queue:
                    await self._flush_once()
                return
            except asyncio.TimeoutError:
                pass  # Normal path — interval elapsed; proceed to flush

            if self._queue:
                await self._flush_once()

    async def _flush_once(self) -> None:
        """Attempt to publish all currently queued events.

        Events that publish successfully are discarded.  Events that fail are
        retained in the queue for the next flush cycle (re-inserted at the
        front to preserve FIFO ordering).
        """
        pending = list(self._queue)
        self._queue.clear()
        remaining: list[_QueueEntry] = []

        for entry in pending:
            try:
                await self._publish_fn(entry.event)
                logger.info(
                    "pubsub_retry_queue_flushed",
                    extra={
                        "encounter_id": str(entry.event.encounter_id),
                        "event_type": entry.event.event_type.value,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "pubsub_retry_queue_flush_failed",
                    extra={
                        "encounter_id": str(entry.event.encounter_id),
                        "error": str(exc),
                        "failure_count": entry.failure_count + 1,
                    },
                )
                remaining.append(
                    entry._replace(failure_count=entry.failure_count + 1)
                )

        # Re-enqueue failed entries at the front to preserve FIFO order
        for entry in reversed(remaining):
            self._queue.appendleft(entry)
