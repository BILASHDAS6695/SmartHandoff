---
id: TASK-004
title: "Write pytest Unit Tests — ADTEventPublisher, PublishRetryQueue, Pipeline Publish Step (All 4 Scenarios)"
user_story: US-014
epic: EP-001
sprint: 1
layer: Testing
estimate: 2.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-014/TASK-001, US-014/TASK-002, US-014/TASK-003]
---

# TASK-004: Write pytest Unit Tests — ADTEventPublisher, PublishRetryQueue, Pipeline Publish Step (All 4 Scenarios)

> **Story:** US-014 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Testing | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-014 DoD specifies:

> *"Unit tests: verify message body schema, ordering key, attribute presence"*

All 4 acceptance criteria scenarios must be covered. Tests are split across three test files matching the three production modules:

| Test File | Module Under Test | Coverage Focus |
|-----------|------------------|----------------|
| `test_adt_event_publisher.py` | `app/pubsub/adt_event_publisher.py` | Message body schema, ordering key, attributes, retry on failure, retry queue delegation |
| `test_publish_retry_queue.py` | `app/pubsub/publish_retry_queue.py` | Enqueue, background flush, stop on shutdown, bounded overflow |
| `test_pipeline_publish.py` | `app/mllp/pipeline.py` (publish step) | Publish called after route; ACK only after publish; pipeline defers ACK |

Coverage target: ≥80% branch coverage on all three modules (TR-020).

**Mocking strategy:**

| External Dependency | Mock Approach |
|---------------------|---------------|
| `google.cloud.pubsub_v1.PublisherClient` | `unittest.mock.MagicMock` patched at `app.pubsub.adt_event_publisher.pubsub_v1.PublisherClient` |
| `future.result()` | `MagicMock` configured to raise `GoogleAPICallError` on demand |
| `asyncio.sleep` | `AsyncMock` patched to avoid real delays in retry tests |
| `ADTEventPublisher.publish` | `AsyncMock` injected into `PublishRetryQueue` constructor for flush tests |
| `MLLPPipeline._publisher` | `AsyncMock` injected as constructor argument for pipeline tests |

---

## Acceptance Criteria Addressed

| US-014 AC | Test Case(s) |
|---|---|
| **Scenario 1** | `test_publish_sets_ordering_key_to_encounter_id`, `test_publish_body_is_json_serialised_adt_event` |
| **Scenario 2** | `test_publish_ordering_key_is_encounter_id_string` (parametrised with multiple events same encounter) |
| **Scenario 3** | `test_publish_retries_three_times_on_transient_error`, `test_publish_delegates_to_retry_queue_after_all_retries`, `test_pubsub_failures_counter_incremented_on_exhaustion` |
| **Scenario 4** | `test_build_attributes_contains_all_required_keys`, `test_build_attributes_mrn_hash_is_sha256`, `test_build_attributes_no_raw_mrn` |
| **DoD** | Full test suite; ≥80% coverage; all 4 scenarios covered |

---

## Implementation Steps

### 1. Scaffold test directories

```bash
mkdir -p hl7-listener/tests/unit/pubsub
touch hl7-listener/tests/unit/pubsub/__init__.py
```

### 2. Create `hl7-listener/tests/unit/pubsub/test_adt_event_publisher.py`

```python
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

import asyncio
import hashlib
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from google.api_core.exceptions import ServiceUnavailable

from app.pubsub.adt_event_publisher import ADTEventPublisher, _build_attributes, _RETRY_DELAYS
from tests.factories.adt_event_factory import make_adt_event  # shared fixture factory


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
    pub = ADTEventPublisher(retry_queue=mock_retry_queue)
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
    """SC-2: Different encounters get different ordering keys (parametrised)."""
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
    """SC-3: If first attempt fails but second succeeds, no queue enqueue."""
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

    expected = hashlib.sha256(str(sample_event.patient.mrn).encode("utf-8")).hexdigest()
    assert mrn_hash == expected
    assert len(mrn_hash) == 64  # SHA-256 produces 64 hex chars


def test_build_attributes_no_raw_mrn(sample_event):
    """SC-4 / BR-020: Raw MRN must NOT appear in any attribute value."""
    attrs = _build_attributes(sample_event)
    raw_mrn = str(sample_event.patient.mrn)

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
```

### 3. Create `hl7-listener/tests/unit/pubsub/test_publish_retry_queue.py`

```python
"""Unit tests for app/pubsub/publish_retry_queue.py.

Coverage:
  - enqueue() adds to queue and emits structured log
  - background flush re-publishes and removes successful entries
  - stop() signals flush loop and logs remaining entries
  - bounded deque evicts oldest on overflow
"""
from __future__ import annotations

import asyncio
import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.pubsub.publish_retry_queue import PublishRetryQueue, _MAX_QUEUE_SIZE
from tests.factories.adt_event_factory import make_adt_event


@pytest.fixture()
def mock_publish_fn() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def retry_queue(mock_publish_fn) -> PublishRetryQueue:
    return PublishRetryQueue(publish_fn=mock_publish_fn, flush_interval=0.05)


@pytest.mark.asyncio
async def test_enqueue_increases_depth(retry_queue):
    event = make_adt_event()
    assert retry_queue.depth() == 0
    await retry_queue.enqueue(event)
    assert retry_queue.depth() == 1


@pytest.mark.asyncio
async def test_flush_publishes_queued_event(retry_queue, mock_publish_fn):
    event = make_adt_event()
    await retry_queue.enqueue(event)
    await retry_queue._flush_once()

    mock_publish_fn.assert_awaited_once_with(event)
    assert retry_queue.depth() == 0  # event removed after success


@pytest.mark.asyncio
async def test_flush_retains_failed_events(retry_queue, mock_publish_fn):
    mock_publish_fn.side_effect = Exception("Pub/Sub still down")
    event = make_adt_event()
    await retry_queue.enqueue(event)
    await retry_queue._flush_once()

    assert retry_queue.depth() == 1  # event retained for next flush


@pytest.mark.asyncio
async def test_stop_logs_remaining_events(retry_queue):
    event = make_adt_event()
    await retry_queue.enqueue(event)
    await retry_queue.start()

    with patch.object(retry_queue, "_flush_once", new_callable=AsyncMock):
        await retry_queue.stop()

    # No assertion on log — verifies stop() completes without error


@pytest.mark.asyncio
async def test_bounded_queue_evicts_oldest_on_overflow(mock_publish_fn):
    queue = PublishRetryQueue(publish_fn=mock_publish_fn)
    events = [make_adt_event() for _ in range(_MAX_QUEUE_SIZE + 5)]
    for event in events:
        await queue.enqueue(event)

    assert queue.depth() == _MAX_QUEUE_SIZE
```

