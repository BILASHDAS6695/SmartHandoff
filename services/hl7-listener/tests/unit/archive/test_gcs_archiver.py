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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.api_core.exceptions import ServiceUnavailable  # type: ignore[import]

from app.archive.gcs_archiver import GCSArchiver, build_archive_path


# ---------------------------------------------------------------------------
# Tests for build_archive_path() — DoD (a): archive path format
# ---------------------------------------------------------------------------

class TestBuildArchivePath:
    """Scenario 3: date-partitioned archive path."""

    @pytest.mark.parametrize("year, month, day, msg_id, expected", [
        (2026, 7,  15, "MSG-001",       "2026/07/15/MSG-001.hl7"),
        (2026, 1,   5, "MSG-X",         "2026/01/05/MSG-X.hl7"),
        (2026, 12, 31, "MSG-20261231",  "2026/12/31/MSG-20261231.hl7"),
    ])
    def test_path_format_is_date_partitioned(self, year, month, day, msg_id, expected):
        """Archive path must be {YYYY}/{MM}/{DD}/{msg_control_id}.hl7 (SC-3)."""
        ts = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
        assert build_archive_path(msg_id, ts) == expected

    def test_empty_msg_control_id_raises_value_error(self):
        ts = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
        with pytest.raises(ValueError, match="msg_control_id"):
            build_archive_path("", ts)

    def test_whitespace_msg_control_id_raises_value_error(self):
        ts = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
        with pytest.raises(ValueError, match="msg_control_id"):
            build_archive_path("   ", ts)

    def test_non_utc_timestamp_is_normalised(self):
        """Timestamp in a non-UTC timezone is converted to UTC for path partition."""
        # UTC+05:30 — the UTC date should be the previous day for early-morning times
        tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        ts = datetime.datetime(2026, 7, 15, 2, 0, 0, tzinfo=tz)  # = 2026-07-14T20:30Z
        path = build_archive_path("MSG-TZ", ts)
        assert path.startswith("2026/07/14/")

    def test_path_ends_with_hl7_extension(self):
        ts = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
        path = build_archive_path("MSG-001", ts)
        assert path.endswith(".hl7")

    def test_path_contains_msg_control_id(self):
        ts = datetime.datetime(2026, 7, 15, tzinfo=datetime.timezone.utc)
        path = build_archive_path("MY-MSG-ID", ts)
        assert "MY-MSG-ID" in path


# ---------------------------------------------------------------------------
# Helpers for GCSArchiver tests
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


def _attach_mock_client(archiver: GCSArchiver) -> MagicMock:
    """Attach a mock GCS client to archiver and return the mock blob."""
    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    archiver._client = mock_client
    return mock_blob


# ---------------------------------------------------------------------------
# Tests for GCSArchiver.archive() — successful upload (SC-1 / DoD-a)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGCSArchiverSuccess:
    """Scenario 1: successful upload."""

    async def test_archive_calls_upload_before_returning(self):
        """GCS upload_from_string() must be called; archive() returns True."""
        archiver = _make_archiver()
        mock_blob = _attach_mock_client(archiver)

        result = await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        assert result is True
        mock_blob.upload_from_string.assert_called_once_with(
            data=_RAW_HL7,
            content_type="text/plain",
        )

    async def test_archive_returns_true_on_success(self):
        archiver = _make_archiver()
        _attach_mock_client(archiver)
        result = await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)
        assert result is True

    async def test_archive_sets_metadata_without_phi(self):
        """GCS blob metadata must contain only message_id and upload_timestamp — no PHI."""
        archiver = _make_archiver()
        mock_blob = _attach_mock_client(archiver)

        await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        metadata = mock_blob.metadata
        assert set(metadata.keys()) == {"message_id", "upload_timestamp"}
        assert metadata["message_id"] == _MSG_CONTROL_ID
        # Confirm no PHI field names in metadata keys
        phi_fields = {"patient", "mrn", "dob", "name", "first", "last", "address"}
        for key in metadata:
            assert not any(phi in key.lower() for phi in phi_fields)

    async def test_archive_path_passed_to_blob(self):
        """blob() must be called with the date-partitioned path."""
        archiver = _make_archiver()
        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        archiver._client = MagicMock()
        archiver._client.bucket.return_value = mock_bucket

        await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)

        expected_path = "2026/07/15/MSG-001.hl7"
        mock_bucket.blob.assert_called_once_with(expected_path)


# ---------------------------------------------------------------------------
# Tests for GCSArchiver retry + fallback (SC-4 / DoD-c)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGCSArchiverRetry:
    """Scenario 4: GCS failure → 3 retries → fallback delegation."""

    @patch("app.archive.gcs_archiver.asyncio.sleep", new_callable=AsyncMock)
    async def test_archive_retries_three_times_on_failure(self, mock_sleep):
        """On transient GCS error, upload is attempted exactly 3 times."""
        fallback = AsyncMock()
        archiver = _make_archiver(fallback_queue=fallback)
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
        fallback = AsyncMock()
        archiver = _make_archiver(fallback_queue=fallback)
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
        """Transient failure on attempt 1, success on attempt 2 → True returned."""
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

    @patch("app.archive.gcs_archiver.asyncio.sleep", new_callable=AsyncMock)
    async def test_archive_returns_false_when_fallback_used(self, mock_sleep):
        """archive() returns False when all retries fail and fallback is invoked."""
        fallback = AsyncMock()
        archiver = _make_archiver(fallback_queue=fallback)
        mock_blob = MagicMock()
        mock_blob.upload_from_string.side_effect = ServiceUnavailable("GCS down")
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        archiver._client = MagicMock()
        archiver._client.bucket.return_value = mock_bucket

        result = await archiver.archive(_RAW_HL7, _MSG_CONTROL_ID, _ARRIVED_AT)
        assert result is False
