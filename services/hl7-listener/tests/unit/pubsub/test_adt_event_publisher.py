"""Unit tests for app/pubsub/adt_event_publisher.py.

Coverage:
  SC-1: message body schema and ordering key
  SC-2: ordering key is encounter_id for FIFO
  SC-3: retry on transient error; retry queue delegation; Prometheus counter
  SC-4: message attributes — event_type, encounter_id, patient_mrn_hash,
        iso_timestamp; no raw MRN in attributes

Tests do NOT make real Pub/Sub API calls.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.api_core.exceptions import ServiceUnavailable

from app.pubsub.adt_event_publisher import (
    ADTEventPublisher,
    _build_attributes,
    _RETRY_DELAYS,
)
from tests.factories.adt_event_factory import make_adt_event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_retry_queue() -> AsyncMock:
    q = AsyncMock()
    q.enqueue = AsyncMock()
    return q


@pytest.fixture()
def mock_pubsub_client() -> MagicMock:
    client = MagicMock()
    future = MagicMock()
    future.result.return_value = "msg-id-001"
    client.publish.return_value = future
    return client


@pytest.fixture()
def publisher(mock_retry_queue, mock_pubsub_client) -> ADTEventPublisher:
    pub = ADTEventPublisher(
        retry_queue=mock_retry_queue,
        project_id="test-project",
        topic_id="adt-events",
    )
    pub._client = mock_pubsub_client
    return pub


@pytest.fixture()
def sample_event():
    return make_adt_event(event_type="ADMIT")


# ---------------------------------------------------------------------------
# Scenario 1 & 2: Message body schema and ordering key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_body_is_json_serialised_adt_event(publisher, sample_event, mock_pubsub_client):
    """SC-1: Message body = UTF-8 JSON of the full ADTEvent."""
    await publisher.publish(sample_event)

    call_kwargs = mock_pubsub_client.publish.call_args
    data_arg: bytes = call_kwargs[0][1]  # positional: (topic_path, data, ...)
    parsed = json.loads(data_arg.decode("utf-8"))

    assert "encounter_id" in parsed
    assert "event_type" in parsed
    assert parsed["encounter_id"] == str(sample_event.encounter_id)


@pytest.mark.asyncio
async def test_publish_sets_ordering_key_to_encounter_id(publisher, sample_event, mock_pubsub_client):
    """SC-1 & SC-2: ordering_key must equal encounter_id string."""
    await publisher.publish(sample_event)

    call_kwargs = mock_pubsub_client.publish.call_args
    ordering_key: str = call_kwargs[1]["ordering_key"]

    assert ordering_key == str(sample_event.encounter_id)


@pytest.mark.asyncio
async def test_publish_ordering_key_is_encounter_id_string(publisher, mock_pubsub_client):
    """SC-2: Different encounters get different ordering keys."""
    enc_a = uuid.uuid4()
    enc_b = uuid.uuid4()
    event_a = make_adt_event(encounter_id=enc_a, event_type="ADMIT")
    event_b = make_adt_event(encounter_id=enc_b, event_type="ADMIT")

    await publisher.publish(event_a)
    await publisher.publish(event_b)

    calls = mock_pubsub_client.publish.call_args_list
    key_a = calls[0][1]["ordering_key"]
    key_b = calls[1][1]["ordering_key"]

    assert key_a == str(enc_a)
    assert key_b == str(enc_b)
    assert key_a != key_b


# ---------------------------------------------------------------------------
# Scenario 3: Retry logic and retry queue delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_retries_three_times_on_transient_error(
    publisher, sample_event, mock_pubsub_client
):
    """SC-3: Transient ServiceUnavailable → exactly 3 publish attempts."""
    error = ServiceUnavailable("Pub/Sub unavailable")
    mock_pubsub_client.publish.return_value.result.side_effect = error

    with patch("app.pubsub.adt_event_publisher.asyncio.sleep", new_callable=AsyncMock):
        await publisher.publish(sample_event)

    assert mock_pubsub_client.publish.call_count == len(_RETRY_DELAYS)


@pytest.mark.asyncio
async def test_publish_delegates_to_retry_queue_after_all_retries(
    publisher, sample_event, mock_pubsub_client, mock_retry_queue
):
    """SC-3: After all retries, event enqueued to PublishRetryQueue."""
    mock_pubsub_client.publish.return_value.result.side_effect = ServiceUnavailable("error")

    with patch("app.pubsub.adt_event_publisher.asyncio.sleep", new_callable=AsyncMock):
        await publisher.publish(sample_event)

    mock_retry_queue.enqueue.assert_awaited_once_with(sample_event)


@pytest.mark.asyncio
async def test_pubsub_failures_counter_incremented_on_exhaustion(
    publisher, sample_event, mock_pubsub_client
):
    """SC-3: pubsub_publish_failures_total Prometheus counter incremented."""
    from app.pubsub.adt_event_publisher import PUBSUB_PUBLISH_FAILURES

    mock_pubsub_client.publish.return_value.result.side_effect = ServiceUnavailable("error")
    event_type = sample_event.event_type.value
    before = PUBSUB_PUBLISH_FAILURES.labels(event_type=event_type)._value.get()

    with patch("app.pubsub.adt_event_publisher.asyncio.sleep", new_callable=AsyncMock):
        await publisher.publish(sample_event)

    after = PUBSUB_PUBLISH_FAILURES.labels(event_type=event_type)._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_publish_succeeds_on_second_attempt(
    publisher, sample_event, mock_pubsub_client, mock_retry_queue
):
    """SC-3: First attempt fails, second succeeds — no queue enqueue."""
    call_count = 0

    def side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ServiceUnavailable("transient")
        return "msg-id"

    mock_pubsub_client.publish.return_value.result.side_effect = side_effect

    with patch("app.pubsub.adt_event_publisher.asyncio.sleep", new_callable=AsyncMock):
        await publisher.publish(sample_event)

    mock_retry_queue.enqueue.assert_not_awaited()
    assert mock_pubsub_client.publish.call_count == 2


@pytest.mark.asyncio
async def test_publish_exponential_backoff_delays(
    publisher, sample_event, mock_pubsub_client
):
    """SC-3: Retry delays must be 1 s then 2 s (2 inter-attempt sleeps for 3 attempts)."""
    mock_pubsub_client.publish.return_value.result.side_effect = ServiceUnavailable("error")

    with patch("app.pubsub.adt_event_publisher.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await publisher.publish(sample_event)

    sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
    assert sleep_calls == [1.0, 2.0]


# ---------------------------------------------------------------------------
# Scenario 4: Message attributes — SC-4
# ---------------------------------------------------------------------------


def test_build_attributes_contains_all_required_keys(sample_event):
    """SC-4: Attributes must contain event_type, encounter_id, patient_mrn_hash, iso_timestamp."""
    attrs = _build_attributes(sample_event)

    assert set(attrs.keys()) == {
        "event_type",
        "encounter_id",
        "patient_mrn_hash",
        "iso_timestamp",
    }


def test_build_attributes_mrn_hash_is_sha256(sample_event):
    """SC-4: patient_mrn_hash is SHA-256 hex of the MRN, not the raw MRN."""
    attrs = _build_attributes(sample_event)
    mrn_hash = attrs["patient_mrn_hash"]

    expected = hashlib.sha256(str(sample_event.patient_mrn).encode("utf-8")).hexdigest()
    assert mrn_hash == expected
    assert len(mrn_hash) == 64  # SHA-256 produces 64 hex chars


def test_build_attributes_no_raw_mrn(sample_event):
    """SC-4 / BR-020: Raw MRN must NOT appear in any attribute value."""
    attrs = _build_attributes(sample_event)
    raw_mrn = str(sample_event.patient_mrn)

    for key, value in attrs.items():
        assert raw_mrn not in value, (
            f"Raw MRN found in attribute '{key}': PHI leak violation (BR-020)"
        )


def test_build_attributes_event_type_matches_event(sample_event):
    """SC-4: event_type attribute matches ADTEvent.event_type.value."""
    attrs = _build_attributes(sample_event)
    assert attrs["event_type"] == sample_event.event_type.value


def test_build_attributes_encounter_id_matches_ordering_key(sample_event):
    """SC-1 & SC-4: encounter_id attribute matches the ordering key value."""
    attrs = _build_attributes(sample_event)
    assert attrs["encounter_id"] == str(sample_event.encounter_id)


def test_retry_delays_are_correct():
    """DoD: _RETRY_DELAYS must be exactly (1.0, 2.0, 4.0)."""
    assert _RETRY_DELAYS == (1.0, 2.0, 4.0)


# ---------------------------------------------------------------------------
# TR-017: Graceful shutdown — close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_stops_pubsub_client(mock_retry_queue, mock_pubsub_client):
    """TR-017: close() must call client.stop() for graceful Pub/Sub shutdown."""
    pub = ADTEventPublisher(
        retry_queue=mock_retry_queue,
        project_id="test-project",
        topic_id="adt-events",
    )
    pub._client = mock_pubsub_client

    await pub.close()

    mock_pubsub_client.stop.assert_called_once()


@pytest.mark.asyncio
async def test_close_shuts_down_executor(mock_retry_queue, mock_pubsub_client):
    """TR-017: close() must call executor.shutdown() to release thread-pool resources."""
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import MagicMock

    mock_executor = MagicMock(spec=ThreadPoolExecutor)
    pub = ADTEventPublisher(
        retry_queue=mock_retry_queue,
        project_id="test-project",
        topic_id="adt-events",
        executor=mock_executor,
    )
    pub._client = mock_pubsub_client

    await pub.close()

    mock_executor.shutdown.assert_called_once_with(wait=False)
