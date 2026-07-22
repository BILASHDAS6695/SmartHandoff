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
  export PUBSUB_PROJECT_ID=test-project
  export PUBSUB_TOPIC_ID=adt-events-test

Design refs:
    ADR-001  — all ADT events to Pub/Sub before agent processing
    US-014   — SC-2: per-encounter FIFO delivery
    TR-011   — Pub/Sub throughput
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Generator

import pytest
from google.cloud import pubsub_v1

from app.pubsub.adt_event_publisher import ADTEventPublisher
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

    # Create topic (may already exist in emulator — that's fine)
    try:
        publisher_client.create_topic(request={"name": topic_path})
    except Exception:
        pass

    # Create subscription with enable_message_ordering=True (US-014 Technical Notes)
    subscriber_client.create_subscription(
        request={
            "name": subscription_path,
            "topic": topic_path,
            "enable_message_ordering": True,
        }
    )

    yield topic_path, subscription_path

    # Teardown — best-effort
    try:
        subscriber_client.delete_subscription(
            request={"subscription": subscription_path}
        )
    except Exception:
        pass


@pytest.fixture()
def adt_publisher() -> ADTEventPublisher:
    """``ADTEventPublisher`` configured against the Pub/Sub emulator."""
    retry_queue = PublishRetryQueue(publish_fn=_noop_publish_fn)
    return ADTEventPublisher(
        retry_queue=retry_queue,
        project_id=TEST_PROJECT,
        topic_id=TEST_TOPIC,
    )


async def _noop_publish_fn(event: object) -> None:
    """No-op publish function for the retry queue in integration tests."""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def pull_messages(subscription_path: str, expected_count: int, max_wait_s: float = 10.0) -> list[dict]:
    """Pull ``expected_count`` messages from the subscription synchronously.

    Polls up to ``max_wait_s`` seconds to allow for emulator propagation delay.
    """
    subscriber = pubsub_v1.SubscriberClient()
    received: list[dict] = []
    deadline = time.monotonic() + max_wait_s

    while time.monotonic() < deadline and len(received) < expected_count:
        response = subscriber.pull(
            request={
                "subscription": subscription_path,
                "max_messages": expected_count - len(received),
            }
        )
        ack_ids: list[str] = []
        for msg in response.received_messages:
            received.append(json.loads(msg.message.data.decode("utf-8")))
            ack_ids.append(msg.ack_id)

        if ack_ids:
            subscriber.acknowledge(
                request={"subscription": subscription_path, "ack_ids": ack_ids}
            )

        if len(received) < expected_count:
            time.sleep(0.5)

    return received


def pull_raw_messages(subscription_path: str, expected_count: int) -> list:
    """Pull raw Pub/Sub messages (with attributes) for attribute inspection."""
    subscriber = pubsub_v1.SubscriberClient()
    received = []
    deadline = time.monotonic() + 10.0

    while time.monotonic() < deadline and len(received) < expected_count:
        response = subscriber.pull(
            request={"subscription": subscription_path, "max_messages": expected_count}
        )
        ack_ids: list[str] = []
        for msg in response.received_messages:
            received.append(msg.message)
            ack_ids.append(msg.ack_id)
        if ack_ids:
            subscriber.acknowledge(
                request={"subscription": subscription_path, "ack_ids": ack_ids}
            )
        if len(received) < expected_count:
            time.sleep(0.5)

    return received


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@skip_if_no_emulator
@pytest.mark.asyncio
async def test_ordering_key_ensures_fifo_for_same_encounter(
    adt_publisher, pubsub_topic_and_subscription
):
    """SC-2: A01, A02, A03 published with same encounter_id arrive in FIFO order.

    Verifies that the GCP Pub/Sub ordering key mechanism delivers messages in
    FIFO order when the same ``encounter_id`` is used as the ordering key
    across sequential publishes for the same encounter.
    """
    _, subscription_path = pubsub_topic_and_subscription
    encounter_id = str(uuid.uuid4())

    event_a01 = make_adt_event(encounter_id=encounter_id, event_type="ADMIT")
    event_a02 = make_adt_event(encounter_id=encounter_id, event_type="TRANSFER")
    event_a03 = make_adt_event(encounter_id=encounter_id, event_type="DISCHARGE")

    # Publish in sequence — ordering key = encounter_id for all three (SC-2)
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
async def test_different_encounters_do_not_affect_each_other(
    adt_publisher, pubsub_topic_and_subscription
):
    """SC-2: Events for different encounters can interleave; per-encounter order maintained."""
    _, subscription_path = pubsub_topic_and_subscription
    enc_x = str(uuid.uuid4())
    enc_y = str(uuid.uuid4())

    event_x1 = make_adt_event(encounter_id=enc_x, event_type="ADMIT")
    event_y1 = make_adt_event(encounter_id=enc_y, event_type="ADMIT")
    event_x2 = make_adt_event(encounter_id=enc_x, event_type="DISCHARGE")

    await adt_publisher.publish(event_x1)
    await adt_publisher.publish(event_y1)
    await adt_publisher.publish(event_x2)

    messages = pull_messages(subscription_path, expected_count=3)
    enc_x_msgs = [m for m in messages if m["encounter_id"] == enc_x]

    enc_x_types = [m["event_type"] for m in enc_x_msgs]
    assert enc_x_types == ["ADMIT", "DISCHARGE"], (
        f"enc_x ordering violated: {enc_x_types}"
    )


@skip_if_no_emulator
@pytest.mark.asyncio
async def test_message_attributes_present_in_published_message(
    adt_publisher, pubsub_topic_and_subscription
):
    """SC-4: Published messages contain all 4 required attributes without raw MRN."""
    _, subscription_path = pubsub_topic_and_subscription
    event = make_adt_event(event_type="ADMIT")

    await adt_publisher.publish(event)

    raw_msgs = pull_raw_messages(subscription_path, expected_count=1)
    assert raw_msgs, "No message received from subscription"

    msg = raw_msgs[0]
    attributes = dict(msg.attributes)

    required_attributes = {"event_type", "encounter_id", "patient_mrn_hash", "iso_timestamp"}
    assert required_attributes.issubset(set(attributes.keys())), (
        f"Missing attributes: {required_attributes - set(attributes.keys())}"
    )

    # Verify no raw MRN in attributes (BR-020)
    raw_mrn = str(event.patient_mrn)
    for key, value in attributes.items():
        assert raw_mrn not in value, f"PHI leak: raw MRN found in attribute '{key}'"
