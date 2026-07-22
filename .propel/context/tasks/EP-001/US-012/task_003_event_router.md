---
id: TASK-003
title: "Create `hl7-listener/app/parser/router.py` — ADT Event Type Router & Handler Registration"
user_story: US-012
epic: EP-001
sprint: 1
layer: Backend
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-012/TASK-001, US-012/TASK-002]
---

# TASK-003: Create `hl7-listener/app/parser/router.py` — ADT Event Type Router & Handler Registration

> **Story:** US-012 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Backend | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

The US-012 DoD requires:

> *"Event type routing map: `{A01: admit_handler, A02: transfer_handler, ...}` with handler registration pattern"*

The router is the integration point between the HL7 parser output and the Pub/Sub publisher. After `HL7Parser.parse()` returns an `ADTEvent`, the router:

1. Maps the `EventType` enum value to a registered handler callable.
2. Invokes the handler with the `ADTEvent`.
3. Provides a `@register_handler(event_type)` decorator for clean handler registration.
4. Returns the handler result to the caller (e.g. Pub/Sub message ID from the publisher).

The router itself does **not** publish to Pub/Sub — that responsibility belongs to the Pub/Sub publisher module (outside US-012 scope). Instead, the default handlers for this story are **stub implementations** that log the event and return `None`. The Pub/Sub publisher (a later story) will replace the stubs by registering real handlers.

This design ensures the MLLP server (US-011) can integrate US-012 components without waiting for the Pub/Sub publisher to be complete.

Design refs: FR-002, US-012 DoD, ADR-001 (Pub/Sub event bus).

---

## Acceptance Criteria Addressed

| US-012 AC | Requirement |
|---|---|
| **Scenario 2** | Routing map dispatches all 8 event types to registered handlers |
| **Scenario 3** | Unknown event type never reaches the router (caught in `HL7Parser`); router raises `KeyError`-safe `HL7ValidationError` if called with unregistered type |
| **DoD** | Event type routing map `{A01: admit_handler, ...}` with handler registration pattern |

---

## Implementation Steps

### 1. Create `hl7-listener/app/parser/router.py`

```python
"""ADT event type router with handler registration pattern.

Routes a parsed ``ADTEvent`` to the appropriate registered handler based on
``ADTEvent.event_type``.  Handlers are registered via the ``@register_handler``
decorator or the ``ADTRouter.register()`` method.

Design:
  - ``ADTRouter`` is the central dispatcher.  A module-level singleton
    ``default_router`` is exported for use by the MLLP server and tests.
  - Handler registration is idempotent: re-registering the same event type
    replaces the previous handler (useful for test isolation).
  - Default stub handlers are registered at module load time so that
    ``default_router.route(event)`` is always callable, even before the
    Pub/Sub publisher is wired up.

Handler signature::

    def my_handler(event: ADTEvent) -> Any:
        ...

Async handlers are NOT supported in this module (Phase 1). The MLLP server
invokes the router synchronously inside its asyncio handler via
``asyncio.get_event_loop().run_in_executor(None, default_router.route, event)``.

Design refs:
    FR-002  — ADT event type classification (A01–A13)
    ADR-001 — Pub/Sub event bus (handlers will publish to adt-events topic)
    US-012  — DoD: routing map with handler registration pattern
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from app.parser.models import ADTEvent, EventType, HL7ValidationError

logger = logging.getLogger(__name__)

# Type alias for handler callables
HandlerFn = Callable[[ADTEvent], Any]


class ADTRouter:
    """Registry and dispatcher for ADT event handlers.

    Each ``EventType`` maps to exactly one handler.  Unregistered event types
    raise ``HL7ValidationError`` to prevent silent failures.

    Usage::

        router = ADTRouter()

        @router.register(EventType.ADMIT)
        def handle_admit(event: ADTEvent) -> None:
            ...  # publish to Pub/Sub, write to DB, etc.

        result = router.route(event)
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, HandlerFn] = {}

    def register(self, event_type: EventType) -> Callable[[HandlerFn], HandlerFn]:
        """Decorator that registers a handler for the given ``EventType``.

        Example::

            @router.register(EventType.ADMIT)
            def handle_admit(event: ADTEvent) -> None:
                publish_to_pubsub(event)
        """
        def decorator(fn: HandlerFn) -> HandlerFn:
            self._handlers[event_type] = fn
            logger.debug(
                "Registered handler '%s' for event_type='%s'",
                fn.__name__,
                event_type.value,
            )
            return fn
        return decorator

    def register_fn(self, event_type: EventType, handler: HandlerFn) -> None:
        """Register a handler imperatively (alternative to decorator).

        Args:
            event_type: The ``EventType`` this handler responds to.
            handler:    Callable accepting a single ``ADTEvent`` argument.
        """
        self._handlers[event_type] = handler
        logger.debug(
            "Registered handler '%s' for event_type='%s'",
            handler.__name__,
            event_type.value,
        )

    def route(self, event: ADTEvent) -> Any:
        """Dispatch ``event`` to its registered handler and return the result.

        Args:
            event: A parsed and validated ``ADTEvent``.

        Returns:
            Whatever the registered handler returns (e.g. Pub/Sub message ID).

        Raises:
            HL7ValidationError: If no handler is registered for
                ``event.event_type``.  This should not occur in production
                because the parser rejects unknown trigger codes; it is a
                safety net for misconfigured deployments.
        """
        handler = self._handlers.get(event.event_type)
        if handler is None:
            raise HL7ValidationError(
                f"No handler registered for event_type='{event.event_type.value}'",
                segment="MSH",
                field="MSH-9.2",
            )

        logger.info(
            "Routing event: event_type='%s' source_message_id='%s' encounter_id='%s'",
            event.event_type.value,
            event.source_message_id,
            event.encounter_id,
        )
        return handler(event)

    def registered_types(self) -> list[EventType]:
        """Return a sorted list of event types that have registered handlers."""
        return sorted(self._handlers.keys(), key=lambda e: e.value)

    def is_registered(self, event_type: EventType) -> bool:
        """Return True if a handler is registered for ``event_type``."""
        return event_type in self._handlers


# ---------------------------------------------------------------------------
# Module-level default router singleton
# ---------------------------------------------------------------------------

default_router = ADTRouter()


# ---------------------------------------------------------------------------
# Stub handlers (replaced by Pub/Sub publisher in a later story)
# ---------------------------------------------------------------------------

def _stub_handler(event: ADTEvent) -> None:
    """Default stub handler — logs the event and returns None.

    This handler is registered for all 8 event types at module load time.
    It will be replaced by the real Pub/Sub publisher handler once that
    module is implemented (see ADR-001).
    """
    logger.info(
        "STUB handler invoked: event_type='%s' encounter_id='%s' — "
        "Pub/Sub publisher not yet wired up",
        event.event_type.value,
        event.encounter_id,
    )


# Register stub handlers for all 8 supported event types
for _event_type in EventType:
    default_router.register_fn(_event_type, _stub_handler)
```

