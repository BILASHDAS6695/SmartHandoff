---
id: TASK-005
title: "Write Integration Test — Pub/Sub Emulator Confirms FIFO Ordering for Same Encounter (A01 → A02 → A03)"
user_story: US-014
epic: EP-001
sprint: 1
layer: Testing
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-014/TASK-001, US-014/TASK-002, US-014/TASK-003]
---

# TASK-005: Write Integration Test — Pub/Sub Emulator Confirms FIFO Ordering for Same Encounter (A01 → A02 → A03)

> **Story:** US-014 | **Epic:** EP-001 | **Sprint:** 1 | **Layer:** Testing | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

US-014 DoD specifies:

> *"Integration test: publish and pull from test subscription confirms FIFO order for same encounter"*

US-014 Acceptance Criteria Scenario 2 requires:

> *"Given events A01, A02, A03 arrive in sequence for encounter `ENC-001`, When they are published with ordering key `ENC-001`, Then a subscriber pulling messages from the subscription receives them in A01 → A02 → A03 order for that encounter."*

This integration test uses the **GCP Pub/Sub emulator** (`google.cloud.pubsub_v1` with `PUBSUB_EMULATOR_HOST` env var) instead of real GCP infrastructure. The emulator supports ordering keys and runs locally with no credentials.

**Emulator setup** (required before running this test):

```bash
# Install GCP emulator
gcloud components install pubsub-emulator

# Start the emulator in background
gcloud beta emulators pubsub start --project=test-project --host-port=localhost:8085

# Export emulator endpoint (must be set before running the test)
export PUBSUB_EMULATOR_HOST=localhost:8085
export PUBSUB_PROJECT_ID=test-project
export PUBSUB_TOPIC_ID=adt-events-test
```

Alternatively, the test fixture handles emulator lifecycle if `pytest-pubsub-emulator` or a Docker-based fixture is available. The test is skipped if `PUBSUB_EMULATOR_HOST` is not set (marks as `pytest.mark.integration`).

Design refs: ADR-001, US-014 SC-2, TR-005, TR-011.

---

## Acceptance Criteria Addressed

| US-014 AC | Requirement |
|---|---|
| **Scenario 2** | A01 → A02 → A03 published with same ordering key `encounter_id`; pull subscription receives them in that order |
| **DoD** | Integration test: publish and pull from test subscription confirms FIFO order |

---

## Implementation Steps

### 1. Scaffold integration test directory

```bash
mkdir -p hl7-listener/tests/integration/pubsub
touch hl7-listener/tests/integration/__init__.py
touch hl7-listener/tests/integration/pubsub/__init__.py
```

### 2. Create `hl7-listener/tests/integration/pubsub/test_pubsub_ordering.py`

