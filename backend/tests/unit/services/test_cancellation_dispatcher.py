"""Unit tests for CancellationDispatcher (US-015 TASK-005).

Validates:
  - Pub/Sub attributes include all required keys (no PHI)
  - SignalR group name format
  - Pub/Sub failure does not prevent SignalR broadcast (failure isolation)
  - SignalR failure does not prevent Pub/Sub publish (failure isolation)
  - No PHI fields in any published payload
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from app.services.cancellation_dispatcher import CancellationDispatcher
from app.services.cancellation_service import CancellationResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ENC_ID = uuid4()
RESULT_A11 = CancellationResult(
    encounter_id=ENC_ID,
    event_type="A11",
    tasks_cancelled=3,
    docs_cancelled=2,
)
RESULT_A12 = CancellationResult(
    encounter_id=ENC_ID,
    event_type="A12",
    tasks_cancelled=1,
    docs_cancelled=0,
)


@pytest.fixture()
def mock_publisher() -> AsyncMock:
    pub = AsyncMock()
    pub.publish_raw = AsyncMock()
    return pub


@pytest.fixture()
def mock_hub() -> AsyncMock:
    hub = AsyncMock()
    hub.send_to_group = AsyncMock()
    return hub


@pytest.fixture()
def dispatcher(mock_publisher, mock_hub) -> CancellationDispatcher:
    return CancellationDispatcher(publisher=mock_publisher, hub=mock_hub)


# ---------------------------------------------------------------------------
# Pub/Sub attribute validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pubsub_attributes_contain_required_keys(dispatcher, mock_publisher):
    """WORKFLOW_CANCELLED message must include message_type, event_type, encounter_id, iso_timestamp."""
    await dispatcher.dispatch_post_commit(RESULT_A11)

    mock_publisher.publish_raw.assert_awaited_once()
    _, kwargs = mock_publisher.publish_raw.call_args
    attrs = kwargs.get("attributes") or mock_publisher.publish_raw.call_args[1]["attributes"]

    for key in ("message_type", "event_type", "encounter_id", "iso_timestamp"):
        assert key in attrs, f"Missing attribute: {key}"

    assert attrs["message_type"] == "WORKFLOW_CANCELLED"
    assert attrs["event_type"] == "A11"
    assert attrs["encounter_id"] == str(ENC_ID)


@pytest.mark.asyncio
async def test_pubsub_ordering_key_is_encounter_id(dispatcher, mock_publisher):
    """WORKFLOW_CANCELLED ordering key must equal str(encounter_id) for FIFO ordering."""
    await dispatcher.dispatch_post_commit(RESULT_A11)

    mock_publisher.publish_raw.assert_awaited_once()
    kwargs = mock_publisher.publish_raw.call_args.kwargs
    assert kwargs["ordering_key"] == str(ENC_ID)


@pytest.mark.asyncio
async def test_pubsub_message_body_contains_counts(dispatcher, mock_publisher):
    """WORKFLOW_CANCELLED message body must include tasks_cancelled and docs_cancelled."""
    await dispatcher.dispatch_post_commit(RESULT_A11)

    _, kwargs = mock_publisher.publish_raw.call_args
    data: bytes = kwargs.get("data") or mock_publisher.publish_raw.call_args[1]["data"]
    body = json.loads(data.decode("utf-8"))

    assert body["tasks_cancelled"] == 3
    assert body["docs_cancelled"] == 2
    assert body["event_type"] == "A11"


@pytest.mark.asyncio
async def test_pubsub_no_phi_in_attributes(dispatcher, mock_publisher):
    """PHI fields must be absent from Pub/Sub message attributes (BR-020)."""
    await dispatcher.dispatch_post_commit(RESULT_A11)

    _, kwargs = mock_publisher.publish_raw.call_args
    attrs = kwargs.get("attributes") or mock_publisher.publish_raw.call_args[1]["attributes"]

    phi_fields = {"mrn", "first_name", "last_name", "dob", "phone", "email",
                  "patient_mrn", "patient_name", "patient_mrn_hash"}
    found = phi_fields & set(attrs.keys())
    assert not found, f"PHI field(s) found in Pub/Sub attributes: {found}"


# ---------------------------------------------------------------------------
# SignalR group / event validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signalr_group_format(dispatcher, mock_hub):
    """SignalR group must be 'encounter-{encounter_id}'."""
    await dispatcher.dispatch_post_commit(RESULT_A11)

    mock_hub.send_to_group.assert_awaited_once()
    _, kwargs = mock_hub.send_to_group.call_args
    group = kwargs.get("group") or mock_hub.send_to_group.call_args[1]["group"]
    assert group == f"encounter-{ENC_ID}"


@pytest.mark.asyncio
async def test_signalr_event_type_in_payload(dispatcher, mock_hub):
    """SignalR payload must include event='ENCOUNTER_CANCELLED' and event_type."""
    await dispatcher.dispatch_post_commit(RESULT_A12)

    _, kwargs = mock_hub.send_to_group.call_args
    payload = kwargs.get("payload") or mock_hub.send_to_group.call_args[1]["payload"]
    assert payload["event"] == "ENCOUNTER_CANCELLED"
    assert payload["event_type"] == "A12"


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pubsub_failure_does_not_block_signalr(mock_publisher, mock_hub):
    """If Pub/Sub publish fails, SignalR broadcast must still be attempted."""
    mock_publisher.publish_raw = AsyncMock(side_effect=RuntimeError("pubsub down"))
    dispatcher = CancellationDispatcher(publisher=mock_publisher, hub=mock_hub)

    await dispatcher.dispatch_post_commit(RESULT_A11)  # must not raise

    mock_hub.send_to_group.assert_awaited_once()


@pytest.mark.asyncio
async def test_signalr_failure_does_not_raise(mock_publisher, mock_hub):
    """If SignalR broadcast fails, dispatch_post_commit must not raise."""
    mock_hub.send_to_group = AsyncMock(side_effect=ConnectionError("signalr down"))
    dispatcher = CancellationDispatcher(publisher=mock_publisher, hub=mock_hub)

    await dispatcher.dispatch_post_commit(RESULT_A11)  # must not raise

    mock_publisher.publish_raw.assert_awaited_once()
