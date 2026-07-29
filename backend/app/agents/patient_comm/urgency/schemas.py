"""Pydantic schemas and domain models for the Urgency Detector (US-044).

All schemas are consumed by:
    - task_002: UrgencyDetector Phase 1 (keyword matching)
    - task_003: UrgencyDetector Phase 2 (Gemini semantic classification)
    - task_004: EmergencyAlertHandler (Pub/Sub publish, DB write)
    - task_005: POST /api/v1/chat pipeline integration

Design refs:
    US-044 AC Scenarios 1–4
    design.md §7.3 AIR-020 — Vertex AI structured output with Pydantic validation
    design.md §7.5 AIR-040 — notification-requests Pub/Sub payload contract
    US-044 Technical Notes — minimum-PHI alert payload
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Detection phase enumeration
# ---------------------------------------------------------------------------

class DetectionPhase(str, Enum):
    """Which detection phase triggered the urgency verdict.

    KEYWORD  — Phase 1 regex match (O(n), <10ms) — US-044 Technical Notes
    SEMANTIC — Phase 2 Gemini Flash classification (~500ms) — US-044 Technical Notes
    NONE     — No urgency detected; message proceeds to normal chatbot pipeline
    """

    KEYWORD = "KEYWORD"
    SEMANTIC = "SEMANTIC"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Gemini structured output schema — Phase 2 classification
# ---------------------------------------------------------------------------

class GeminiUrgencyClassification(BaseModel):
    """Structured JSON output from Gemini Flash urgency classification.

    Gemini is prompted to return ONLY this schema in JSON mode:
        response_mime_type="application/json"

    The `confidence` field maps to the 0.8 threshold defined in US-044 DoD:
        if classification.urgency and classification.confidence >= 0.8 → trigger urgency response
    """

    urgency: bool = Field(
        ...,
        description="True if the message contains a medical urgency signal",
    )
    confidence: Annotated[
        float,
        Field(
            ge=0.0,
            le=1.0,
            description="Confidence score; urgency triggered only when ≥ 0.8",
        ),
    ]


# ---------------------------------------------------------------------------
# Combined detection result
# ---------------------------------------------------------------------------

class UrgencyDetectionResult(BaseModel):
    """Result produced by UrgencyDetector after running both phases.

    Consumed by task_004 (EmergencyAlertHandler) and task_005 (pipeline integration).

    If `is_urgent` is False, `detection_phase` is `NONE` and `matched_phrase`
    is None — the message proceeds to the normal US-043 chatbot pipeline.
    """

    is_urgent: bool = Field(
        ...,
        description="True if urgency was detected by either Phase 1 or Phase 2",
    )
    detection_phase: DetectionPhase = Field(
        ...,
        description="Which phase triggered the verdict",
    )
    matched_phrase: str | None = Field(
        default=None,
        description="The keyword phrase that matched in Phase 1; None for semantic or non-urgent",
    )
    confidence: float | None = Field(
        default=None,
        description="Gemini confidence score (Phase 2 only); None for keyword or non-urgent",
    )
    message_summary: str | None = Field(
        default=None,
        description=(
            "Brief non-PHI summary of the urgency trigger for the alert payload. "
            "Maximum 100 characters. Never contains patient name, DOB, or MRN."
        ),
        max_length=100,
    )


# ---------------------------------------------------------------------------
# Emergency contact configuration schema
# ---------------------------------------------------------------------------

class EmergencyContactConfig(BaseModel):
    """Typed representation of config/emergency_contacts.yaml.

    Loaded once at agent startup from the YAML file and injected into
    EmergencyAlertHandler. Never serialised to logs or responses.
    """

    primary_number: str = Field(..., description="Primary emergency number, e.g. '911'")
    hospital_number: str = Field(..., description="Hospital direct emergency line")
    display_message: str = Field(
        ...,
        description="Full message displayed to patient in chat UI when urgency detected",
    )
    care_team_alert_channel: str = Field(
        ...,
        description="Pub/Sub topic name for CARE_TEAM_URGENCY_ALERT messages",
    )


# ---------------------------------------------------------------------------
# Urgency alert Pub/Sub payload — minimum PHI
# ---------------------------------------------------------------------------

class UrgencyAlertPayload(BaseModel):
    """Payload published to the notification-requests Pub/Sub topic.

    Minimum PHI principle (design.md AIR-021):
        - Contains only encounter_id (UUID, not directly identifying)
        - Contains ONLY patient_first_name (no last name, DOB, MRN)
        - Contains non-PHI urgency_message_summary (system-generated, not patient text)
        - Contains timestamp for audit trail

    Consumed by the Notification Service (design.md §7.5 AIR-040) → SMS to care team.
    """

    encounter_id: str = Field(..., description="Encounter UUID (not directly identifying)")
    patient_first_name: str = Field(
        ...,
        description="Patient first name only (minimum PHI; no last name, DOB, or MRN)",
    )
    urgency_message_summary: str = Field(
        ...,
        description="System-generated urgency trigger summary; never the raw patient message",
        max_length=100,
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Alert publication timestamp (UTC)",
    )
    idempotency_key: str = Field(
        ...,
        description="Unique key for Pub/Sub idempotency; prevents duplicate sends (design.md AIR-040)",
    )


# ---------------------------------------------------------------------------
# Urgency keyword configuration schema
# ---------------------------------------------------------------------------

class UrgencyKeywordConfig(BaseModel):
    """Typed representation of config/urgency_keywords.yaml.

    Loaded once at agent startup and cached as compiled regex patterns.
    """

    keywords: list[str] = Field(
        ...,
        description="List of urgency keyword phrases to match case-insensitively in Phase 1",
    )
