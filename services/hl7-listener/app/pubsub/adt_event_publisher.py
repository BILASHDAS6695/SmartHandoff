"""Pub/Sub publisher for ADT domain events.

Publishes each ``ADTEvent`` to the GCP Pub/Sub ``adt-events`` topic with:
  - Ordering key = ``encounter_id`` (string, ≤1 024 bytes)
  - Message body = UTF-8 JSON of the full ``ADTEvent`` Pydantic model
  - Message attributes:
      event_type        — e.g. "ADMIT", "TRANSFER", "DISCHARGE"
      encounter_id      — string matching the ordering key
      patient_mrn_hash  — SHA-256 hex digest of MRN (NOT the MRN itself)
      iso_timestamp     — ISO-8601 UTC datetime of the ADT event

Retry policy (SC-3):
  3 attempts; delays 1 s → 2 s → 4 s (exponential backoff, base=2).
  Uses ``asyncio.sleep`` between retries so the event loop is not blocked.
  After all retries are exhausted, the event is written to
  ``PublishRetryQueue`` and a ``pubsub_publish_failures_total`` Prometheus
  counter is incremented.

PHI safety (BR-020 / AIR-021):
  MRN is never included in Pub/Sub message attributes. ``patient_mrn_hash``
  is a one-way SHA-256 hash used for operational correlation only — it
  cannot be reversed to retrieve the original MRN.
  The message body (``ADTEvent`` JSON) contains PHI fields as they appear in
  the model — Pub/Sub treats the body as opaque bytes.

Environment variables:
  PUBSUB_PROJECT_ID  — GCP project ID owning the Pub/Sub topic
  PUBSUB_TOPIC_ID    — Topic ID (typically ``adt-events``)

Design refs:
    ADR-001  — all ADT events published to Pub/Sub before any processing
    TR-005   — throughput ≥5,000 events/day; async-native publisher
    TR-015   — retry / DLQ; zero message loss
    BR-020   — no PHI in message attributes
    AIR-021  — minimum-necessary PHI in any downstream system input
    US-014   — SC-1 to SC-4, DoD
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from google.cloud import pubsub_v1
from prometheus_client import Counter

if TYPE_CHECKING:
    from app.parser.models import ADTEvent
    from app.pubsub.publish_retry_queue import PublishRetryQueue

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)  # seconds; 3 attempts

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

PUBSUB_PUBLISH_FAILURES = Counter(
    "pubsub_publish_failures_total",
    "Total number of ADT events that failed all Pub/Sub publish retries",
    ["event_type"],
)

# ---------------------------------------------------------------------------
# ADTEventPublisher
# ---------------------------------------------------------------------------


class ADTEventPublisher:
    """Async-capable Pub/Sub publisher for ADT domain events.

    Args:
        retry_queue: ``PublishRetryQueue`` instance that receives events when
            all Pub/Sub retries are exhausted.
        project_id: GCP project ID. Defaults to ``PUBSUB_PROJECT_ID`` env var.
        topic_id: Pub/Sub topic ID. Defaults to ``PUBSUB_TOPIC_ID`` env var.
        executor: ``ThreadPoolExecutor`` for offloading the synchronous
            Pub/Sub SDK call.  A default 4-thread executor is created if
            not supplied.

    Example::

        publisher = ADTEventPublisher(retry_queue=retry_queue)
        await publisher.publish(adt_event)
    """

    def __init__(
        self,
        retry_queue: "PublishRetryQueue",
        project_id: str | None = None,
        topic_id: str | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._project_id = project_id or os.environ["PUBSUB_PROJECT_ID"]
        self._topic_id = topic_id or os.environ["PUBSUB_TOPIC_ID"]
        self._topic_path = (
            f"projects/{self._project_id}/topics/{self._topic_id}"
        )
        self._retry_queue = retry_queue
        self._executor = executor or ThreadPoolExecutor(max_workers=4)

        # PublisherOptions(enable_message_ordering=True) is REQUIRED for
        # ordering keys to be honoured by the GCP backend.
        self._client = pubsub_v1.PublisherClient(
            publisher_options=pubsub_v1.types.PublisherOptions(
                enable_message_ordering=True
            )
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish(self, event: "ADTEvent") -> None:
        """Publish ``event`` to the Pub/Sub ``adt-events`` topic.

        Serialises ``event`` to JSON, sets the encounter ordering key and
        required attributes, then attempts publication with up to 3 retries.
        On complete retry exhaustion, delegates to ``PublishRetryQueue`` and
        increments ``pubsub_publish_failures_total``.

        Args:
            event: Parsed and persisted ``ADTEvent`` domain object.

        Raises:
            Nothing — failures are handled internally via retry + queue.
        """
        message_body: bytes = event.model_dump_json().encode("utf-8")
        ordering_key: str = str(event.encounter_id)
        attributes: dict[str, str] = _build_attributes(event)

        for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
            try:
                await self._publish_once(message_body, ordering_key, attributes)
                logger.info(
                    "pubsub_publish_success",
                    extra={
                        "encounter_id": str(event.encounter_id),
                        "event_type": event.event_type.value,
                        "attempt": attempt,
                    },
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "pubsub_publish_retry",
                    extra={
                        "encounter_id": str(event.encounter_id),
                        "event_type": event.event_type.value,
                        "attempt": attempt,
                        "error": str(exc),
                        "next_delay_seconds": delay if attempt < len(_RETRY_DELAYS) else None,
                    },
                )
                if attempt < len(_RETRY_DELAYS):
                    await asyncio.sleep(delay)

        # All retries exhausted — delegate to local retry queue
        logger.error(
            "pubsub_publish_failed_all_retries",
            extra={
                "encounter_id": str(event.encounter_id),
                "event_type": event.event_type.value,
            },
        )
        PUBSUB_PUBLISH_FAILURES.labels(event_type=event.event_type.value).inc()
        await self._retry_queue.enqueue(event)

    async def publish_raw(
        self,
        ordering_key: str,
        attributes: dict[str, str],
        data: bytes,
    ) -> None:
        """Publish raw bytes to the Pub/Sub topic.

        Unlike ``publish()``, this method accepts pre-serialised message bytes
        and caller-supplied attributes.  Used by ``CancellationDispatcher`` to
        publish ``WORKFLOW_CANCELLED`` messages without an ``ADTEvent`` object.

        Failures are propagated to the caller — apply best-effort handling
        (catch + log) at the call site.

        Args:
            ordering_key: Pub/Sub ordering key string (e.g. ``str(encounter_id)``).
            attributes:   Message attribute mapping (all values must be ``str``).
            data:         UTF-8 encoded message body bytes.

        Raises:
            Exception: Any Pub/Sub client exception is re-raised so the caller
                can decide whether to retry or log and swallow.
        """
        await self._publish_once(
            message_body=data,
            ordering_key=ordering_key,
            attributes=attributes,
        )

    async def close(self) -> None:
        """Gracefully shut down the Pub/Sub client and thread-pool executor.

        Call during Cloud Run SIGTERM handling (TR-017).
        """
        self._client.stop()
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _publish_once(
        self,
        message_body: bytes,
        ordering_key: str,
        attributes: dict[str, str],
    ) -> None:
        """Dispatch a single publish call via the thread-pool executor.

        ``PublisherClient.publish().result()`` is synchronous and blocks the
        calling thread.  ``run_in_executor`` offloads it so the asyncio event
        loop remains responsive.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor,
            self._sync_publish,
            message_body,
            ordering_key,
            attributes,
        )

    def _sync_publish(
        self,
        message_body: bytes,
        ordering_key: str,
        attributes: dict[str, str],
    ) -> None:
        """Synchronous publish call executed in the thread-pool.

        Raises ``GoogleAPICallError`` (or any SDK exception) on failure so
        the async retry loop can catch and delay.
        """
        future = self._client.publish(
            self._topic_path,
            data=message_body,
            ordering_key=ordering_key,
            **attributes,
        )
        future.result()  # blocks thread; raises on failure


# ---------------------------------------------------------------------------
# Attribute builder (module-level pure function — easy to unit test)
# ---------------------------------------------------------------------------


def _build_attributes(event: "ADTEvent") -> dict[str, str]:
    """Build Pub/Sub message attributes from an ``ADTEvent``.

    PHI rule (BR-020):
      ``patient_mrn_hash`` is SHA-256 hex of the MRN string.
      The raw MRN must NEVER appear in attributes.

    Returns:
        Mapping with keys: event_type, encounter_id, patient_mrn_hash,
        iso_timestamp.
    """
    mrn_bytes = str(event.patient_mrn).encode("utf-8")
    mrn_hash = hashlib.sha256(mrn_bytes).hexdigest()

    return {
        "event_type": event.event_type.value,
        "encounter_id": str(event.encounter_id),
        "patient_mrn_hash": mrn_hash,
        "iso_timestamp": event.event_time.isoformat(),
    }