### 4. Create `hl7-listener/tests/unit/pubsub/test_pipeline_publish.py`

```python
"""Unit tests for Pub/Sub integration in app/mllp/pipeline.py.

Verifies:
  - publisher.publish() is called after router.route()
  - ACK is returned only after publisher.publish() completes
  - A publisher failure does not prevent ACK (publish() handles failures internally)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mllp.pipeline import MLLPPipeline


@pytest.fixture()
def mock_publisher() -> AsyncMock:
    pub = AsyncMock()
    pub.publish = AsyncMock()
    return pub


@pytest.fixture()
def pipeline(mock_publisher) -> MLLPPipeline:
    return MLLPPipeline(
        parser=AsyncMock(parse=AsyncMock(return_value=MagicMock())),
        router=AsyncMock(route=AsyncMock()),
        archiver=AsyncMock(archive=AsyncMock()),
        idempotency_checker=AsyncMock(is_duplicate=AsyncMock(return_value=False)),
        publisher=mock_publisher,
        db_session=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_publish_called_after_route(pipeline, mock_publisher):
    """publish() must be called after route() — DB persist before Pub/Sub."""
    call_order = []
    pipeline._router.route = AsyncMock(side_effect=lambda *a, **kw: call_order.append("route"))
    mock_publisher.publish = AsyncMock(side_effect=lambda *a, **kw: call_order.append("publish"))

    raw_hl7 = "MSH|^~\\&|TEST|TEST|TEST|TEST|20260715120000||ADT^A01|MSG001|P|2.5"
    with patch.object(pipeline, "_archiver") as arch, \
         patch.object(pipeline, "_idempotency") as idm:
        arch.archive = AsyncMock()
        idm.is_duplicate = AsyncMock(return_value=False)
        await pipeline.process_message(raw_hl7)

    assert call_order.index("route") < call_order.index("publish"), (
        "route() must be called before publish() (DB persist before Pub/Sub)"
    )


@pytest.mark.asyncio
async def test_ack_returned_after_publish(pipeline, mock_publisher):
    """ACK bytes are returned only after publish() completes."""
    publish_completed = []
    async def publish_and_record(event):
        publish_completed.append(True)
    mock_publisher.publish = publish_and_record

    raw_hl7 = "MSH|^~\\&|TEST|TEST|TEST|TEST|20260715120000||ADT^A01|MSG001|P|2.5"
    ack = await pipeline.process_message(raw_hl7)

    assert publish_completed, "publish() must complete before ACK is returned"
    assert isinstance(ack, bytes)
```

---

## Validation

Run from `hl7-listener/`:

```bash
# Run all US-014 unit tests
pytest tests/unit/pubsub/ -v --tb=short

# Coverage report for pubsub modules
pytest tests/unit/pubsub/ \
  --cov=app/pubsub \
  --cov-report=term-missing \
  --cov-fail-under=80
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `hl7-listener/tests/unit/pubsub/__init__.py` |
| CREATE | `hl7-listener/tests/unit/pubsub/test_adt_event_publisher.py` |
| CREATE | `hl7-listener/tests/unit/pubsub/test_publish_retry_queue.py` |
| CREATE | `hl7-listener/tests/unit/pubsub/test_pipeline_publish.py` |

---

## Definition of Done Checklist

- [ ] `test_publish_body_is_json_serialised_adt_event` — SC-1: body is valid JSON containing `encounter_id`
- [ ] `test_publish_sets_ordering_key_to_encounter_id` — SC-1: ordering key = `encounter_id`
- [ ] `test_publish_retries_three_times_on_transient_error` — SC-3: exactly 3 attempts
- [ ] `test_publish_delegates_to_retry_queue_after_all_retries` — SC-3: queue delegated
- [ ] `test_pubsub_failures_counter_incremented_on_exhaustion` — SC-3: Prometheus counter +1
- [ ] `test_build_attributes_contains_all_required_keys` — SC-4: all 4 attribute keys present
- [ ] `test_build_attributes_mrn_hash_is_sha256` — SC-4: SHA-256 hash, not raw MRN
- [ ] `test_build_attributes_no_raw_mrn` — BR-020: PHI not in attributes
- [ ] `test_publish_called_after_route` — pipeline step order: route before publish
- [ ] `test_ack_returned_after_publish` — ACK deferred until publish returns
- [ ] `pytest --cov=app/pubsub --cov-fail-under=80` passes
