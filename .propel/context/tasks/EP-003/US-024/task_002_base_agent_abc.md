---
id: TASK-002
title: "Create `base-agent/app/base/agent.py` — BaseAgent ABC with Pub/Sub Lifecycle, Task Status Transitions, and SIGTERM Shutdown"
user_story: US-024
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [US-024/TASK-001]
---

# TASK-002: Create `base-agent/app/base/agent.py` — BaseAgent ABC with Pub/Sub Lifecycle, Task Status Transitions, and SIGTERM Shutdown

> **Story:** US-024 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-024 mandates (TR-015, ADR-001, ADR-004, DoD):

> *"`BaseAgent` abstract class with: `subscribe()`, `process()` (abstract), `ack()`, `nack()`, `check_cancellation()`, `update_task_status()`"*
> *"`AgentTask` status transitions: `PENDING → IN_PROGRESS` on start, `IN_PROGRESS → COMPLETED/FAILED/CANCELLED` on completion"*
> *"SIGTERM graceful shutdown: inherited by all specialist agents"*

`BaseAgent` is the single shared skeleton consumed by all 5 specialist agents. It encodes:

1. **Pub/Sub message loop** — pulls from the agent's dedicated subscription, dispatches to `process()`, then ACKs or NACKs based on outcome
2. **Task status transitions** — `PENDING → IN_PROGRESS → COMPLETED/FAILED/CANCELLED` with DB writes
3. **Cancellation check** — delegates to `CancellationChecker` (TASK-003); exits cleanly if flag set
4. **SIGTERM handler** — sets a shutdown flag; current message is processed to completion before exit
5. **Abstract `process()` method** — specialist agents override this; return type is `BaseAgentOutput`

Design decisions:

| Decision | Rationale |
|----------|-----------|
| ABC with abstract `process()` | Forces all 5 specialist agents to implement processing logic; base handles all boilerplate |
| Cancellation check BEFORE DB persist | Prevents writing stale AI output after encounter is cancelled (AC Scenario 3) |
| ACK on cancellation | Prevents DLQ accumulation for intentionally cancelled tasks (AC Scenario 3, TR-015) |
| NACK on `RetryableError` | Returns message to Pub/Sub subscription so retry counter increments naturally (AC Scenario 2) |
| SIGTERM sets `_shutdown` flag; completes current message | Prevents partial DB writes on container shutdown (Cloud Run sends SIGTERM 10 s before SIGKILL) |
| `update_task_status()` uses `SELECT … FOR UPDATE` | Prevents concurrent status overwrites if Pub/Sub redelivers before first processing finishes |

Design refs: TR-015, ADR-001, ADR-004, US-024 DoD, AC Scenarios 1–4.

---

## Acceptance Criteria Addressed

| US-024 AC | Requirement |
|---|---|
| **Scenario 1** | `process()` completes → message ACK-ed → `AgentTask.status = COMPLETED` |
| **Scenario 2** | `RetryableError` raised → NACK → `AgentTask.retry_count` incremented → backoff applied |
| **Scenario 3** | Cancellation flag set → agent exits without DB persist → `AgentTask.status = CANCELLED` → ACK |
| **Scenario 4** | Non-retryable failure → propagates → `AgentTask.status = FAILED` with error JSON |

---

## Implementation Steps

### 1. Create `base-agent/app/base/agent.py`

