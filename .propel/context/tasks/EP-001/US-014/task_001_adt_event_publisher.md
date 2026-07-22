---
id: TASK-001
title: "Create `hl7-listener/app/pubsub/adt_event_publisher.py` — ADT Event Publisher (Ordering Key, Message Attributes, Exponential-Backoff Retry)"
user_story: US-014
epic: EP-001
sprint: 1
layer: Backend
estimate: 2.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-012/TASK-001, US-013/TASK-001]
---

# TASK-001: Create `hl7-listener/app/pubsub/adt_event_publisher.py` — ADT Event Publisher (Ordering Key, Message Attributes, Exponential-Backoff Retry)

> **Story:** US-014 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-014 mandates (ADR-001, TR-005):

> *"All ADT events published to GCP Pub/Sub `adt-events` topic; each agent type subscribes on a dedicated subscription with its own dead-letter queue"*

`ADTEventPublisher` is the single module responsible for converting a parsed `ADTEvent` domain object into a Pub/Sub message and dispatching it to the `adt-events` topic. It must:

- Set `encounter_id` as the ordering key on every `PublishRequest` (SC-1, SC-2)
- Include message attributes: `event_type`, `encounter_id`, `patient_mrn_hash` (SHA-256, not plaintext MRN), `iso_timestamp` (SC-4)
- Serialise the full `ADTEvent` as UTF-8-encoded JSON for the message body
- Retry up to 3 times with exponential backoff (1 s / 2 s / 4 s) on transient API errors (SC-3)
- Delegate to `PublishRetryQueue` (TASK-002) when all retries are exhausted, and fire a `pubsub_publish_failures_total` Prometheus counter increment

Design decisions encoded in this module:

| Decision | Rationale |
|----------|-----------|
| `PublisherOptions(enable_message_ordering=True)` | Required by GCP SDK for ordering key support; without this the ordering key is ignored |
| `encounter_id` as ordering key (not `patient_id`) | A patient can have multiple concurrent encounters; per-encounter FIFO is what agents need |
| SHA-256 of MRN in attributes (not MRN) | BR-020 / ADR-007: PHI must not appear in Pub/Sub attributes — attributes are logged by GCP without field-level encryption |
| Full `ADTEvent` JSON in message body | Body is treated as an opaque byte payload by Pub/Sub — field-level encryption already applied to PHI fields via `ADTEvent.model_dump(mode='json')` |
| `run_in_executor` for sync SDK | `google-cloud-pubsub` `future.result()` blocks; offloaded to thread-pool executor so the asyncio pipeline is never blocked |
| Prometheus `pubsub_publish_failures_total` counter | TR-005: operational metric for SLA tracking; exportable to Cloud Monitoring via OpenTelemetry |

Design refs: ADR-001, TR-005, TR-015, AIR-021, BR-020, US-014 DoD, SC-1–SC-4.

---

## Acceptance Criteria Addressed

| US-014 AC | Requirement |
|---|---|
| **Scenario 1** | Message appears in `adt-events` topic within 1 second; ordering key = `encounter_id`; body = full `ADTEvent` JSON |
| **Scenario 2** | `encounter_id` ordering key ensures FIFO delivery for same encounter |
| **Scenario 3** | Transient error → 3 retries with exponential backoff; all retries fail → `PublishRetryQueue.enqueue()` called; `pubsub_publish_failures_total` incremented |
| **Scenario 4** | Attributes include `event_type`, `encounter_id`, `patient_mrn_hash` (SHA-256), `iso_timestamp` |
| **DoD** | `ADTEventPublisher` wraps `PublisherClient` with ordering key; `ADTEvent` serialises to JSON; all 4 required attributes present |

---

## Implementation Steps

### 1. Scaffold the `pubsub` sub-package

```
hl7-listener/
└── app/
    └── pubsub/
        ├── __init__.py
        ├── adt_event_publisher.py   ← THIS TASK
        └── publish_retry_queue.py   ← TASK-002
```

```bash
mkdir -p hl7-listener/app/pubsub
touch hl7-listener/app/pubsub/__init__.py
```

### 2. Create `hl7-listener/app/pubsub/__init__.py`

