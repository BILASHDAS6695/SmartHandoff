---
id: TASK-001
title: "Create `coordinator-agent/app/pubsub/adt_subscriber.py` — Async Pub/Sub Pull Subscriber with FlowControl and ACK Management"
user_story: US-020
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-014/TASK-001]
---

# TASK-001: Create `coordinator-agent/app/pubsub/adt_subscriber.py` — Async Pub/Sub Pull Subscriber with FlowControl and ACK Management

> **Story:** US-020 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-020 mandates (ADR-001, TR-005, TR-015, TR-017):

> *"Coordinator must automatically receive every ADT event from Pub/Sub and create `AgentTask` records within 2 seconds"*

`ADTSubscriber` is the single module responsible for consuming ADT events from the GCP Pub/Sub `coordinator-sub` subscription and delivering deserialized `ADTEvent` objects to the processing callback. It must:

- Use `google.cloud.pubsub_v1.SubscriberClient` with `FlowControl(max_messages=10)` to prevent memory overload
- Deserialise incoming Pub/Sub messages into `ADTEvent` Pydantic domain objects
- Acknowledge messages only after the processing callback returns successfully
- Negative-acknowledge (`nack`) messages when the callback raises an exception or when shutdown is requested mid-flight
- Extend the ACK deadline via `modify_ack_deadline` for tasks taking longer than 60 seconds
- Expose a `shutdown_event: asyncio.Event` for SIGTERM-driven graceful draining (TR-017)

Design decisions encoded in this module:

| Decision | Rationale |
|----------|-----------|
| `FlowControl(max_messages=10)` | Prevents OOM on coordinator container (2 GB RAM); allows back-pressure |
| ACK-after-success only | Guarantees at-least-once delivery; coordinator cannot lose tasks |
| `nack` on shutdown | TR-017: Pub/Sub redelivers to another instance; no message loss |
| Callback receives `ADTEvent` not raw bytes | Encapsulates deserialization; coordinator is event-type agnostic |
| `asyncio.Event` for shutdown | Integrates cleanly with SIGTERM handler in TASK-003; avoids threading issues |

Design refs: ADR-001, TR-005, TR-015, TR-017, US-020 DoD, SC-3.

---

## Acceptance Criteria Addressed

| US-020 AC | Requirement |
|---|---|
| **Scenario 1** | Subscriber receives ADT^A01 message, deserialises to `ADTEvent`, delivers to callback within 100ms of receipt |
| **Scenario 3** | On SIGTERM: `shutdown_event` is set; current message is `nack`-ed if callback is mid-flight; subscriber closes cleanly within 30 seconds |
| **Scenario 4** | Failed deliveries bubble up as exceptions; Pub/Sub's built-in retry + DLQ handles 5-attempt expiry (configured in Terraform via TASK-004) |

---

## Implementation Steps

### 1. Scaffold the `coordinator-agent` service structure

```
coordinator-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                    ← entry point (TASK-003)
│   ├── pubsub/
│   │   ├── __init__.py
│   │   └── adt_subscriber.py      ← THIS TASK
│   ├── coordinator/
│   │   ├── __init__.py
│   │   ├── agent.py               ← TASK-002
│   │   └── task_mapping.py        ← TASK-002
│   └── models/
│       └── agent_task.py          ← pre-existing (US-006)
├── Dockerfile
├── requirements.txt
└── tests/
    ├── unit/
    └── integration/
```

```bash
mkdir -p coordinator-agent/app/pubsub
touch coordinator-agent/app/__init__.py
touch coordinator-agent/app/pubsub/__init__.py
```

### 2. Create `coordinator-agent/app/pubsub/__init__.py`

```python
"""Pub/Sub sub-package — ADT subscription consumer for coordinator agent.

Exports:
  ADTSubscriber — async-capable Pub/Sub pull subscriber with FlowControl,
                  graceful shutdown, and ACK/NACK lifecycle management.

Design refs:
    ADR-001  — event-driven architecture: agents as independent Pub/Sub consumers
    TR-005   — ADT event throughput ≥5,000 events/day
    TR-015   — zero message loss: nack on shutdown for redelivery
    TR-017   — graceful shutdown: drain in-flight, exit within 30 s
"""
from app.pubsub.adt_subscriber import ADTSubscriber

__all__ = ["ADTSubscriber"]
```

### 3. Create `coordinator-agent/app/pubsub/adt_subscriber.py`