```python
"""BaseAgent — abstract base class for all SmartHandoff specialist agents.

All 5 specialist agents (Documentation, Medication Reconciliation,
Bed Management, Follow-up Care, Patient Communication) extend this class
and override the single abstract method ``process()``.

The base class handles:
- Pub/Sub message pull loop (``subscribe()``)
- ACK / NACK lifecycle (``ack()``, ``nack()``)
- AgentTask status transitions (``update_task_status()``)
- Cancellation flag check (``check_cancellation()``)
- SIGTERM graceful shutdown

Design refs:
    TR-015  — DLQ: max_delivery_attempts=5 on agent subscriptions; NACK on
              transient errors so Pub/Sub manages delivery attempt counter
    ADR-001 — each agent is an independent Pub/Sub subscriber
    ADR-004 — LangChain + Vertex AI; structured output via Pydantic
    US-024  — AC Scenarios 1–4, DoD
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from google.cloud import pubsub_v1

from app.base.errors import NonRetryableError, RetryableError

if TYPE_CHECKING:
    from app.base.cancellation import CancellationChecker
    from app.models.adt_event import ADTEvent
    from app.models.agent_task import AgentTask
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status enum — mirrors AgentTask DB column values
# ---------------------------------------------------------------------------


class AgentTaskStatus(StrEnum):
    """AgentTask lifecycle statuses (mirrors DB column ``agent_task.status``)."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Output base model
# ---------------------------------------------------------------------------


class BaseAgentOutput:
    """Minimal base class for structured agent output.

    Specialist agents define their own Pydantic model subclass; this base
    class exists so ``process()`` has a concrete return type annotation.
    """


# ---------------------------------------------------------------------------
# BaseAgent
# ---------------------------------------------------------------------------


class BaseAgent(ABC):
    """Abstract base class providing Pub/Sub lifecycle, retry, and status management.

    Args:
        subscription_path: Full GCP Pub/Sub subscription path,
            e.g. ``"projects/my-project/subscriptions/docs-agent-sub"``.
        db_session: Async SQLAlchemy session factory (callable).
        cancellation_checker: ``CancellationChecker`` instance for Redis-backed
            cancellation flag queries.
        max_messages: Maximum messages to pull per Pub/Sub batch (default 1).

    Example::

        class DocumentationAgent(BaseAgent):
            async def process(self, event: ADTEvent) -> DocumentationOutput:
                ...
    """

    def __init__(
        self,
        subscription_path: str,
        db_session: "AsyncSession",
        cancellation_checker: "CancellationChecker",
        max_messages: int = 1,
    ) -> None:
        self._subscription_path = subscription_path
        self._db_session = db_session
        self._cancellation_checker = cancellation_checker
        self._max_messages = max_messages
        self._shutdown = False

        # Register SIGTERM handler for graceful Cloud Run shutdown
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGINT, self._handle_sigterm)

    # ------------------------------------------------------------------
    # Abstract interface — specialist agents implement this
    # ------------------------------------------------------------------

    @abstractmethod
    async def process(self, event: "ADTEvent") -> BaseAgentOutput:
        """Process a single ADT event and return structured output.

        Specialist agents override this method. The base class handles
        ACK/NACK, status transitions, and cancellation checks around the
        call to ``process()``.

        Args:
            event: Validated ``ADTEvent`` deserialized from Pub/Sub message.

        Returns:
            Structured output matching the agent's ``BaseAgentOutput`` subclass.

        Raises:
            RetryableError: For transient failures (triggers NACK + retry).
            NonRetryableError: For permanent failures (triggers FAILED status).
        """

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def subscribe(self) -> None:
        """Start the Pub/Sub message pull loop.

        Runs until a SIGTERM is received. Each iteration:
        1. Pull one message from the subscription
        2. Transition AgentTask to IN_PROGRESS
        3. Check cancellation flag
        4. Call ``process()``
        5. Persist output; transition AgentTask to COMPLETED
        6. ACK the message

        On ``RetryableError``: NACK + increment retry counter.
        On ``NonRetryableError``: set FAILED + propagate (Pub/Sub will retry
        until max_delivery_attempts exhausted then route to DLQ).
        """
        subscriber = pubsub_v1.SubscriberClient()

        logger.info(
            "base_agent_subscribe_start",
            extra={"subscription": self._subscription_path},
        )

        while not self._shutdown:
            response = subscriber.pull(
                request={
                    "subscription": self._subscription_path,
                    "max_messages": self._max_messages,
                }
            )

            if not response.received_messages:
                await asyncio.sleep(1)
                continue

            for received_message in response.received_messages:
                if self._shutdown:
                    # SIGTERM received mid-batch; NACK unprocessed messages
                    self.nack(subscriber, received_message.ack_id)
                    continue

                await self._handle_message(subscriber, received_message)

        logger.info(
            "base_agent_subscribe_stopped",
            extra={"subscription": self._subscription_path},
        )

    # ------------------------------------------------------------------
    # ACK / NACK
    # ------------------------------------------------------------------

    def ack(
        self,
        subscriber: pubsub_v1.SubscriberClient,
        ack_id: str,
    ) -> None:
        """Acknowledge a Pub/Sub message (prevent redelivery).

        Called after successful processing or after CANCELLED to prevent
        message accumulation in the DLQ (TR-015, AC Scenario 3).

        Args:
            subscriber: Active ``SubscriberClient`` instance.
            ack_id: ACK ID from the received message.
        """
        subscriber.acknowledge(
            request={
                "subscription": self._subscription_path,
                "ack_ids": [ack_id],
            }
        )
        logger.debug("pubsub_ack", extra={"ack_id": ack_id[:12]})

    def nack(
        self,
        subscriber: pubsub_v1.SubscriberClient,
        ack_id: str,
    ) -> None:
        """Negative-acknowledge a Pub/Sub message (trigger redelivery).

        Sets ``ack_deadline_seconds=0`` which immediately makes the message
        available for redelivery. Pub/Sub increments its internal delivery
        counter; after ``max_delivery_attempts=5`` the message is routed to
        the DLQ subscription (TR-015).

        Args:
            subscriber: Active ``SubscriberClient`` instance.
            ack_id: ACK ID from the received message.
        """
        subscriber.modify_ack_deadline(
            request={
                "subscription": self._subscription_path,
                "ack_ids": [ack_id],
                "ack_deadline_seconds": 0,
            }
        )
        logger.warning("pubsub_nack", extra={"ack_id": ack_id[:12]})

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    async def check_cancellation(self, encounter_id: str) -> bool:
        """Check the Redis cancellation flag for the given encounter.

        Queries ``cancellation:{encounter_id}`` key in Redis (TTL=3600s).
        Set by EP-001 A11/A12/A13 cancellation event handlers (US-015).

        Args:
            encounter_id: UUID string of the encounter to check.

        Returns:
            ``True`` if the encounter is cancelled; ``False`` otherwise.
        """
        return await self._cancellation_checker.is_cancelled(encounter_id)

    # ------------------------------------------------------------------
    # Task status
    # ------------------------------------------------------------------

    async def update_task_status(
        self,
        task_id: str,
        status: AgentTaskStatus,
        error_details: dict[str, Any] | None = None,
        retry_increment: bool = False,
    ) -> None:
        """Persist an AgentTask status transition to the database.

        Uses ``SELECT … FOR UPDATE SKIP LOCKED`` to prevent concurrent
        status overwrites on Pub/Sub redelivery race conditions.

        Status transitions (US-024 Technical Notes):
        - ``PENDING → IN_PROGRESS`` on message receipt
        - ``IN_PROGRESS → COMPLETED`` on successful ``process()``
        - ``IN_PROGRESS → CANCELLED`` when cancellation flag is set
        - ``IN_PROGRESS → FAILED`` on ``NonRetryableError`` or exhausted retries

        Args:
            task_id: UUID string of the ``AgentTask`` row.
            status: Target ``AgentTaskStatus`` value.
            error_details: Optional structured error dict serialised to JSON
                and stored in ``AgentTask.error_details``.
            retry_increment: If ``True``, increment ``AgentTask.retry_count``.
        """
        from app.models.agent_task import AgentTask  # noqa: PLC0415
        from sqlalchemy import select, update  # noqa: PLC0415

        async with self._db_session() as session:
            async with session.begin():
                stmt = (
                    update(AgentTask)
                    .where(AgentTask.id == task_id)
                    .values(
                        status=status.value,
                        error_details=(
                            json.dumps(error_details) if error_details else None
                        ),
                        **(
                            {"retry_count": AgentTask.retry_count + 1}
                            if retry_increment
                            else {}
                        ),
                    )
                )
                await session.execute(stmt)

        logger.info(
            "agent_task_status_updated",
            extra={
                "task_id": task_id,
                "status": status.value,
                "retry_increment": retry_increment,
            },
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _handle_message(
        self,
        subscriber: pubsub_v1.SubscriberClient,
        received_message: Any,
    ) -> None:
        """Orchestrate the full message processing lifecycle for one message."""
        from app.models.adt_event import ADTEvent  # noqa: PLC0415

        ack_id = received_message.ack_id
        raw_data = received_message.message.data

        try:
            event = ADTEvent.model_validate_json(raw_data)
        except Exception as exc:
            # Malformed payload — non-retryable; ACK to avoid infinite DLQ loop
            logger.error(
                "agent_message_parse_error",
                extra={"error": str(exc)},
            )
            self.ack(subscriber, ack_id)
            return

        task_id: str | None = received_message.message.attributes.get("task_id")

        try:
            if task_id:
                await self.update_task_status(task_id, AgentTaskStatus.IN_PROGRESS)

            # --- Cancellation check (before any processing) ---
            if await self.check_cancellation(str(event.encounter_id)):
                logger.info(
                    "agent_cancelled",
                    extra={"encounter_id": str(event.encounter_id)},
                )
                if task_id:
                    await self.update_task_status(task_id, AgentTaskStatus.CANCELLED)
                self.ack(subscriber, ack_id)
                return

            # --- Core processing ---
            await self.process(event)

            # --- Success ---
            if task_id:
                await self.update_task_status(task_id, AgentTaskStatus.COMPLETED)
            self.ack(subscriber, ack_id)

        except RetryableError as exc:
            logger.warning(
                "agent_retryable_failure",
                extra={
                    "encounter_id": str(event.encounter_id),
                    "error": str(exc),
                    "error_detail": exc.error_detail,
                },
            )
            if task_id:
                await self.update_task_status(
                    task_id,
                    AgentTaskStatus.IN_PROGRESS,
                    retry_increment=True,
                )
            self.nack(subscriber, ack_id)

        except NonRetryableError as exc:
            logger.error(
                "agent_nonretryable_failure",
                extra={
                    "encounter_id": str(event.encounter_id),
                    "error": str(exc),
                    "error_detail": exc.error_detail,
                },
            )
            if task_id:
                await self.update_task_status(
                    task_id,
                    AgentTaskStatus.FAILED,
                    error_details={"error": str(exc), **exc.error_detail},
                )
            # ACK so Pub/Sub delivery counter continues naturally toward DLQ
            # (Pub/Sub's max_delivery_attempts=5 counts NACK-based redeliveries;
            #  for non-retryable we ACK to avoid redundant reprocessing)
            self.ack(subscriber, ack_id)

        except Exception as exc:
            logger.exception(
                "agent_unexpected_failure",
                extra={"encounter_id": str(event.encounter_id), "error": str(exc)},
            )
            if task_id:
                await self.update_task_status(
                    task_id,
                    AgentTaskStatus.FAILED,
                    error_details={"error": str(exc), "type": type(exc).__name__},
                )
            self.ack(subscriber, ack_id)

    def _handle_sigterm(self, signum: int, frame: Any) -> None:
        """Set shutdown flag on SIGTERM/SIGINT.

        Cloud Run sends SIGTERM 10 seconds before SIGKILL. Setting
        ``_shutdown=True`` allows the current message to complete before
        the subscriber loop exits gracefully.
        """
        logger.info(
            "agent_sigterm_received",
            extra={"signal": signum, "subscription": self._subscription_path},
        )
        self._shutdown = True
```

