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
from typing import Any, Callable

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
                ``event.event_type``.
        """
        handler = self._handlers.get(event.event_type)
        if handler is None:
            logger.warning(
                "unknown_event_type=%s source_message_id=%s — no handler registered",
                event.event_type.value,
                event.source_message_id,
            )
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
