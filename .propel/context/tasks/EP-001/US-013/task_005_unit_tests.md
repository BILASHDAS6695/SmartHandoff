---
id: TASK-005
title: "Write pytest Unit Tests — GCS Archiver, Fallback Queue, Idempotency Checker (All 4 Scenarios)"
user_story: US-013
epic: EP-001
sprint: 1
layer: Testing
estimate: 2.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-013/TASK-001, US-013/TASK-002, US-013/TASK-003, US-013/TASK-004]
---

# TASK-005: Write pytest Unit Tests — GCS Archiver, Fallback Queue, Idempotency Checker (All 4 Scenarios)

> **Story:** US-013 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-013 DoD specifies:

> *"Unit tests: (a) archive path format, (b) duplicate detection, (c) GCS failure retry"*

All 4 acceptance criteria scenarios must be covered. Tests are split across three test files matching the three production modules:

| Test File | Module Under Test | Coverage Focus |
|-----------|------------------|----------------|
| `test_gcs_archiver.py` | `app/archive/gcs_archiver.py` | Path format, successful upload, retry on failure, fallback delegation |
| `test_fallback_queue.py` | `app/archive/fallback_queue.py` | Enqueue, background flush, stop on shutdown, bounded overflow |
| `test_idempotency_checker.py` | `app/idempotency/idempotency_checker.py` | Duplicate detection, new message pass-through, DB error fail-open |

Coverage target: ≥80% branch coverage on all three modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---------------------|---------------|
| `google.cloud.storage.Client` | `unittest.mock.MagicMock` patched at `app.archive.gcs_archiver.storage.Client` |
| `asyncio.sleep` | `AsyncMock` patched to avoid real delays in retry tests |
| `sqlalchemy.ext.asyncio.AsyncSession` | `AsyncMock` with `.execute()` returning a mock scalar result |
| `FallbackQueue.enqueue` | `AsyncMock` injected into `GCSArchiver` constructor |

---

## Acceptance Criteria Addressed

| US-013 AC | Test Case(s) |
|---|---|
| **Scenario 1** | `test_gcs_archiver.py::test_archive_calls_upload_before_returning` |
| **Scenario 2** | `test_idempotency_checker.py::test_is_duplicate_returns_true_for_known_id`, `test_pipeline_returns_ack_without_publishing_on_duplicate` |
| **Scenario 3** | `test_gcs_archiver.py::test_build_archive_path_date_partitioned` (parametrised) |
| **Scenario 4** | `test_gcs_archiver.py::test_archive_retries_three_times_on_failure`, `test_archive_delegates_to_fallback_after_all_retries` |
| **DoD** | Full test suite; ≥80% coverage; fixtures in `tests/fixtures/hl7/` reused |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p hl7-listener/tests/unit/archive
mkdir -p hl7-listener/tests/unit/idempotency
touch hl7-listener/tests/unit/archive/__init__.py
touch hl7-listener/tests/unit/idempotency/__init__.py
```

### 2. Create `hl7-listener/tests/unit/archive/test_gcs_archiver.py`

```python
"""Unit tests for app/archive/gcs_archiver.py.

DoD coverage:
  (a) Archive path format — date-partitioned {YYYY}/{MM}/{DD}/{msg_id}.hl7
  (c) GCS failure retry  — 3 attempts, exponential backoff, fallback delegation

Tests do NOT make real GCS API calls.  The GCS SDK client is mocked at the
module level.
"""
from __future__ import annotations

import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from google.api_core.exceptions import ServiceUnavailable

from app.archive.gcs_archiver import GCSArchiver, build_archive_path


# ---------------------------------------------------------------------------
# Tests for build_archive_path() — DoD (a): archive path format
# ---------------------------------------------------------------------------