```python
"""Integration test: Pub/Sub ordering key ensures FIFO delivery for same encounter.

Uses the GCP Pub/Sub emulator (PUBSUB_EMULATOR_HOST env var must be set).
Skipped in CI if emulator is not available.

Test scenario (US-014 SC-2):
  Publish A01, A02, A03 for encounter ENC-001 with ordering key = encounter_id.
  Pull from a dedicated test subscription.
  Assert messages arrive in A01 → A02 → A03 order.

Emulator start (run once before test session):
  gcloud beta emulators pubsub start --project=test-project --host-port=localhost:8085
  export PUBSUB_EMULATOR_HOST=localhost:8085

Design refs:
    ADR-001 — all ADT events to Pub/Sub before agent processing
    US-014  — SC-2: per-encounter FIFO delivery
    TR-011  — Pub/Sub throughput
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Generator

import pytest
from google.cloud import pubsub_v1

from app.pubsub.adt_event_publisher import ADTEventPublisher, _build_attributes
from app.pubsub.publish_retry_queue import PublishRetryQueue
from tests.factories.adt_event_factory import make_adt_event

# ---------------------------------------------------------------------------
# Skip if Pub/Sub emulator is not configured
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration

EMULATOR_HOST = os.environ.get("PUBSUB_EMULATOR_HOST")
TEST_PROJECT = os.environ.get("PUBSUB_PROJECT_ID", "test-project")
TEST_TOPIC = os.environ.get("PUBSUB_TOPIC_ID", "adt-events-test")

skip_if_no_emulator = pytest.mark.skipif(
    not EMULATOR_HOST,
    reason="PUBSUB_EMULATOR_HOST not set — Pub/Sub emulator required for integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pubsub_topic_and_subscription() -> Generator[tuple[str, str], None, None]:
    """Create a test topic and ordering-enabled subscription; tear down after module."""
    publisher_client = pubsub_v1.PublisherClient()
    subscriber_client = pubsub_v1.SubscriberClient()

    topic_path = publisher_client.topic_path(TEST_PROJECT, TEST_TOPIC)
    subscription_id = f"test-ordering-sub-{uuid.uuid4().hex[:8]}"
    subscription_path = subscriber_client.subscription_path(TEST_PROJECT, subscription_id)

    # Create topic
    try:
        publisher_client.create_topic(request={"name": topic_path})
    except Exception:
        pass  # Topic may already exist in emulator

    # Create subscription with enable_message_ordering=True
    subscriber_client.create_subscription(
        request={
            "name": subscription_path,
            "topic": topic_path,
            "enable_message_ordering": True,
        }
    )

    yield topic_path, subscription_path

    # Teardown
    try:
        subscriber_client.delete_subscription(
            request={"subscription": subscription_path}
        )
    except Exception:
        pass


@pytest.fixture()
def adt_publisher(tmp_path) -> ADTEventPublisher:
    """``ADTEventPublisher`` configured against the Pub/Sub emulator."""
    retry_queue = PublishRetryQueue(publish_fn=lambda e: None)  # no-op for integration test
    return ADTEventPublisher(
        retry_queue=retry_queue,
        project_id=TEST_PROJECT,
        topic_id=TEST_TOPIC,
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def pull_messages(subscription_path: str, expected_count: int) -> list[dict]:
    """Pull ``expected_count`` messages from the subscription synchronously."""
    subscriber = pubsub_v1.SubscriberClient()
    received: list[dict] = []

    max_polls = 10
    for _ in range(max_polls):
        response = subscriber.pull(
            request={
                "subscription": subscription_path,
                "max_messages": expected_count,
            }
        )
        for msg in response.received_messages:
            received.append(json.loads(msg.message.data.decode("utf-8")))
            subscriber.acknowledge(
                request={
                    "subscription": subscription_path,
                    "ack_ids": [msg.ack_id],
                }
            )
        if len(received) >= expected_count:
            break

    return received


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@skip_if_no_emulator
@pytest.mark.asyncio
async def test_ordering_key_ensures_fifo_for_same_encounter(
    adt_publisher, pubsub_topic_and_subscription
):
    """SC-2: A01, A02, A03 published with same encounter_id arrive in order.

    This test verifies that the GCP Pub/Sub ordering key mechanism delivers
    messages in FIFO order when the same ``encounter_id`` is used as the
    ordering key across sequential publishes.
    """
    topic_path, subscription_path = pubsub_topic_and_subscription
    encounter_id = uuid.uuid4()

    event_a01 = make_adt_event(encounter_id=encounter_id, event_type="ADMIT")
    event_a02 = make_adt_event(encounter_id=encounter_id, event_type="TRANSFER")
    event_a03 = make_adt_event(encounter_id=encounter_id, event_type="DISCHARGE")

    # Publish in sequence — ordering key = encounter_id for all three
    await adt_publisher.publish(event_a01)
    await adt_publisher.publish(event_a02)
    await adt_publisher.publish(event_a03)

    messages = pull_messages(subscription_path, expected_count=3)

    assert len(messages) == 3, f"Expected 3 messages, got {len(messages)}"

    received_event_types = [m["event_type"] for m in messages]
    assert received_event_types == ["ADMIT", "TRANSFER", "DISCHARGE"], (
        f"FIFO ordering violated: received {received_event_types}"
    )


@skip_if_no_emulator
@pytest.mark.asyncio
async def test_different_encounters_do_not_affect_each_other_ordering(
    adt_publisher, pubsub_topic_and_subscription
):
    """SC-2: Events for different encounters can interleave without ordering violation."""
    _, subscription_path = pubsub_topic_and_subscription
    enc_x = uuid.uuid4()
    enc_y = uuid.uuid4()

    event_x1 = make_adt_event(encounter_id=enc_x, event_type="ADMIT")
    event_y1 = make_adt_event(encounter_id=enc_y, event_type="ADMIT")
    event_x2 = make_adt_event(encounter_id=enc_x, event_type="DISCHARGE")

    await adt_publisher.publish(event_x1)
    await adt_publisher.publish(event_y1)
    await adt_publisher.publish(event_x2)

    messages = pull_messages(subscription_path, expected_count=3)
    enc_x_msgs = [m for m in messages if m["encounter_id"] == str(enc_x)]

    # enc_x events must be in ADMIT → DISCHARGE order regardless of interleaving
    enc_x_types = [m["event_type"] for m in enc_x_msgs]
    assert enc_x_types == ["ADMIT", "DISCHARGE"], (
        f"enc_x ordering violated: {enc_x_types}"
    )


@skip_if_no_emulator
@pytest.mark.asyncio
async def test_message_attributes_present_in_published_message(
    adt_publisher, pubsub_topic_and_subscription
):
    """SC-4: Published messages contain all 4 required attributes."""
    _, subscription_path = pubsub_topic_and_subscription
    event = make_adt_event(event_type="ADMIT")

    await adt_publisher.publish(event)

    subscriber = pubsub_v1.SubscriberClient()
    response = subscriber.pull(
        request={"subscription": subscription_path, "max_messages": 1}
    )

    assert response.received_messages, "No message received from subscription"
    msg = response.received_messages[0].message
    attributes = dict(msg.attributes)

    required_attributes = {"event_type", "encounter_id", "patient_mrn_hash", "iso_timestamp"}
    assert required_attributes.issubset(set(attributes.keys())), (
        f"Missing attributes: {required_attributes - set(attributes.keys())}"
    )

    # Verify no raw MRN in attributes (BR-020)
    raw_mrn = str(event.patient.mrn)
    for key, value in attributes.items():
        assert raw_mrn not in value, f"PHI leak: raw MRN found in attribute '{key}'"
```

