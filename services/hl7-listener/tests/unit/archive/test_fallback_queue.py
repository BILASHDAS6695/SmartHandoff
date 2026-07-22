"""Unit tests for app/archive/fallback_queue.py."""
from __future__ import annotations

import asyncio
import datetime
import logging
from unittest.mock import AsyncMock

import pytest

from app.archive.fallback_queue import FallbackQueue

_ARRIVED_AT = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)


# ---------------------------------------------------------------------------
# Enqueue behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFallbackQueueEnqueue:
    async def test_enqueue_increases_depth(self):
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        assert queue.depth == 0
        await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        assert queue.depth == 1

    async def test_enqueue_multiple_messages(self):
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        for i in range(5):
            await queue.enqueue(f"MSG-{i}", f"MSG-{i:04d}", _ARRIVED_AT)
        assert queue.depth == 5

    async def test_enqueue_bounded_at_500(self):
        """Queue does not exceed 500 — oldest entry is evicted on overflow."""
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        for i in range(501):
            await queue.enqueue(f"HL7MSG-{i}", f"MSG-{i:04d}", _ARRIVED_AT)
        assert queue.depth == 500  # maxlen enforced

    async def test_enqueue_emits_structured_log(self, caplog):
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        with caplog.at_level(logging.ERROR):
            await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        assert "hl7_fallback_queue_enqueued" in caplog.text


# ---------------------------------------------------------------------------
# Flush behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFallbackQueueFlush:
    async def test_flush_removes_successfully_archived_entries(self):
        """Entries successfully re-archived are removed from the queue."""
        mock_archiver = AsyncMock()
        mock_archiver.archive.return_value = True  # GCS succeeds on retry
        queue = FallbackQueue(archiver=mock_archiver)
        await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        assert queue.depth == 1
        await queue._flush_all()
        assert queue.depth == 0

    async def test_flush_retains_entries_that_still_fail(self):
        """Entries that still fail to archive remain in the queue for the next cycle."""
        mock_archiver = AsyncMock()
        mock_archiver.archive.return_value = False  # GCS still failing
        queue = FallbackQueue(archiver=mock_archiver)
        await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        await queue._flush_all()
        assert queue.depth == 1

    async def test_flush_all_does_nothing_when_queue_empty(self):
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        await queue._flush_all()  # should not raise
        mock_archiver.archive.assert_not_called()

    async def test_flush_calls_archiver_for_each_entry(self):
        mock_archiver = AsyncMock()
        mock_archiver.archive.return_value = True
        queue = FallbackQueue(archiver=mock_archiver)
        for i in range(3):
            await queue.enqueue(f"HL7MSG-{i}", f"MSG-{i:04d}", _ARRIVED_AT)
        await queue._flush_all()
        assert mock_archiver.archive.await_count == 3


# ---------------------------------------------------------------------------
# Shutdown behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFallbackQueueShutdown:
    async def test_stop_logs_remaining_entries(self, caplog):
        """stop() logs remaining unprocessed entries at ERROR level."""
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        await queue.start()
        await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        with caplog.at_level(logging.ERROR):
            await queue.stop()
        assert any(
            "unprocessed" in r.message.lower() or "remaining" in r.message.lower()
            for r in caplog.records
            if r.levelno >= logging.ERROR
        )

    async def test_stop_when_queue_empty_does_not_log_error(self, caplog):
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        await queue.start()
        # No enqueue — stop should not log remaining entries error
        with caplog.at_level(logging.ERROR):
            await queue.stop()
        shutdown_loss_records = [
            r for r in caplog.records
            if "shutdown_loss" in r.message or ("unprocessed" in r.message.lower())
        ]
        assert len(shutdown_loss_records) == 0

    async def test_start_creates_background_task(self):
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        assert queue._flush_task is None
        await queue.start()
        assert queue._flush_task is not None
        await queue.stop()