class TestBuildArchivePath:
    """Scenario 3: date-partitioned archive path."""

    @pytest.mark.parametrize("year, month, day, msg_id, expected_prefix", [
        (2026, 7, 15, "MSG-001",       "2026/07/15/MSG-001.hl7"),
        (2026, 1,  5, "MSG-X",         "2026/01/05/MSG-X.hl7"),
        (2026, 12, 31, "MSG-20261231", "2026/12/31/MSG-20261231.hl7"),
    ])
    def test_path_format_is_date_partitioned(self, year, month, day, msg_id, expected_prefix):
        """Archive path must be {YYYY}/{MM}/{DD}/{msg_control_id}.hl7 (SC-3)."""
        ts = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
        assert build_archive_path(msg_id, ts) == expected_prefix

    def test_empty_msg_control_id_raises_value_error(self):
        ts = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
        with pytest.raises(ValueError, match="msg_control_id"):
            build_archive_path("", ts)

    def test_whitespace_msg_control_id_raises_value_error(self):
        ts = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
        with pytest.raises(ValueError, match="msg_control_id"):
            build_archive_path("   ", ts)

    def test_non_utc_timestamp_is_normalised(self):
        """Timestamp in a non-UTC timezone is converted to UTC for path partitioning."""
        # +05:30 offset — UTC date should be the previous day
        tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts = datetime.datetime(2026, 7, 15, 2, 0, 0, tzinfo=tz)  # = 2026-07-14T20:30Z
        path = build_archive_path("MSG-TZ", ts)
        assert path.startswith("2026/07/14/")


# ---------------------------------------------------------------------------
# Tests for GCSArchiver.archive() — DoD (a) and (c)
# ---------------------------------------------------------------------------

_RAW_HL7 = (
    "MSH|^~\\&|EHR|HOSP|SmartHandoff|HOSP|20260715100000||ADT^A01|MSG-001|P|2.5\r"
    "EVN|A01|20260715095500\r"
    "PID|1||MRN-1001^^^HOSP^MR||Smith^John||19800115|M\r"
)
_MSG_CONTROL_ID = "MSG-001"
_ARRIVED_AT = datetime.datetime(2026, 7, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)


def _make_archiver(fallback_queue: AsyncMock | None = None) -> GCSArchiver:
    archiver = GCSArchiver(bucket_name="test-hl7-archive", fallback_queue=fallback_queue)
    return archiver


@pytest.mark.asyncio
class TestGCSArchiverSuccess:
    """Scenario 1: successful upload."""

    async def test_archive_calls_upload_before_returning(self):
        """GCS upload_from_string() must be called; archive() returns True."""
        archiver = _make_archiver()
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        archiver._client = mock_client

        result = await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        assert result is True
        mock_blob.upload_from_string.assert_called_once_with(
            data=_RAW_HL7,
            content_type="text/plain",
        )

    async def test_archive_sets_metadata_without_phi(self):
        """GCS blob metadata must contain only message_id and upload_timestamp — no PHI."""
        archiver = _make_archiver()
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        archiver._client = MagicMock()
        archiver._client.bucket.return_value = mock_bucket

        await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        metadata = mock_blob.metadata
        assert set(metadata.keys()) == {"message_id", "upload_timestamp"}
        assert metadata["message_id"] == _MSG_CONTROL_ID
        # No patient data in metadata
        phi_fields = {"patient", "mrn", "dob", "name", "first", "last"}
        for key in metadata:
            assert not any(phi in key.lower() for phi in phi_fields)

    async def test_archive_path_passed_to_blob(self):
        """blob() must be called with the date-partitioned path."""
        archiver = _make_archiver()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = MagicMock()
        archiver._client = MagicMock()
        archiver._client.bucket.return_value = mock_bucket

        await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        expected_path = "2026/07/15/MSG-001.hl7"
        mock_bucket.blob.assert_called_once_with(expected_path)


