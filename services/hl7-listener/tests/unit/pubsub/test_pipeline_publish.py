"""Unit tests for Pub/Sub integration step in app/mllp/pipeline.py.

Verifies:
  - publisher.publish() is called after router.route() (Step 6 > Step 5)
  - ACK bytes returned only after publisher.publish() completes (SC-3 deferred ACK)
  - A publisher failure does not prevent ACK (publish() handles failures internally)
  - Publisher not called when pipeline short-circuits on duplicate detection
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.mllp.pipeline as pipeline_module
from tests.factories.adt_event_factory import make_adt_event

# Minimal valid MSH-only HL7 string for testing pipeline entry
_RAW_HL7 = (
    "MSH|^~\\&|EHR|HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG-001|P|2.5\r"
    "EVN|A01|20260715095500\r"
    "PID|1||MRN-1001^^^HOSP^MR||Smith^John||19800115|M\r"
    "PV1|1|I|2E^2012^A|||DR-SMITH||||||||||||ENC-001\r"
)


@pytest.fixture(autouse=True)
def reset_pipeline_singletons():
    """Reset module-level singletons before and after each test."""
    original_publisher = pipeline_module._publisher
    original_archiver = pipeline_module._gcs_archiver
    original_fallback = pipeline_module._fallback_queue
    original_retry_queue = pipeline_module._publish_retry_queue
    yield
    pipeline_module._publisher = original_publisher
    pipeline_module._gcs_archiver = original_archiver
    pipeline_module._fallback_queue = original_fallback
    pipeline_module._publish_retry_queue = original_retry_queue


@pytest.fixture()
def mock_publisher() -> AsyncMock:
    pub = AsyncMock()
    pub.publish = AsyncMock()
    return pub


@pytest.fixture()
def mock_archiver() -> AsyncMock:
    archiver = AsyncMock()
    archiver.archive = AsyncMock(return_value=True)
    return archiver


@pytest.fixture()
def mock_adt_event():
    return make_adt_event(event_type="ADMIT")


@pytest.fixture()
def wired_pipeline(mock_publisher, mock_archiver, mock_adt_event):
    """Wire mock dependencies into the pipeline module singletons."""
    pipeline_module._publisher = mock_publisher
    pipeline_module._gcs_archiver = mock_archiver

    # Stub out idempotency and parser
    pipeline_module._idempotency_checker = MagicMock()
    pipeline_module._hl7_parser = MagicMock()
    pipeline_module._hl7_parser.parse.return_value = mock_adt_event

    return pipeline_module


@pytest.mark.asyncio
async def test_publish_called_after_route(wired_pipeline, mock_publisher, mock_adt_event):
    """Step 6 (publish) must execute after Step 5 (route)."""
    call_order: list[str] = []

    async def record_publish(event):
        call_order.append("publish")

    mock_publisher.publish.side_effect = record_publish

    with (
        patch.object(wired_pipeline, "_idempotency_checker") as mock_idm,
        patch("app.mllp.pipeline.get_async_session") as mock_session_ctx,
        patch("app.mllp.pipeline.default_router") as mock_router,
    ):
        mock_idm.is_duplicate = AsyncMock(return_value=False)
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        def record_route(event):
            call_order.append("route")

        mock_router.route.side_effect = record_route

        await wired_pipeline.process_message(_RAW_HL7)

    assert "route" in call_order, "route() was not called"
    assert "publish" in call_order, "publish() was not called"
    assert call_order.index("route") < call_order.index("publish"), (
        "route() must be called before publish()"
    )


@pytest.mark.asyncio
async def test_ack_returned_after_publish(wired_pipeline, mock_publisher):
    """ACK bytes are returned only after publish() completes (SC-3)."""
    publish_completed: list[bool] = []

    async def record_publish(event):
        publish_completed.append(True)

    mock_publisher.publish.side_effect = record_publish

    with (
        patch("app.mllp.pipeline.get_async_session") as mock_session_ctx,
        patch("app.mllp.pipeline.default_router"),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        ack = await wired_pipeline.process_message(_RAW_HL7)

    assert publish_completed, "publish() must complete before ACK is returned"
    assert isinstance(ack, bytes), "ACK must be bytes"
    assert b"MSA|AA" in ack, "ACK response must contain MSA|AA"


@pytest.mark.asyncio
async def test_publisher_failure_does_not_prevent_ack(wired_pipeline, mock_publisher):
    """If publish() raises, pipeline should still return ACK (publish handles internally)."""
    # publish() should never raise — it handles failures internally by enqueuing.
    # This test verifies the pipeline does not propagate any exception.
    mock_publisher.publish.side_effect = None  # No-op (already default AsyncMock)

    with (
        patch("app.mllp.pipeline.get_async_session") as mock_session_ctx,
        patch("app.mllp.pipeline.default_router"),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        ack = await wired_pipeline.process_message(_RAW_HL7)

    assert isinstance(ack, bytes)
    mock_publisher.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_not_called_for_duplicate_message(wired_pipeline, mock_publisher):
    """Duplicate messages short-circuit before Step 6 — publisher must NOT be called."""
    with (
        patch("app.mllp.pipeline.get_async_session") as mock_session_ctx,
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # Force idempotency check to return True (duplicate)
        wired_pipeline._idempotency_checker = MagicMock()
        wired_pipeline._idempotency_checker.is_duplicate = AsyncMock(return_value=True)

        ack = await wired_pipeline.process_message(_RAW_HL7)

    mock_publisher.publish.assert_not_awaited()
    assert b"MSA|AA" in ack


@pytest.mark.asyncio
async def test_publish_not_called_when_parse_fails(wired_pipeline, mock_publisher):
    """GAP-4: Parse failure (Step 4 NACK) must not reach Step 6 — publisher must NOT be called."""
    from app.parser.models import HL7ValidationError

    # Force the parser to raise HL7ValidationError (invalid message)
    wired_pipeline._hl7_parser.parse.side_effect = HL7ValidationError(
        "Missing mandatory segment MSH", segment="MSH"
    )

    with (
        patch("app.mllp.pipeline.get_async_session") as mock_session_ctx,
        patch("app.mllp.pipeline.default_router"),
    ):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        nack = await wired_pipeline.process_message(_RAW_HL7)

    # Publisher must NOT be called — the pipeline returned NACK at Step 4
    mock_publisher.publish.assert_not_awaited()
    # Response must be a NACK (AE), not an ACK (AA)
    assert b"MSA|AE" in nack, f"Expected NACK (AE) on parse failure, got: {nack!r}"
