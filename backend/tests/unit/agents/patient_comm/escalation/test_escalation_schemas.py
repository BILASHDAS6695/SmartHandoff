"""Unit tests for US-045 Pydantic schemas (TASK-001).

Covers:
    - EscalationCreate UUID validation rejects non-UUIDs
    - EscalationRead.acknowledgement_time_minutes for acknowledged and unacknowledged rows
    - EscalationAlertPayload.urgency_message_summary truncated to 200 chars
    - EscalationConfirmedMessage contains required AC Scenario 1 text
"""
import pytest
from datetime import datetime, timezone, timedelta
from pydantic import ValidationError
import uuid

from backend.app.agents.patient_comm.escalation.schemas import (
    EscalationAlertPayload,
    EscalationConfirmedMessage,
    EscalationCreate,
    EscalationRead,
    NotificationChannel,
)

VALID_UUID_1 = str(uuid.uuid4())
VALID_UUID_2 = str(uuid.uuid4())
VALID_UUID_3 = str(uuid.uuid4())


class TestEscalationCreateValidation:
    def test_valid_create_accepted(self):
        req = EscalationCreate(
            encounter_id=VALID_UUID_1,
            transcript_message_id=VALID_UUID_2,
            urgency_message="I am having chest pain",
            channel=NotificationChannel.SMS,
        )
        assert req.encounter_id == VALID_UUID_1

    def test_non_uuid_encounter_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EscalationCreate(
                encounter_id="not-a-uuid",
                transcript_message_id=VALID_UUID_2,
                urgency_message="pain",
            )
        assert "encounter_id" in str(exc_info.value)

    def test_non_uuid_transcript_message_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EscalationCreate(
                encounter_id=VALID_UUID_1,
                transcript_message_id="../../etc/passwd",
                urgency_message="pain",
            )
        assert "transcript_message_id" in str(exc_info.value)

    def test_empty_urgency_message_rejected(self):
        with pytest.raises(ValidationError):
            EscalationCreate(
                encounter_id=VALID_UUID_1,
                transcript_message_id=VALID_UUID_2,
                urgency_message="",
            )

    def test_default_channel_is_sms(self):
        req = EscalationCreate(
            encounter_id=VALID_UUID_1,
            transcript_message_id=VALID_UUID_2,
            urgency_message="help",
        )
        assert req.channel == NotificationChannel.SMS


class TestEscalationReadAckTime:
    BASE_NOTIFIED_AT = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)

    def _make_read(self, ack_offset_seconds: int | None) -> EscalationRead:
        return EscalationRead(
            id=VALID_UUID_1,
            encounter_id=VALID_UUID_2,
            transcript_message_id=VALID_UUID_3,
            notified_user_id=VALID_UUID_3,
            notified_at=self.BASE_NOTIFIED_AT,
            acknowledged_at=(
                self.BASE_NOTIFIED_AT + timedelta(seconds=ack_offset_seconds)
                if ack_offset_seconds is not None
                else None
            ),
            channel=NotificationChannel.SMS,
            urgency_message="I feel dizzy",
            created_at=self.BASE_NOTIFIED_AT,
        )

    def test_unacknowledged_returns_none(self):
        read = self._make_read(None)
        assert read.acknowledgement_time_minutes is None

    def test_acknowledged_within_sla_returns_correct_minutes(self):
        read = self._make_read(90)  # 1.5 minutes
        assert read.acknowledgement_time_minutes == pytest.approx(1.5, rel=1e-2)

    def test_acknowledged_beyond_sla_returns_correct_minutes(self):
        read = self._make_read(180)  # 3.0 minutes
        assert read.acknowledgement_time_minutes == pytest.approx(3.0, rel=1e-2)

    def test_acknowledged_at_exactly_2_minutes(self):
        read = self._make_read(120)  # exactly 2 minutes
        assert read.acknowledgement_time_minutes == pytest.approx(2.0, rel=1e-2)


class TestEscalationAlertPayloadTruncation:
    def test_urgency_message_summary_truncated_to_200_chars(self):
        long_message = "x" * 500
        payload = EscalationAlertPayload(
            escalation_id=VALID_UUID_1,
            encounter_id=VALID_UUID_2,
            notified_user_id=VALID_UUID_3,
            patient_first_name="Jane",
            urgency_message_summary=long_message,
            channel=NotificationChannel.SMS,
        )
        assert len(payload.urgency_message_summary) == 200

    def test_short_message_not_truncated(self):
        payload = EscalationAlertPayload(
            escalation_id=VALID_UUID_1,
            encounter_id=VALID_UUID_2,
            notified_user_id=VALID_UUID_3,
            patient_first_name="Jane",
            urgency_message_summary="short message",
            channel=NotificationChannel.SMS,
        )
        assert payload.urgency_message_summary == "short message"

    def test_exactly_200_char_message(self):
        message = "x" * 200
        payload = EscalationAlertPayload(
            escalation_id=VALID_UUID_1,
            encounter_id=VALID_UUID_2,
            notified_user_id=VALID_UUID_3,
            patient_first_name="Jane",
            urgency_message_summary=message,
            channel=NotificationChannel.SMS,
        )
        assert len(payload.urgency_message_summary) == 200


class TestEscalationConfirmedMessage:
    def test_message_contains_2_minutes(self):
        msg = EscalationConfirmedMessage(
            encounter_id=VALID_UUID_1,
            escalation_id=VALID_UUID_2,
        )
        assert "2 minutes" in msg.message

    def test_message_contains_911_reference(self):
        msg = EscalationConfirmedMessage(
            encounter_id=VALID_UUID_1,
            escalation_id=VALID_UUID_2,
        )
        assert "911" in msg.message

    def test_message_type_is_escalation_confirmed(self):
        from backend.app.agents.patient_comm.escalation.schemas import EscalationMessageType
        msg = EscalationConfirmedMessage(
            encounter_id=VALID_UUID_1,
            escalation_id=VALID_UUID_2,
        )
        assert msg.type == EscalationMessageType.ESCALATION_CONFIRMED

    def test_message_contains_life_threatening_guidance(self):
        msg = EscalationConfirmedMessage(
            encounter_id=VALID_UUID_1,
            escalation_id=VALID_UUID_2,
        )
        assert "life-threatening" in msg.message.lower()