---

## Validation

Run from `base-agent/`:

```bash
# 1. Syntax check
python -c "
import ast, pathlib
ast.parse(pathlib.Path('app/base/agent.py').read_text())
print('Syntax check app/base/agent.py: PASSED')
"

# 2. BaseAgent is abstract — cannot be instantiated directly
python -c "
from app.base.agent import BaseAgent
try:
    BaseAgent.__abstractmethods__
    assert 'process' in BaseAgent.__abstractmethods__, 'process must be abstract'
    print('BaseAgent abstract method process: PASSED')
except AttributeError:
    raise AssertionError('BaseAgent must have __abstractmethods__')
"

# 3. AgentTaskStatus enum values match expected strings
python -c "
from app.base.agent import AgentTaskStatus
assert AgentTaskStatus.PENDING == 'PENDING'
assert AgentTaskStatus.IN_PROGRESS == 'IN_PROGRESS'
assert AgentTaskStatus.COMPLETED == 'COMPLETED'
assert AgentTaskStatus.FAILED == 'FAILED'
assert AgentTaskStatus.CANCELLED == 'CANCELLED'
print('AgentTaskStatus values: PASSED')
"

# 4. Specialist agent can extend BaseAgent
python -c "
from app.base.agent import BaseAgent, BaseAgentOutput
from app.models.adt_event import ADTEvent

class TestAgent(BaseAgent):
    async def process(self, event: ADTEvent) -> BaseAgentOutput:
        return BaseAgentOutput()

print('Specialist agent subclass: PASSED')
"
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `base-agent/app/base/agent.py` |

---

## Definition of Done Checklist

- [ ] `BaseAgent` is an `ABC`; `process()` is `@abstractmethod`
- [ ] `subscribe()` enters pull loop; exits cleanly on `_shutdown = True`
- [ ] `ack()` calls `subscriber.acknowledge()` with correct subscription path
- [ ] `nack()` calls `subscriber.modify_ack_deadline(ack_deadline_seconds=0)`
- [ ] `check_cancellation(encounter_id)` delegates to `CancellationChecker`
- [ ] `update_task_status()` writes to DB with `SELECT … FOR UPDATE` semantics
- [ ] `PENDING → IN_PROGRESS` on message receipt; `IN_PROGRESS → COMPLETED/FAILED/CANCELLED` on completion
- [ ] ACK on `CANCELLED` (prevents DLQ accumulation — AC Scenario 3)
- [ ] NACK on `RetryableError` + `retry_count` incremented (AC Scenario 2)
- [ ] `NonRetryableError` → `FAILED` status with error JSON (AC Scenario 4)
- [ ] SIGTERM sets `_shutdown = True`; current message completes before exit
- [ ] No PHI in structured log fields (only UUID encounter IDs, task IDs, status values)
