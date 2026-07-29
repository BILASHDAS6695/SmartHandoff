"""Unit tests for emergency alert handler (US-044 TASK-004).

Covers:
    - Alert payload PHI bounds: encounter_id, patient_first_name (ONLY), urgency_message_summary, timestamp, idempotency_key
    - Pub/Sub publish: CARE_TEAM_URGENCY_ALERT to notification-requests channel
    - DB write: chatbot_transcript.urgency_flag=True
    - Concurrent execution: asyncio.gather() with return_exceptions=True
    - Hardcoded reply: returned immediately (not LLM-dependent)
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.patient_comm.urgency.emergency_handler import (
    EmergencyAlertHandler,
)
from backend.app.agents.patient_comm.urgency.schemas import (
    DetectionPhase,
    EmergencyContactConfig,
    UrgencyDetectionResult,
    UrgencyAlertPayload,
)


# Fixtures
ENCOUNTER_ID = str(uuid4())
PATIENT_FIRST_NAME = "Alice"
EMERGENCY_DISPLAY_MESSAGE = (
    "⚠ Emergency Alert: This sounds serious. Call 911 immediately or go to the "
    "nearest emergency room. Your care team has been notified."
)


@pytest.fixture
def mock_emergency_config() -> EmergencyContactConfig:
    """Mock emergency contact configuration."""
    return EmergencyContactConfig(
        primary_number="911",
        hospital_number="1-800-HOSPITAL",
        display_message=EMERGENCY_DISPLAY_MESSAGE,
        care_team_alert_channel="notification-requests",
    )


@pytest.fixture
def urgency_result() -> UrgencyDetectionResult:
    """Mock urgency detection result (keyword match)."""
    return UrgencyDetectionResult(
        is_urgent=True,
        detection_phase=DetectionPhase.KEYWORD,
        matched_phrase="chest pain",
        confidence=None,
        message_summary="Urgency keyword detected: 'chest pain'",
    )


@pytest.fixture
async def mock_db_session() -> AsyncSession:
    """Mock database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


class TestEmergencyAlertHandlerReply:
    """Test the hardcoded emergency reply behavior."""

    @pytest.mark.asyncio
    async def test_returns_hardcoded_reply_immediately(self, mock_emergency_config, urgency_result, mock_db_session):
        """Emergency reply must be hardcoded and returned immediately (not LLM-dependent)."""
        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch.object(EmergencyAlertHandler, "_publish_care_team_alert", new_callable=AsyncMock):
                with patch.object(EmergencyAlertHandler, "_persist_urgency_flag", new_callable=AsyncMock):
                    handler = EmergencyAlertHandler()
                    reply = await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        assert reply == EMERGENCY_DISPLAY_MESSAGE
        assert reply is mock_emergency_config.display_message

    @pytest.mark.asyncio
    async def test_reply_does_not_depend_on_pubsub_or_db_completion(self, mock_emergency_config, urgency_result, mock_db_session):
        """Reply must be returned even if Pub/Sub or DB operations fail."""
        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            # Simulate Pub/Sub and DB failures
            with patch.object(
                EmergencyAlertHandler, "_publish_care_team_alert",
                side_effect=Exception("Pub/Sub connection failed"),
                new_callable=AsyncMock,
            ):
                with patch.object(
                    EmergencyAlertHandler, "_persist_urgency_flag",
                    side_effect=Exception("DB connection failed"),
                    new_callable=AsyncMock,
                ):
                    handler = EmergencyAlertHandler()
                    reply = await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        # Reply must still be returned successfully
        assert reply == EMERGENCY_DISPLAY_MESSAGE