### 2. Create `hl7-listener/app/parser/pipeline.py` — End-to-end parse + route

```python
"""End-to-end HL7 parse → route pipeline for the MLLP server.

Provides a single entry point used by ``app/mllp/server.py`` to process
an inbound raw HL7 message string.  Separates the MLLP server from the
parser and router internals.

Usage in server.py::

    from app.parser.pipeline import process_hl7_message

    try:
        result = process_hl7_message(raw_hl7_str)
    except HL7ValidationError as exc:
        # Build NACK
        ...

Design refs: US-012, AIR-002, FR-002.
"""
from __future__ import annotations

import logging
from typing import Any

from app.parser.hl7_parser import HL7Parser
from app.parser.models import HL7ValidationError
from app.parser.router import default_router

logger = logging.getLogger(__name__)

_parser = HL7Parser()


def process_hl7_message(raw_hl7: str) -> Any:
    """Parse a raw HL7 string and route the resulting ADTEvent.

    Args:
        raw_hl7: CR-terminated HL7 v2 text (MLLP framing already stripped).

    Returns:
        The return value of the registered handler (or None for stubs).

    Raises:
        HL7ValidationError: Propagated from parser or router for any
            structural failure — caller converts this to a NACK.
    """
    event = _parser.parse(raw_hl7)
    return default_router.route(event)
```

### 3. Update `hl7-listener/app/parser/__init__.py`

```python
"""HL7 parser package: domain model, parser, router, and pipeline."""

from app.parser.models import ADTEvent, EventType, HL7ValidationError, HL7_TRIGGER_MAP
from app.parser.hl7_parser import HL7Parser
from app.parser.router import ADTRouter, default_router
from app.parser.pipeline import process_hl7_message

__all__ = [
    "ADTEvent",
    "EventType",
    "HL7ValidationError",
    "HL7_TRIGGER_MAP",
    "HL7Parser",
    "ADTRouter",
    "default_router",
    "process_hl7_message",
]
```

---

## Validation

```bash
cd hl7-listener

python -c "
from app.parser.router import ADTRouter, default_router
from app.parser.models import EventType, ADTEvent
import datetime

# Verify all 8 event types have stub handlers registered
registered = default_router.registered_types()
expected = list(EventType)
assert len(registered) == 8, f'Expected 8 handlers, got {len(registered)}'
print('All 8 event types registered:', [e.value for e in registered])

# Verify custom handler registration via decorator
test_router = ADTRouter()
results = []

@test_router.register(EventType.ADMIT)
def handle_admit(event: ADTEvent):
    results.append(event.event_type)
    return 'handled'

assert test_router.is_registered(EventType.ADMIT)
print('Custom handler registration via decorator: PASSED')

# Verify routing dispatches to handler
dummy_event = ADTEvent(
    source_message_id='MSG001',
    event_type=EventType.ADMIT,
    sending_application='EHR',
    message_datetime=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc),
    event_time=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc),
    patient_mrn='MRN-001',
    encounter_id='ENC-9001',
)
ret = test_router.route(dummy_event)
assert ret == 'handled'
assert results[0] == EventType.ADMIT
print('Router dispatch: PASSED')
print('router.py: ALL CHECKS PASSED')
"
```

---

## Definition of Done Checklist

- [ ] `ADTRouter` class with `register()` decorator, `register_fn()`, `route()`, `is_registered()`
- [ ] `default_router` singleton with stub handlers for all 8 `EventType` values
- [ ] `process_hl7_message()` pipeline function combines parser + router
- [ ] `HL7ValidationError` raised (not `KeyError`) for unregistered event types
- [ ] No PHI in any log statement
- [ ] Validation script above runs without errors
