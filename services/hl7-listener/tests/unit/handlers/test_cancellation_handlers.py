"""Unit tests for HL7 listener cancellation handlers (US-015 TASK-005).

Tests:
  - 404 response from API → warning logged, no exception raised (best-effort)
  - Timeout → exception re-raised (MLLP server will issue NACK)
  - 409 response → HL7ValidationError raised (NACK)
  - Successful 200 → handler returns without error
  - register_cancellation_handlers() registers all 3 event types
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.parser.models import ADTEvent, EventType, HL7ValidationError
from app.parser.router import ADTRouter
from app.handlers.cancellation_handlers import (
    cancel_admit_handler,
    cancel_transfer_handler,
    cancel_discharge_handler,
    register_cancellation_handlers,
    _call_cancel_api,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ENC_ID = uuid4()


def _make_event(event_type=EventType.CANCEL_ADMIT):
    event = MagicMock()
    event.encounter_id = ENC_ID
    event.event_type = event_type
    return event


def _make_response(status_code: int, json_body: dict | None = None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body or {})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# _call_cancel_api tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_404_logs_warning_and_returns():
    """404 response must be silently absorbed (best-effort for unknown encounters)."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(return_value=_make_response(404))

    # Should not raise
    await _call_cancel_api(str(ENC_ID), "A11", client)

    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_timeout_is_reraised():
    """Timeout exception must be re-raised so MLLP server issues NACK."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(httpx.TimeoutException):
        await _call_cancel_api(str(ENC_ID), "A11", client)


@pytest.mark.asyncio
async def test_409_raises_hl7_validation_error():
    """409 Conflict (state machine rejection) must raise HL7ValidationError."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(
        return_value=_make_response(409, {"detail": "invalid transition"})
    )

    with pytest.raises(HL7ValidationError):
        await _call_cancel_api(str(ENC_ID), "A11", client)


@pytest.mark.asyncio
async def test_200_returns_without_error():
    """Successful 2xx response must return without raising."""
    client = AsyncMock(spec=httpx.AsyncClient)
    resp = _make_response(200)
    resp.raise_for_status = MagicMock()  # no-op on 200
    client.post = AsyncMock(return_value=resp)

    await _call_cancel_api(str(ENC_ID), "A12", client)  # no exception


# ---------------------------------------------------------------------------
# register_cancellation_handlers tests
# ---------------------------------------------------------------------------


def test_register_cancellation_handlers_registers_all_types():
    """All three cancellation event types must be registered after calling register."""
    router = ADTRouter()
    register_cancellation_handlers(router=router)

    assert router.is_registered(EventType.CANCEL_ADMIT)
    assert router.is_registered(EventType.CANCEL_TRANSFER)
    assert router.is_registered(EventType.CANCEL_DISCHARGE)


def test_register_is_idempotent():
    """Calling register_cancellation_handlers twice must not raise."""
    router = ADTRouter()
    register_cancellation_handlers(router=router)
    register_cancellation_handlers(router=router)  # second call must not raise

    assert router.is_registered(EventType.CANCEL_ADMIT)