class TestEmergencyAlertHandlerPayloadPHI:
    """Test PHI minimization in Pub/Sub alert payload (design.md AIR-021)."""

    @pytest.mark.asyncio
    async def test_alert_payload_contains_only_minimum_phi(self, mock_emergency_config, urgency_result, mock_db_session):
        """Alert payload must contain ONLY: encounter_id, patient_first_name, urgency_message_summary, timestamp, idempotency_key."""
        published_payloads = []

        async def capture_publish(payload: UrgencyAlertPayload) -> None:
            published_payloads.append(payload.model_dump(mode="json"))

        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch.object(
                EmergencyAlertHandler, "_publish_care_team_alert",
                side_effect=capture_publish,
                new_callable=AsyncMock,
            ):
                with patch.object(EmergencyAlertHandler, "_persist_urgency_flag", new_callable=AsyncMock):
                    handler = EmergencyAlertHandler()
                    await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        assert len(published_payloads) == 1
        payload = published_payloads[0]

        # Verify ONLY these fields are present
        expected_keys = {"encounter_id", "patient_first_name", "urgency_message_summary", "timestamp", "idempotency_key"}
        actual_keys = set(payload.keys())
        assert actual_keys == expected_keys, f"Payload has unexpected keys: {actual_keys - expected_keys}"

        # Verify NO PHI fields
        assert "last_name" not in payload
        assert "dob" not in payload
        assert "mrn" not in payload
        assert "phone" not in payload
        assert "email" not in payload
        assert "patient_message" not in payload

    @pytest.mark.asyncio
    async def test_alert_payload_patient_first_name_only(self, mock_emergency_config, urgency_result, mock_db_session):
        """Alert payload must contain patient_first_name only (not full name)."""
        published_payloads = []

        async def capture_publish(payload: UrgencyAlertPayload) -> None:
            published_payloads.append(payload)

        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch.object(
                EmergencyAlertHandler, "_publish_care_team_alert",
                side_effect=capture_publish,
                new_callable=AsyncMock,
            ):
                with patch.object(EmergencyAlertHandler, "_persist_urgency_flag", new_callable=AsyncMock):
                    handler = EmergencyAlertHandler()
                    await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        assert len(published_payloads) == 1
        payload = published_payloads[0]
        assert payload.patient_first_name == PATIENT_FIRST_NAME

    @pytest.mark.asyncio
    async def test_alert_payload_message_summary_never_reproduces_raw_message(self, mock_emergency_config, mock_db_session):
        """message_summary must be system-generated, never the patient's raw message."""
        # This urgency detection result includes the matched keyword summary
        urgency_result = UrgencyDetectionResult(
            is_urgent=True,
            detection_phase=DetectionPhase.KEYWORD,
            matched_phrase="chest pain",
            confidence=None,
            message_summary="Urgency keyword detected: 'chest pain'",
        )

        published_payloads = []

        async def capture_publish(payload: UrgencyAlertPayload) -> None:
            published_payloads.append(payload)

        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch.object(
                EmergencyAlertHandler, "_publish_care_team_alert",
                side_effect=capture_publish,
                new_callable=AsyncMock,
            ):
                with patch.object(EmergencyAlertHandler, "_persist_urgency_flag", new_callable=AsyncMock):
                    handler = EmergencyAlertHandler()
                    await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        assert len(published_payloads) == 1
        payload = published_payloads[0]
        # message_summary must be the system-generated text, not the raw patient message
        assert payload.urgency_message_summary == "Urgency keyword detected: 'chest pain'"
        # It should NOT contain patient's full message
        assert "general" not in payload.urgency_message_summary or "chest pain" in payload.urgency_message_summary


class TestEmergencyAlertHandlerPubSub:
    """Test Pub/Sub publish behavior."""

    @pytest.mark.asyncio
    async def test_publishes_to_notification_requests_channel(self, mock_emergency_config, urgency_result, mock_db_session):
        """Alert must be published to the care_team_alert_channel from config."""
        publish_calls = []

        def mock_publish(topic_path, data, **attributes):
            publish_calls.append({
                "topic_path": topic_path,
                "data": data,
                "attributes": attributes,
            })
            # Return a mock Future
            future = MagicMock()
            future.result.return_value = "msg-id-123"
            return future

        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch("backend.app.agents.patient_comm.urgency.emergency_handler.pubsub_v1.PublisherClient") as mock_publisher_class:
                mock_publisher = MagicMock()
                mock_publisher.publish = mock_publish
                mock_publisher.topic_path.return_value = "projects/test-project/topics/notification-requests"
                mock_publisher_class.return_value = mock_publisher

                with patch.object(EmergencyAlertHandler, "_persist_urgency_flag", new_callable=AsyncMock):
                    handler = EmergencyAlertHandler()
                    await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        assert len(publish_calls) == 1
        assert "notification-requests" in publish_calls[0]["topic_path"]
        assert publish_calls[0]["attributes"]["event_type"] == "CARE_TEAM_URGENCY_ALERT"

    @pytest.mark.asyncio
    async def test_publishes_with_idempotency_key(self, mock_emergency_config, urgency_result, mock_db_session):
        """Alert must include idempotency_key to prevent duplicate sends (design.md AIR-040)."""
        publish_calls = []

        def mock_publish(topic_path, data, **attributes):
            publish_calls.append(attributes)
            future = MagicMock()
            future.result.return_value = "msg-id-123"
            return future

        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch("backend.app.agents.patient_comm.urgency.emergency_handler.pubsub_v1.PublisherClient") as mock_publisher_class:
                mock_publisher = MagicMock()
                mock_publisher.publish = mock_publish
                mock_publisher.topic_path.return_value = "projects/test-project/topics/notification-requests"
                mock_publisher_class.return_value = mock_publisher

                with patch.object(EmergencyAlertHandler, "_persist_urgency_flag", new_callable=AsyncMock):
                    handler = EmergencyAlertHandler()
                    await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        assert len(publish_calls) == 1
        assert "idempotency_key" in publish_calls[0]
        assert ENCOUNTER_ID in publish_calls[0]["idempotency_key"]

    @pytest.mark.asyncio
    async def test_pubsub_failure_does_not_block_reply(self, mock_emergency_config, urgency_result, mock_db_session):
        """If Pub/Sub publish fails, the reply must still be returned and error logged."""
        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch("backend.app.agents.patient_comm.urgency.emergency_handler.pubsub_v1.PublisherClient") as mock_publisher_class:
                mock_publisher = MagicMock()
                mock_publisher.publish.side_effect = Exception("Pub/Sub unavailable")
                mock_publisher.topic_path.return_value = "projects/test-project/topics/notification-requests"
                mock_publisher_class.return_value = mock_publisher

                with patch.object(EmergencyAlertHandler, "_persist_urgency_flag", new_callable=AsyncMock):
                    handler = EmergencyAlertHandler()
                    reply = await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        # Reply must still be returned
        assert reply == EMERGENCY_DISPLAY_MESSAGE


