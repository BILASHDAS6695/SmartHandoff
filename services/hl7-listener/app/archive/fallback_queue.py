"""Bounded in-memory fallback queue for raw HL7 messages.

Holds raw HL7 messages that could not be archived to GCS after 3 retry
attempts.  A background asyncio task periodically retries flushing queued
messages to GCS.

Queue behaviour:
  - Maximum capacity: 500 messages (``maxlen`` on the underlying deque).
  - When full, the **oldest** entry is silently evicted (already triggering
    alerts via Cloud Monitoring — the fresh message takes priority).
  - Background flush interval: 30 seconds.
  - On Cloud Run SIGTERM, ``stop()`` signals the flush loop to exit cleanly
    and logs remaining unprocessed entries.

Alerting:
  - A structured log ``hl7_fallback_queue_enqueued`` is emitted on each
    ``enqueue()`` call.  Cloud Monitoring parses this as a counter metric
    (``hl7_fallback_queue_depth``) to trigger a P2 alert.

Sprint 1 trade-off:
  - If the Cloud Run instance is terminated while messages are in the queue,
    those messages are lost.  This is acceptable for Sprint 1 per the
    Technical Notes; Phase 2 will persist the fallback queue to Pub/Sub DLQ.

Design refs:
    SC-4     — fallback queue after GCS retry exhaustion
    TR-017   — graceful shutdown: drain fallback queue on SIGTERM
    TR-015   — dead-letter alerting
    US-013   — Technical Notes: deque-based queue, no Redis in Sprint 1
"""
from __future__ import annotations

import asyncio
import datetime
import logging
from collections import deque
from typing import NamedTuple, TYPE_CHECKING

if TYPE_CHECKING:
    from app.archive.gcs_archiver import GCSArchiver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Queue entry type
# ---------------------------------------------------------------------------


class _QueueEntry(NamedTuple):
    """Immutable container for a queued HL7 message pending GCS archival."""

    raw_hl7: str
    msg_control_id: str
    arrived_at: datetime.datetime


# ---------------------------------------------------------------------------
# FallbackQueue
# ---------------------------------------------------------------------------

_MAX_QUEUE_SIZE = 500
_FLUSH_INTERVAL_SECONDS = 30.0


class FallbackQueue:
    """Bounded in-memory queue with asynchronous background GCS flush.

    Usage::

        queue = FallbackQueue(archiver=gcs_archiver)
        await queue.start()         # starts background flush task

        # Enqueue a failed message (called by GCSArchiver on retry exhaustion)
        await queue.enqueue(raw_hl7, msg_control_id, arrived_at)

        # On SIGTERM:
        await queue.stop()          # graceful shutdown, logs remaining entries

    Args:
        archiver: ``GCSArchiver`` instance used for flush retries.
                  Injected so the queue is not tightly coupled to the archiver.
    """

    def __init__(self, archiver: "GCSArchiver") -> None:
        self._archiver = archiver
        self._queue: deque[_QueueEntry] = deque(maxlen=_MAX_QUEUE_SIZE)
        self._stop_event = asyncio.Event()
        self._flush_task: asyncio.Task | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background flush task.  Call once at service startup."""
        self._stop_event.clear()
        self._flush_task = asyncio.create_task(
            self._flush_loop(), name="fallback-queue-flush"
        )
        logger.info(
            "FallbackQueue flush task started (interval=%ss)", _FLUSH_INTERVAL_SECONDS
        )

    async def stop(self) -> None:
        """Signal the flush loop to stop and wait for it to exit.

        Logs any remaining unprocessed entries for operational visibility.
        """
        self._stop_event.set()
        if self._flush_task is not None:
            try:
                await asyncio.wait_for(self._flush_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "FallbackQueue flush task did not finish within 10 s on shutdown"
                )
        remaining = len(self._queue)
        if remaining > 0:
            logger.error(
                "FallbackQueue shutting down with %d unprocessed entries — messages may be lost",
                remaining,
                extra={
                    "event": "hl7_fallback_queue_shutdown_loss",
                    "remaining_count": remaining,
                },
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        raw_hl7: str,
        msg_control_id: str,
        arrived_at: datetime.datetime,
    ) -> None:
        """Add a failed message to the fallback queue.

        Thread-safe (deque append is atomic in CPython).  Emits a structured
        alert log for Cloud Monitoring.

        Args:
            raw_hl7:        Raw HL7 message text.
            msg_control_id: MSH-10 message control ID.
            arrived_at:     UTC datetime when the message was originally received.
        """
        entry = _QueueEntry(
            raw_hl7=raw_hl7,
            msg_control_id=msg_control_id,
            arrived_at=arrived_at,
        )
        was_full = len(self._queue) == _MAX_QUEUE_SIZE
        self._queue.append(entry)  # deque with maxlen evicts oldest if full
        logger.error(
            "hl7_fallback_queue_enqueued",
            extra={
                "event": "hl7_fallback_queue_enqueued",
                "message_id": msg_control_id,
                "queue_depth": len(self._queue),
                "evicted_oldest": was_full,
            },
        )

    @property
    def depth(self) -> int:
        """Current number of messages waiting in the fallback queue."""
        return len(self._queue)

    # ------------------------------------------------------------------
    # Background flush loop
    # ------------------------------------------------------------------

    async def _flush_loop(self) -> None:
        """Continuously retry flushing queued messages to GCS every 30 seconds."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=_FLUSH_INTERVAL_SECONDS,
                )
                # Stop event fired — do one final flush then exit
                await self._flush_all()
                return
            except asyncio.TimeoutError:
                # Interval elapsed — attempt a flush cycle
                pass
            if self._queue:
                await self._flush_all()

    async def _flush_all(self) -> None:
        """Attempt to upload all queued messages to GCS.

        Successfully uploaded entries are removed from the deque.
        Entries that still fail remain in the queue for the next cycle.
        """
        if not self._queue:
            return
        logger.info("FallbackQueue flush cycle: %d messages pending", len(self._queue))
        # Snapshot current entries — new entries added during flush are NOT processed this cycle
        entries = list(self._queue)
        flushed = 0
        for entry in entries:
            success = await self._archiver.archive(
                raw_hl7=entry.raw_hl7,
                msg_control_id=entry.msg_control_id,
                arrived_at=entry.arrived_at,
            )
            if success:
                try:
                    self._queue.remove(entry)
                    flushed += 1
                except ValueError:
                    pass  # entry was already evicted due to queue overflow
        if flushed:
            logger.info(
                "FallbackQueue flushed %d/%d messages to GCS", flushed, len(entries)
            )
