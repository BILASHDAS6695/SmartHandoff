"""Unit tests for app/parser/router.py — ADTRouter and default_router.

Coverage:
  - ADTRouter.register() decorator
  - ADTRouter.register_fn() imperative registration
  - ADTRouter.route() dispatch
  - ADTRouter.is_registered()
  - ADTRouter.registered_types()
  - Unregistered event type → HL7ValidationError
  - default_router has all 8 event types registered with stub handlers
"""
from __future__ import annotations

import datetime

import pytest

from app.parser.models import ADTEvent, EventType, HL7ValidationError
from app.parser.router import ADTRouter, default_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(event_type: EventType) -> ADTEvent:
    return ADTEvent(
        source_message_id="MSG001",
        event_type=event_type,
        sending_application="EHR",
        message_datetime=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc),
        event_time=datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc),
        patient_mrn="MRN-1001",
        encounter_id="ENC-9001",
    )


# ---------------------------------------------------------------------------
# ADTRouter
# ---------------------------------------------------------------------------

class TestADTRouter:
    def test_register_decorator_registers_handler(self):
        router = ADTRouter()

        @router.register(EventType.ADMIT)
        def handle_admit(event: ADTEvent):
            return "admit_result"

        assert router.is_registered(EventType.ADMIT)

    def test_register_fn_registers_handler(self):
        router = ADTRouter()
        router.register_fn(EventType.DISCHARGE, lambda e: "discharged")
        assert router.is_registered(EventType.DISCHARGE)

    def test_route_dispatches_to_registered_handler(self):
        router = ADTRouter()
        results = []

        @router.register(EventType.TRANSFER)
        def handle_transfer(event: ADTEvent):
            results.append(event.event_type)
            return "transferred"

        event = _make_event(EventType.TRANSFER)
        ret = router.route(event)
        assert ret == "transferred"
        assert results == [EventType.TRANSFER]

    def test_route_returns_handler_return_value(self):
        router = ADTRouter()
        router.register_fn(
            EventType.UPDATE,
            lambda e: {"status": "ok", "msg_id": e.source_message_id},
        )
        event = _make_event(EventType.UPDATE)
        result = router.route(event)
        assert result["status"] == "ok"
        assert result["msg_id"] == "MSG001"

    def test_route_unregistered_type_raises_hl7_validation_error(self):
        router = ADTRouter()
        # No handler registered
        event = _make_event(EventType.ADMIT)
        with pytest.raises(HL7ValidationError) as exc_info:
            router.route(event)
        assert "ADMIT" in str(exc_info.value)

    def test_registered_types_returns_all_registered_types(self):
        router = ADTRouter()
        router.register_fn(EventType.ADMIT, lambda e: None)
        router.register_fn(EventType.DISCHARGE, lambda e: None)
        types = router.registered_types()
        assert EventType.ADMIT in types
        assert EventType.DISCHARGE in types
        assert len(types) == 2

    def test_re_registering_replaces_previous_handler(self):
        router = ADTRouter()
        router.register_fn(EventType.REGISTER, lambda e: "first")
        router.register_fn(EventType.REGISTER, lambda e: "second")
        event = _make_event(EventType.REGISTER)
        assert router.route(event) == "second"

    def test_is_registered_returns_false_for_unregistered(self):
        router = ADTRouter()
        assert not router.is_registered(EventType.CANCEL_ADMIT)

    def test_registered_types_sorted_by_value(self):
        router = ADTRouter()
        for et in EventType:
            router.register_fn(et, lambda e: None)
        types = router.registered_types()
        values = [t.value for t in types]
        assert values == sorted(values)

    def test_handler_receives_correct_event_object(self):
        router = ADTRouter()
        received: list[ADTEvent] = []

        @router.register(EventType.CANCEL_DISCHARGE)
        def capture(event: ADTEvent):
            received.append(event)

        event = _make_event(EventType.CANCEL_DISCHARGE)
        router.route(event)
        assert len(received) == 1
        assert received[0].source_message_id == "MSG001"


# ---------------------------------------------------------------------------
# default_router (module-level singleton)
# ---------------------------------------------------------------------------

class TestDefaultRouter:
    def test_all_eight_event_types_registered_in_default_router(self):
        for event_type in EventType:
            assert default_router.is_registered(event_type), (
                f"default_router missing handler for {event_type.value}"
            )

    def test_default_router_routes_admit_without_error(self):
        """Stub handler should not raise for any EventType."""
        event = _make_event(EventType.ADMIT)
        result = default_router.route(event)  # stub returns None
        assert result is None

    @pytest.mark.parametrize("event_type", list(EventType))
    def test_default_router_stub_handles_all_event_types(self, event_type):
        """All 8 stubs should route without raising."""
        event = _make_event(event_type)
        try:
            default_router.route(event)
        except Exception as exc:
            pytest.fail(
                f"default_router raised {type(exc).__name__} for "
                f"{event_type.value}: {exc}"
            )