### 3. Add integration test marker to `pytest.ini` or `pyproject.toml`

```ini
# pytest.ini
[pytest]
markers =
    integration: Tests requiring external services (Pub/Sub emulator, real DB)
```

---

## Running Integration Tests

```bash
# Start Pub/Sub emulator (one-time setup)
gcloud beta emulators pubsub start \
  --project=test-project \
  --host-port=localhost:8085 &

# Set environment variables
export PUBSUB_EMULATOR_HOST=localhost:8085
export PUBSUB_PROJECT_ID=test-project
export PUBSUB_TOPIC_ID=adt-events-test

# Run integration tests only
cd hl7-listener
pytest tests/integration/pubsub/ -v -m integration --tb=short
```

---

## Files Created / Modified

| Action | Path |
|--------|------|
| CREATE | `hl7-listener/tests/integration/__init__.py` |
| CREATE | `hl7-listener/tests/integration/pubsub/__init__.py` |
| CREATE | `hl7-listener/tests/integration/pubsub/test_pubsub_ordering.py` |
| MODIFY | `hl7-listener/pytest.ini` (or `pyproject.toml`) — add `integration` marker |

---

## Definition of Done Checklist

- [ ] `test_ordering_key_ensures_fifo_for_same_encounter` passes against Pub/Sub emulator
- [ ] A01 → A02 → A03 order confirmed in received messages
- [ ] `test_different_encounters_do_not_affect_each_other_ordering` passes
- [ ] `test_message_attributes_present_in_published_message` confirms all 4 attributes present
- [ ] Raw MRN assertion in attribute check passes (BR-020 compliance)
- [ ] Test is marked `pytest.mark.integration` and skipped when `PUBSUB_EMULATOR_HOST` is unset
- [ ] `integration` marker registered in `pytest.ini`
