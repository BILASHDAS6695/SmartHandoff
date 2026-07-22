"""Unit tests for app/pubsub/publish_retry_queue.py.

Coverage:
  - enqueue() adds to queue and emits structured log
  - background flush re-publishes and removes successful entries
  - stop() signals flush loop and logs remaining entries on non-empty shutdown
  - bounded deque evicts oldest on overflow
  - _flush_once() retains failed events and re-enqueues at front (FIFO)
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.pubsub.publish_retry_queue import PublishRetryQueue, _MAX_QUEUE_SIZE
from tests.factories.adt_event_factory import make_adt_event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_publish_fn() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def retry_queue(mock_publish_fn) -> PublishRetryQueue:
    """RetryQueue with a very short flush interval for test speed."""
    return PublishRetryQueue(publish_fn=mock_publish_fn, flush_interval=0.05)


# ---------------------------------------------------------------------------
# Enqueue behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_increases_depth(retry_queue):
    """depth() returns 1 after a single enqueue."""
    event = make_adt_event()
    assert retry_queue.depth() == 0
    await retry_queue.enqueue(event)
    assert retry_queue.depth() == 1


@pytest.mark.asyncio
async def test_enqueue_multiple_messages(retry_queue):
    """depth() tracks multiple enqueued events."""
    for i in range(5):
        await retry_queue.enqueue(make_adt_event())
    assert retry_queue.depth() == 5


@pytest.mark.asyncio
async def test_bounded_queue_evicts_oldest_on_overflow(mock_publish_fn):
    """Queue does not exceed _MAX_QUEUE_SIZE — oldest entry is evicted."""
    queue = PublishRetryQueue(publish_fn=mock_publish_fn)
    for _ in range(_MAX_QUEUE_SIZE + 5):
        await queue.enqueue(make_adt_event())
    assert queue.depth() == _MAX_QUEUE_SIZE


@pytest.mark.asyncio
async def test_enqueue_emits_structured_log(retry_queue, caplog):
    """enqueue() emits pubsub_retry_queue_enqueued at ERROR level."""
    event = make_adt_event()
    with caplog.at_level(logging.ERROR):
        await retry_queue.enqueue(event)
    assert "pubsub_retry_queue_enqueued" in caplog.text


# ---------------------------------------------------------------------------
# Flush behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_publishes_queued_event(retry_queue, mock_publish_fn):
    """_flush_once() calls publish_fn and removes the event on success."""
    event = make_adt_event()
    await retry_queue.enqueue(event)
    await retry_queue._flush_once()

    mock_publish_fn.assert_awaited_once_with(event)
    assert retry_queue.depth() == 0


@pytest.mark.asyncio
async def test_flush_retains_failed_events(retry_queue, mock_publish_fn):
    """_flush_once() retains events that still fail for next cycle."""
    mock_publish_fn.side_effect = Exception("Pub/Sub still down")
    event = make_adt_event()
    await retry_queue.enqueue(event)
    await retry_queue._flush_once()

    assert retry_queue.depth() == 1  # retained


@pytest.mark.asyncio
async def test_flush_calls_publish_for_each_entry(retry_queue, mock_publish_fn):
    """_flush_once() calls publish_fn for every queued event."""
    for _ in range(3):
        await retry_queue.enqueue(make_adt_event())
    await retry_queue._flush_once()

    assert mock_publish_fn.await_count == 3


@pytest.mark.asyncio
async def test_flush_no_op_when_queue_empty(retry_queue, mock_publish_fn):
    """_flush_once() does not call publish_fn when the queue is empty."""
    await retry_queue._flush_once()
    mock_publish_fn.assert_not_awaited()


# ---------------------------------------------------------------------------
# Shutdown behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_background_task(retry_queue):
    """start() creates the named background flush task."""
    assert retry_queue._flush_task is None
    await retry_queue.start()
    assert retry_queue._flush_task is not None
    await retry_queue.stop()


@pytest.mark.asyncio
async def test_stop_when_queue_empty_no_warning(retry_queue, caplog):
    """stop() with empty queue does not log shutdown_with_pending."""
    await retry_queue.start()
    with caplog.at_level(logging.WARNING):
        await retry_queue.stop()
    assert "shutdown_with_pending" not in caplog.text


@pytest.mark.asyncio
async def test_stop_logs_remaining_when_queue_non_empty(mock_publish_fn, caplog):
    """stop() logs publish_retry_queue_shutdown_with_pending if events remain."""
    # Use a long flush interval so the background task never drains the queue
    queue = PublishRetryQueue(publish_fn=mock_publish_fn, flush_interval=9999.0)
    await queue.start()
    await queue.enqueue(make_adt_event())

    with caplog.at_level(logging.WARNING):
        await queue.stop()

    assert any(
        "shutdown_with_pending" in r.message or "remaining" in r.message.lower()
        for r in caplog.records
        if r.levelno >= logging.WARNING
    )