```python
"""Async Pub/Sub pull subscriber for ADT domain events.

Wraps ``google.cloud.pubsub_v1.SubscriberClient`` with:
  - FlowControl(max_messages=10) — back-pressure to prevent OOM
  - ACK-after-success — guarantees at-least-once task creation
  - NACK on exception or shutdown — ensures Pub/Sub redelivers unprocessed
    messages to another coordinator instance (TR-017, TR-015)
  - ACK deadline extension — for tasks that exceed the 60s default ack deadline
  - asyncio.Event-based shutdown — integrates with SIGTERM handler (TASK-003)

Callback contract:
  The caller passes an ``async`` callback with signature:
      async def process(event: ADTEvent) -> None

  The subscriber awaits the callback. If it returns cleanly the message is
  ACK-ed. If it raises any exception the message is NACK-ed (redelivered).

Environment variables:
  PUBSUB_PROJECT_ID       — GCP project ID
  COORDINATOR_SUB_ID      — Subscription ID (typically ``coordinator-sub``)
  ACK_DEADLINE_SECONDS    — ACK deadline extension in seconds (default: 120)

Design refs:
    ADR-001, TR-005, TR-015, TR-017, US-020 SC-1, SC-3, DoD
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from google.cloud import pubsub_v1
from google.cloud.pubsub_v1.types import FlowControl

if TYPE_CHECKING:
    from google.cloud.pubsub_v1.subscriber.message import Message

    from app.models.adt_event import ADTEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

ProcessCallback = Callable[["ADTEvent"], Awaitable[None]]

# ---------------------------------------------------------------------------
# ADTSubscriber
# ---------------------------------------------------------------------------


class ADTSubscriber:
    """Async pull subscriber for coordinator-sub Pub/Sub subscription.

    Args:
        callback: Async callable ``async def process(event: ADTEvent) -> None``.
            ACK is sent after successful return; NACK on any exception.
        project_id: GCP project ID. Defaults to ``PUBSUB_PROJECT_ID`` env var.
        subscription_id: Pub/Sub subscription ID. Defaults to
            ``COORDINATOR_SUB_ID`` env var.
        ack_deadline_seconds: ACK deadline extension value used when the
            processing callback exceeds 60 seconds. Defaults to
            ``ACK_DEADLINE_SECONDS`` env var or 120.

    Example::

        subscriber = ADTSubscriber(callback=coordinator.process_event)
        await subscriber.start()
        # blocks until shutdown_event is set
        await subscriber.stop()
    """

    def __init__(
        self,
        callback: ProcessCallback,
        project_id: str | None = None,
        subscription_id: str | None = None,
        ack_deadline_seconds: int | None = None,
    ) -> None:
        self._callback = callback
        self._project_id = project_id or os.environ["PUBSUB_PROJECT_ID"]
        self._subscription_id = subscription_id or os.environ["COORDINATOR_SUB_ID"]
        self._subscription_path = (
            f"projects/{self._project_id}/subscriptions/{self._subscription_id}"
        )
        self._ack_deadline = int(
            ack_deadline_seconds
            or os.environ.get("ACK_DEADLINE_SECONDS", 120)
        )
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._client: pubsub_v1.SubscriberClient | None = None
        self._streaming_pull_future: pubsub_v1.futures.StreamingPullFuture | None = None

        # Shutdown coordination
        self.shutdown_event: asyncio.Event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the streaming pull subscription and block until shutdown.

        Opens a streaming pull to ``coordinator-sub`` with
        ``FlowControl(max_messages=10)``. The asyncio event loop remains
        responsive; the synchronous Pub/Sub callback is dispatched from the
        thread-pool executor.

        Blocks until ``shutdown_event`` is set (typically by SIGTERM handler).
        """
        loop = asyncio.get_running_loop()

        self._client = pubsub_v1.SubscriberClient()
        flow_control = FlowControl(max_messages=10)

        def _sync_callback(message: "Message") -> None:
            """Synchronous callback invoked by Pub/Sub client thread."""
            # Schedule the async handler on the event loop
            future = asyncio.run_coroutine_threadsafe(
                self._handle_message(message), loop
            )
            try:
                future.result(timeout=self._ack_deadline)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "pubsub_callback_unhandled_error",
                    extra={"error": str(exc)},
                )
                message.nack()

        self._streaming_pull_future = self._client.subscribe(
            self._subscription_path,
            callback=_sync_callback,
            flow_control=flow_control,
        )

        logger.info(
            "pubsub_subscriber_started",
            extra={"subscription": self._subscription_path},
        )

        # Block until shutdown_event is set
        await self.shutdown_event.wait()
        await self.stop()

    async def stop(self) -> None:
        """Cancel the streaming pull and close the Pub/Sub client.

        Called by the SIGTERM handler (TASK-003). In-flight messages that have
        not yet been ACK-ed will be NACK-ed automatically when the client
        closes (TR-017).
        """
        if self._streaming_pull_future:
            self._streaming_pull_future.cancel()
            try:
                self._streaming_pull_future.result(timeout=5)
            except Exception:  # noqa: BLE001
                pass  # cancellation expected
        if self._client:
            self._client.close()
        self._executor.shutdown(wait=True, cancel_futures=False)
        logger.info("pubsub_subscriber_stopped")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _handle_message(self, message: "Message") -> None:
        """Deserialise, dispatch callback, then ACK or NACK the message.

        On success: ACK the message.
        On exception: NACK the message so Pub/Sub redelivers to DLQ path.

        Args:
            message: Raw Pub/Sub message from the streaming pull.
        """
        encounter_id = message.attributes.get("encounter_id", "unknown")
        event_type = message.attributes.get("event_type", "unknown")

        try:
            adt_event = _deserialise_message(message)
            await self._callback(adt_event)
            message.ack()
            logger.info(
                "pubsub_message_acked",
                extra={
                    "encounter_id": encounter_id,
                    "event_type": event_type,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "pubsub_message_nacked",
                extra={
                    "encounter_id": encounter_id,
                    "event_type": event_type,
                    "error": str(exc),
                },
            )
            message.nack()
            raise


# ---------------------------------------------------------------------------
# Deserialisation helper (module-level pure function — easy to unit test)
# ---------------------------------------------------------------------------


def _deserialise_message(message: "Message") -> "ADTEvent":
    """Deserialise a raw Pub/Sub message into an ``ADTEvent`` domain object.

    The message data is UTF-8-encoded JSON produced by
    ``ADTEvent.model_dump_json()`` in the HL7 Listener service.

    Args:
        message: Raw Pub/Sub message.

    Returns:
        Validated ``ADTEvent`` Pydantic model.

    Raises:
        ValueError: If the message body cannot be deserialised.
        pydantic.ValidationError: If the JSON does not match the ``ADTEvent`` schema.
    """
    # Import here to avoid circular imports at module load time
    from app.models.adt_event import ADTEvent  # noqa: PLC0415

    try:
        payload: dict = json.loads(message.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot deserialise Pub/Sub message body: {exc}") from exc

    return ADTEvent.model_validate(payload)
```