@pytest.mark.asyncio
class TestGCSArchiverRetry:
    """Scenario 4: GCS failure → 3 retries → fallback delegation — DoD (c)."""

    @patch("app.archive.gcs_archiver.asyncio.sleep", new_callable=AsyncMock)
    async def test_archive_retries_three_times_on_failure(self, mock_sleep):
        """On transient GCS error, upload is retried exactly 3 times."""
        archiver = _make_archiver(fallback_queue=AsyncMock())
        mock_blob = MagicMock()
        mock_blob.upload_from_string.side_effect = ServiceUnavailable("GCS down")
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        archiver._client = MagicMock()
        archiver._client.bucket.return_value = mock_bucket

        result = await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        assert result is False
        assert mock_blob.upload_from_string.call_count == 3

    @patch("app.archive.gcs_archiver.asyncio.sleep", new_callable=AsyncMock)
    async def test_archive_uses_exponential_backoff_delays(self, mock_sleep):
        """Retry delays must be 1 s, 2 s (last retry has no sleep after it)."""
        archiver = _make_archiver(fallback_queue=AsyncMock())
        mock_blob = MagicMock()
        mock_blob.upload_from_string.side_effect = ServiceUnavailable("GCS down")
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        archiver._client = MagicMock()
        archiver._client.bucket.return_value = mock_bucket

        await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert sleep_calls == [1.0, 2.0]  # 3 attempts → 2 inter-attempt sleeps

    @patch("app.archive.gcs_archiver.asyncio.sleep", new_callable=AsyncMock)
    async def test_archive_delegates_to_fallback_after_all_retries(self, mock_sleep):
        """After all retries exhausted, FallbackQueue.enqueue() must be called."""
        fallback_queue = AsyncMock()
        archiver = _make_archiver(fallback_queue=fallback_queue)
        mock_blob = MagicMock()
        mock_blob.upload_from_string.side_effect = ServiceUnavailable("GCS down")
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        archiver._client = MagicMock()
        archiver._client.bucket.return_value = mock_bucket

        await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        fallback_queue.enqueue.assert_awaited_once_with(
            _RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT
        )

    @patch("app.archive.gcs_archiver.asyncio.sleep", new_callable=AsyncMock)
    async def test_archive_succeeds_on_second_attempt(self, mock_sleep):
        """Transient failure on attempt 1 but success on attempt 2 → True returned."""
        archiver = _make_archiver()
        mock_blob = MagicMock()
        mock_blob.upload_from_string.side_effect = [
            ServiceUnavailable("transient"),
            None,  # second attempt succeeds
        ]
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        archiver._client = MagicMock()
        archiver._client.bucket.return_value = mock_bucket

        result = await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        assert result is True
        assert mock_blob.upload_from_string.call_count == 2
```

### 3. Create `hl7-listener/tests/unit/archive/test_fallback_queue.py`

```python
"""Unit tests for app/archive/fallback_queue.py."""
from __future__ import annotations

import asyncio
import datetime
from unittest.mock import AsyncMock

import pytest

from app.archive.fallback_queue import FallbackQueue

_ARRIVED_AT = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)


@pytest.mark.asyncio
class TestFallbackQueueEnqueue:
    async def test_enqueue_increases_depth(self):
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        assert queue.depth == 0
        await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        assert queue.depth == 1

    async def test_enqueue_bounded_at_500(self):
        """Queue does not exceed 500 — oldest entry is evicted on overflow."""
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        for i in range(501):
            await queue.enqueue(f"HL7MSG-{i}", f"MSG-{i:04d}", _ARRIVED_AT)
        assert queue.depth == 500  # maxlen enforced


@pytest.mark.asyncio
class TestFallbackQueueFlush:
    async def test_flush_removes_successfully_archived_entries(self):
        """Entries successfully re-archived are removed from the queue."""
        mock_archiver = AsyncMock()
        mock_archiver.archive.return_value = True  # GCS succeeds on retry
        queue = FallbackQueue(archiver=mock_archiver)
        await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        await queue._flush_all()
        assert queue.depth == 0

    async def test_flush_retains_entries_that_still_fail(self):
        """Entries that still fail to archive remain in the queue for next cycle."""
        mock_archiver = AsyncMock()
        mock_archiver.archive.return_value = False  # GCS still failing
        queue = FallbackQueue(archiver=mock_archiver)
        await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        await queue._flush_all()
        assert queue.depth == 1


@pytest.mark.asyncio
class TestFallbackQueueShutdown:
    async def test_stop_logs_remaining_entries(self, caplog):
        """stop() logs remaining unprocessed entries at ERROR level."""
        import logging
        mock_archiver = AsyncMock()
        queue = FallbackQueue(archiver=mock_archiver)
        await queue.start()
        await queue.enqueue("HL7MSG", "MSG-001", _ARRIVED_AT)
        with caplog.at_level(logging.ERROR):
            await queue.stop()
        assert "unprocessed" in caplog.text.lower() or "remaining" in caplog.text.lower()
