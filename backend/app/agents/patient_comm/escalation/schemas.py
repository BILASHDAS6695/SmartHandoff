"""Pydantic schemas for the Care Team Escalation feature (US-045).

All schemas are consumed by:
    - task_002: POST /api/v1/chat/escalate FastAPI endpoint
    - task_003: PATCH /api/v1/chat/escalation/{id}/acknowledge endpoint
    - task_004: GET /api/v1/chat/escalations endpoint
    - task_002: EscalationAlertPayload published to Pub/Sub notification-requests topic

Design refs:
    US-045 AC Scenarios 1–4
    design.md §7.5 AIR-040 — notification-requests Pub/Sub topic payload format
    design.md §8.2 — patient JWT encounter scope
    US-045 Technical Notes — ESCALATION_CONFIRMED message type for SignalR push
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class NotificationChannel(str, Enum):
    """Notification channel used to alert the on-call nurse.

    Matches the `channel` field expected by the Notification Service
    (design.md §7.5 AIR-040).
    """

    SMS = "SMS"
    IN_APP = "IN_APP"


class EscalationMessageType(str, Enum):
    """Chat UI push message type for escalation confirmation.

    US-045 Technical Notes: pushed as a special message type, not a
    regular chatbot response, so the Angular client renders a distinct
    confirmation card rather than a chat bubble.
    """

    ESCALATION_CONFIRMED = "ESCALATION_CONFIRMED"


# ---------------------------------------------------------------------------
# Inbound schemas
# ---------------------------------------------------------------------------

class EscalationCreate(BaseModel):
    """Payload accepted by POST /api/v1/chat/escalate.

    Security note (US-045 AC Scenario 4):
        The API layer verifies that `encounter_id` matches the patient JWT
        `encounter_id` claim before any DB write or Pub/Sub publish.
        Mismatch MUST return HTTP 403.

    PHI note (design.md §6.1 DR-002 / AIR-021):
        `urgency_message` contains the verbatim patient message that triggered
        urgency detection. It does not contain direct identifiers (name, DOB,
        MRN) — it is the patient's own words. It is NOT encrypted at field
        level but MUST NOT appear in Cloud Logging output.
    """

    encounter_id: Annotated[
        str,
        Field(description="UUID of the patient encounter — must match JWT claim"),
    ]
    transcript_message_id: Annotated[
        str,
        Field(description="UUID of the chat_transcript row that triggered urgency detection"),
    ]
    urgency_message: Annotated[
        str,
        Field(
            min_length=1,
            max_length=2000,
            description="Verbatim patient urgency message — minimum PHI, no direct identifiers",
        ),
    ]
    channel: NotificationChannel = Field(
        default=NotificationChannel.SMS,
        description="Notification channel for on-call nurse alert",
    )

    @field_validator("encounter_id", "transcript_message_id")
    @classmethod
    def validate_uuid(cls, value: str, info) -> str:
        """Reject non-UUID values to prevent Redis/DB key injection attacks."""
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValueError(f"{info.field_name} must be a valid UUID v4") from exc
        return value


class EscalationAcknowledge(BaseModel):
    """Payload accepted by PATCH /api/v1/chat/escalation/{id}/acknowledge.

    Staff-only: nurse, physician, or admin role required.
    The `acknowledged_at` timestamp is set server-side (UTC); this schema
    exists as a request body placeholder for future extension (e.g., notes).
    """

    pass  # Body intentionally empty — acknowledgement is idempotent by timestamp


# ---------------------------------------------------------------------------
# Outbound schemas
# ---------------------------------------------------------------------------

class EscalationRead(BaseModel):
    """Escalation record returned by GET /api/v1/chat/escalations.

    US-045 AC Scenario 3 requires all these fields in the response.
    `acknowledgement_time_minutes` is a computed property — null if unacknowledged.
    """

    model_config = {"from_attributes": True}

    id: str
    encounter_id: str
    transcript_message_id: str
    notified_user_id: str
    notified_at: datetime
    acknowledged_at: datetime | None
    channel: NotificationChannel
    urgency_message: str
    created_at: datetime

    @computed_field
    @property
    def acknowledgement_time_minutes(self) -> float | None:
        """Minutes between notified_at and acknowledged_at.

        Used by US-045 DoD: if >2 minutes, the encounter is flagged for
        response time review (logged as a Cloud Monitoring metric in TASK-003).
        Returns None if not yet acknowledged.
        """
        if self.acknowledged_at is None:
            return None
        delta = self.acknowledged_at - self.notified_at
        return round(delta.total_seconds() / 60, 2)


# ---------------------------------------------------------------------------
# Pub/Sub payload schema
# ---------------------------------------------------------------------------

class EscalationAlertPayload(BaseModel):
    """Payload published to the 'notification-requests' Pub/Sub topic.

    Consumed by the Notification Service (design.md §7.5 AIR-040) to
    dispatch an SMS or in-app alert to the on-call nurse.

    PHI minimisation (design.md AIR-021):
        Only `patient_first_name` included — no surname, DOB, MRN, or
        full discharge details. The urgency summary is the patient's own
        words, truncated to 200 characters to minimise PHI exposure in
        the notification channel.
    """

    escalation_id: str = Field(description="UUID of the ChatbotEscalation row")
    encounter_id: str
    notified_user_id: str = Field(description="app_user.id of on-call nurse")
    patient_first_name: str = Field(description="Patient first name only — minimum PHI")
    urgency_message_summary: Annotated[
        str,
        Field(
            max_length=200,
            description="Truncated urgency message for the notification body",
        ),
    ]
    channel: NotificationChannel
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of Pub/Sub publish",
    )

    @model_validator(mode="before")
    @classmethod
    def truncate_urgency_summary(cls, values: dict) -> dict:
        """Enforce 200-char max on urgency_message_summary before validation."""
        if "urgency_message_summary" in values:
            values["urgency_message_summary"] = values["urgency_message_summary"][:200]
        return values


# ---------------------------------------------------------------------------
# SignalR chat push schema
# ---------------------------------------------------------------------------

class EscalationConfirmedMessage(BaseModel):
    """Pushed to the patient's chat UI immediately after escalation is created.

    US-045 Technical Notes:
        - Type is ESCALATION_CONFIRMED — not a regular chatbot reply
        - Angular client renders a distinct confirmation card
        - Displayed immediately after urgency detection, NOT after nurse
          acknowledgement (AC Scenario 1 confirmation text is shown here)
        - Fire-and-forget: chat response is NOT blocked on Pub/Sub delivery

    SignalR group: 'encounter-{encounter_id}' (design.md §3.3 SignalR hub)
    """

    type: EscalationMessageType = EscalationMessageType.ESCALATION_CONFIRMED
    encounter_id: str
    message: str = Field(
        default=(
            "Your care team has been notified and will contact you within 2 minutes. "
            "If this is life-threatening, call 911 immediately."
        ),
        description="Confirmation message shown in the patient's chat UI (AC Scenario 1)",
    )
    escalation_id: str = Field(description="UUID of the ChatbotEscalation row")