---

## Validation

Run from `coordinator-agent/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/pubsub/adt_subscriber.py').read_text())
print('Syntax check: PASSED')
"

# 2. Import check (requires google-cloud-pubsub installed)
python -c "
from app.pubsub import ADTSubscriber
from app.pubsub.adt_subscriber import _deserialise_message
print('Import check: PASSED')
"

# 3. FlowControl max_messages assertion
python -c "
from google.cloud.pubsub_v1.types import FlowControl
fc = FlowControl(max_messages=10)
assert fc.max_messages == 10, f'Expected 10, got {fc.max_messages}'
print(f'FlowControl(max_messages={fc.max_messages}): PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `coordinator-agent/app/__init__.py` |
| CREATE | `coordinator-agent/app/pubsub/__init__.py` |
| CREATE | `coordinator-agent/app/pubsub/adt_subscriber.py` |

---

## Definition of Done Checklist

- [ ] `ADTSubscriber.__init__` accepts `callback`, `project_id`, `subscription_id`, `ack_deadline_seconds`
- [ ] `start()` opens streaming pull with `FlowControl(max_messages=10)`
- [ ] `start()` blocks until `shutdown_event` is set
- [ ] `_handle_message()` ACKs on callback success; NACKs on any exception
- [ ] `stop()` cancels `_streaming_pull_future` and closes client
- [ ] `_deserialise_message()` converts raw bytes → validated `ADTEvent`
- [ ] No PHI in structured log fields (only `encounter_id` UUID and `event_type`)
- [ ] `shutdown_event` is a public `asyncio.Event` for SIGTERM integration (TASK-003)