```

### 4. Create `hl7-listener/tests/unit/idempotency/test_idempotency_checker.py`

```python
"""Unit tests for app/idempotency/idempotency_checker.py.

DoD coverage:
  (b) Duplicate detection — is_duplicate() returns True for known MSH-10
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.idempotency.idempotency_checker import IdempotencyChecker


def _make_session(exists: bool) -> AsyncMock:
    """Build a mock AsyncSession whose execute() returns ``exists``."""
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = exists
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result
    return mock_session


@pytest.mark.asyncio
class TestIdempotencyCheckerDuplicate:
    """Scenario 2: duplicate detection."""

    async def test_is_duplicate_returns_true_for_known_id(self):
        """Known source_message_id → is_duplicate() returns True (SC-2)."""
        checker = IdempotencyChecker()
        session = _make_session(exists=True)
        result = await checker.is_duplicate(session, "MSG-20260714-001")
        assert result is True

    async def test_is_duplicate_returns_false_for_new_id(self):
        """Unknown source_message_id → is_duplicate() returns False."""
        checker = IdempotencyChecker()
        session = _make_session(exists=False)
        result = await checker.is_duplicate(session, "MSG-NEW-999")
        assert result is False

    async def test_duplicate_emits_structured_log(self, caplog):
        """Duplicate detection emits duplicate_message_skipped structured log."""
        import logging
        checker = IdempotencyChecker()
        session = _make_session(exists=True)
        with caplog.at_level(logging.INFO):
            await checker.is_duplicate(session, "MSG-DUP-001")
        assert "duplicate_message_skipped" in caplog.text

    async def test_uses_parameterised_query_not_string_interpolation(self):
        """execute() must be called with a bindparam dict, not a formatted string."""
        checker = IdempotencyChecker()
        session = _make_session(exists=False)
        await checker.is_duplicate(session, "MSG-PARAM-TEST")
        # The second argument to session.execute() must contain the msg_id binding
        call_args = session.execute.call_args
        _, kwargs_or_params = call_args.args if len(call_args.args) > 1 else (None, call_args.kwargs)
        # Verify the parameterised dict was passed (not raw string formatting)
        if len(call_args.args) >= 2:
            params = call_args.args[1]
        else:
            params = call_args.kwargs.get("params", {})
        assert "msg_id" in params
        assert params["msg_id"] == "MSG-PARAM-TEST"
```

### 5. Run the test suite

```bash
cd hl7-listener
pip install -r requirements.txt pytest pytest-asyncio

# Run with coverage
pytest tests/unit/archive/ tests/unit/idempotency/ \
    --cov=app/archive --cov=app/idempotency \
    --cov-report=term-missing \
    --cov-fail-under=80 \
    -v
```

---

## File Structure After This Task

```
hl7-listener/
└── tests/
    └── unit/
        ├── archive/
        │   ├── __init__.py
        │   ├── test_gcs_archiver.py        ← THIS TASK
        │   └── test_fallback_queue.py      ← THIS TASK
        └── idempotency/
            ├── __init__.py
            └── test_idempotency_checker.py ← THIS TASK
```

---

## Definition of Done Checklist (this task)

- [ ] `test_build_archive_path_date_partitioned` covers parametrised date scenarios (SC-3 / DoD-a)
- [ ] `test_archive_calls_upload_before_returning` confirms GCS upload called (SC-1)
- [ ] `test_archive_retries_three_times_on_failure` confirms exactly 3 attempts (SC-4 / DoD-c)
- [ ] `test_archive_uses_exponential_backoff_delays` confirms 1 s / 2 s delays
- [ ] `test_archive_delegates_to_fallback_after_all_retries` confirms `FallbackQueue.enqueue()` called
- [ ] `test_is_duplicate_returns_true_for_known_id` covers SC-2 (DoD-b)
- [ ] `test_duplicate_emits_structured_log` confirms `duplicate_message_skipped` log
- [ ] `test_uses_parameterised_query_not_string_interpolation` confirms SQL injection prevention
- [ ] All tests pass; ≥80% branch coverage on `app/archive/` and `app/idempotency/`