class TestEmergencyAlertHandlerDatabase:
    """Test database urgency_flag write behavior."""

    @pytest.mark.asyncio
    async def test_persists_urgency_flag_to_db(self, mock_emergency_config, urgency_result, mock_db_session):
        """The urgency_flag column on chatbot_transcript must be set to TRUE."""
        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch.object(EmergencyAlertHandler, "_publish_care_team_alert", new_callable=AsyncMock):
                handler = EmergencyAlertHandler()
                await handler.handle(
                    urgency_result,
                    ENCOUNTER_ID,
                    PATIENT_FIRST_NAME,
                    mock_db_session,
                )

        # Verify execute and commit were called
        mock_db_session.execute.assert_called_once()
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_failure_does_not_block_reply(self, mock_emergency_config, urgency_result, mock_db_session):
        """If DB write fails, the reply must still be returned and error logged."""
        mock_db_session.execute.side_effect = Exception("DB connection lost")

        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch.object(EmergencyAlertHandler, "_publish_care_team_alert", new_callable=AsyncMock):
                handler = EmergencyAlertHandler()
                reply = await handler.handle(
                    urgency_result,
                    ENCOUNTER_ID,
                    PATIENT_FIRST_NAME,
                    mock_db_session,
                )

        # Reply must still be returned
        assert reply == EMERGENCY_DISPLAY_MESSAGE
        # Rollback must be called on error
        mock_db_session.rollback.assert_called_once()


class TestEmergencyAlertHandlerConcurrency:
    """Test asyncio.gather() concurrent execution of Pub/Sub and DB operations."""

    @pytest.mark.asyncio
    async def test_pubsub_and_db_run_concurrently(self, mock_emergency_config, urgency_result, mock_db_session):
        """Pub/Sub publish and DB write must run concurrently via asyncio.gather()."""
        call_order = []

        async def mock_publish(*args, **kwargs):
            call_order.append("publish")

        async def mock_persist(*args, **kwargs):
            call_order.append("persist")

        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            with patch.object(
                EmergencyAlertHandler, "_publish_care_team_alert",
                side_effect=mock_publish,
                new_callable=AsyncMock,
            ):
                with patch.object(
                    EmergencyAlertHandler, "_persist_urgency_flag",
                    side_effect=mock_persist,
                    new_callable=AsyncMock,
                ):
                    handler = EmergencyAlertHandler()
                    await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

        # Both operations should have been called
        assert "publish" in call_order
        assert "persist" in call_order

    @pytest.mark.asyncio
    async def test_concurrent_execution_with_return_exceptions(self, mock_emergency_config, urgency_result, mock_db_session):
        """asyncio.gather(..., return_exceptions=True) must allow one failure without blocking the other."""
        with patch(
            "backend.app.agents.patient_comm.urgency.emergency_handler.load_emergency_contact_config",
            return_value=mock_emergency_config,
        ):
            # Make Pub/Sub fail, but DB succeed
            with patch.object(
                EmergencyAlertHandler, "_publish_care_team_alert",
                side_effect=Exception("Pub/Sub fail"),
                new_callable=AsyncMock,
            ):
                with patch.object(EmergencyAlertHandler, "_persist_urgency_flag", new_callable=AsyncMock):
                    handler = EmergencyAlertHandler()
                    reply = await handler.handle(
                        urgency_result,
                        ENCOUNTER_ID,
                        PATIENT_FIRST_NAME,
                        mock_db_session,
                    )

            # Reply should still be returned
            assert reply == EMERGENCY_DISPLAY_MESSAGE
            # DB write should still have been attempted
            mock_db_session.execute.assert_called_once()