```python
"""Pub/Sub sub-package — ADT event publishing and retry queue.

Exports:
  ADTEventPublisher   — async-capable Pub/Sub publisher with ordering key,
                        attributes, retry, and fallback delegation
  PublishRetryQueue   — bounded in-memory queue with background flush for
                        events that failed all publish retries

Design refs:
    ADR-001  — event-driven architecture: all ADT events to Pub/Sub adt-events topic
    TR-005   — ADT event ingestion throughput ≥5,000 events/day
    TR-015   — DLQ / retry: zero message loss policy
    BR-020   — no PHI in Pub/Sub message attributes
"""
from app.pubsub.adt_event_publisher import ADTEventPublisher
from app.pubsub.publish_retry_queue import PublishRetryQueue

__all__ = ["ADTEventPublisher", "PublishRetryQueue"]
```

### 3. Create `hl7-listener/app/pubsub/adt_event_publisher.py`

```python
"""Pub/Sub publisher for ADT domain events.

Publishes each ``ADTEvent`` to the GCP Pub/Sub ``adt-events`` topic with:
  - Ordering key = ``encounter_id`` (UUID string, ≤1 024 bytes)
  - Message body = UTF-8 JSON of the full ``ADTEvent`` Pydantic model
  - Message attributes:
      event_type        — e.g. "ADMIT", "TRANSFER", "DISCHARGE"
      encounter_id      — UUID string matching the ordering key
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
  The message body (``ADTEvent`` JSON) contains encrypted PHI fields as
  ciphertext — Pub/Sub treats the body as opaque bytes; it is never logged
  by GCP in plaintext.

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
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import pubsub_v1
from prometheus_client import Counter

if TYPE_CHECKING:
    from app.models.adt_event import ADTEvent
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
            Pub/Sub SDK call.  A default single-thread executor is created if
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
            except (GoogleAPICallError, Exception) as exc:  # noqa: BLE001
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
      ``patient_mrn_hash`` is SHA-256 hex of the *decrypted* MRN string.
      The raw MRN must NEVER appear in attributes.

    Returns:
        Mapping with keys: event_type, encounter_id, patient_mrn_hash,
        iso_timestamp.
    """
    mrn_bytes = str(event.patient.mrn).encode("utf-8")
    mrn_hash = hashlib.sha256(mrn_bytes).hexdigest()

    return {
        "event_type": event.event_type.value,
        "encounter_id": str(event.encounter_id),
        "patient_mrn_hash": mrn_hash,
        "iso_timestamp": event.event_timestamp.isoformat(),
    }
```

---

## Validation

Run from `hl7-listener/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/pubsub/adt_event_publisher.py').read_text())
print('Syntax check: PASSED')
"

# 2. Import check (requires google-cloud-pubsub, prometheus_client installed)
python -c "
from app.pubsub import ADTEventPublisher
from app.pubsub.adt_event_publisher import _build_attributes, _RETRY_DELAYS
print('Import check: PASSED')
"

# 3. Verify retry delays
python -c "
from app.pubsub.adt_event_publisher import _RETRY_DELAYS
assert _RETRY_DELAYS == (1.0, 2.0, 4.0), f'Expected (1.0, 2.0, 4.0), got {_RETRY_DELAYS}'
print(f'Retry delays: {_RETRY_DELAYS} — PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `hl7-listener/app/pubsub/__init__.py` |
| CREATE | `hl7-listener/app/pubsub/adt_event_publisher.py` |

---

## Definition of Done Checklist

- [ ] `ADTEventPublisher.__init__` passes `enable_message_ordering=True` to `PublisherOptions`
- [ ] `publish()` sets ordering key = `event.encounter_id` (string)
- [ ] `publish()` calls `_build_attributes()` and passes all 4 attributes to `_sync_publish`
- [ ] `_build_attributes()` produces SHA-256 hex hash of MRN, not raw MRN
- [ ] Retry loop attempts exactly 3 times with delays 1 s / 2 s / 4 s
- [ ] On exhaustion: `PublishRetryQueue.enqueue()` called AND `PUBSUB_PUBLISH_FAILURES` incremented
- [ ] `_sync_publish()` uses `run_in_executor` — never blocks the event loop
- [ ] `close()` calls `client.stop()` for graceful shutdown (TR-017)
- [ ] No PHI in structured log fields (only `encounter_id` UUID and `event_type`)
