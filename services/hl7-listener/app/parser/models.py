"""ADTEvent domain model and supporting types for the HL7 Listener service.

Defines the typed domain contract that the HL7 parser produces and all
downstream consumers (Pub/Sub publisher, coordinator agent) depend on.

Key design decisions:
  - Pydantic v2 ``strict=True`` — no silent type coercions.
  - PHI fields excluded from repr/serialisation by default (BR-020).
  - ``EventType`` enum ties HL7 trigger codes to readable domain names.
  - ``HL7ValidationError`` is the single exception type raised by parsing and
    routing; the MLLP server catches it to return a NACK (AE).

Design refs:
    FR-002  — ADT event type classification
    FR-003  — HL7 message validation (mandatory segments, field extraction)
    AIR-002 — Mandatory segments: MSH, EVN, PID; PV1 required for A01/A02/A03
    DR-022  — HL7 message idempotency: source_message_id unique constraint
    BR-020  — PHI must not appear in logs
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Event type enumeration
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """HL7 ADT trigger event types supported by SmartHandoff.

    Maps HL7 MSH-9.2 (trigger event code) to a domain-readable name.
    Only these 8 event types are accepted; all others trigger a NACK.
    """
    ADMIT            = "ADMIT"            # A01 — Admit/visit notification
    TRANSFER         = "TRANSFER"         # A02 — Transfer a patient
    DISCHARGE        = "DISCHARGE"        # A03 — Discharge/end visit
    REGISTER         = "REGISTER"         # A04 — Register a patient
    UPDATE           = "UPDATE"           # A08 — Update patient information
    CANCEL_ADMIT     = "CANCEL_ADMIT"     # A11 — Cancel admit/visit notification
    CANCEL_TRANSFER  = "CANCEL_TRANSFER"  # A12 — Cancel transfer
    CANCEL_DISCHARGE = "CANCEL_DISCHARGE" # A13 — Cancel discharge/end visit


# HL7 trigger code → EventType routing table (used by router.py and hl7_parser.py)
HL7_TRIGGER_MAP: dict[str, EventType] = {
    "A01": EventType.ADMIT,
    "A02": EventType.TRANSFER,
    "A03": EventType.DISCHARGE,
    "A04": EventType.REGISTER,
    "A08": EventType.UPDATE,
    "A11": EventType.CANCEL_ADMIT,
    "A12": EventType.CANCEL_TRANSFER,
    "A13": EventType.CANCEL_DISCHARGE,
}


# ---------------------------------------------------------------------------
# Domain exception
# ---------------------------------------------------------------------------

class HL7ValidationError(Exception):
    """Raised when an HL7 message fails structural or content validation.

    This exception is intentionally narrow — it represents only the cases
    that the MLLP server should convert into a NACK (AE) response:
      - Missing mandatory segment (MSH, EVN, PID, PV1 where required)
      - Unknown/unsupported trigger event code (e.g. A99)
      - Field extraction failure on a mandatory field

    The MLLP server layer (app/mllp/server.py) catches this exception and
    calls ``build_nack_response()``.  It must NOT be used for unexpected
    runtime errors — those should propagate as standard exceptions.

    Attributes:
        segment:  Name of the problematic HL7 segment (e.g. ``"PID"``).
        field:    Field location within the segment (e.g. ``"PID-3"``), or
                  ``None`` when the entire segment is missing.
        message:  Human-readable description (not logged with PHI).
    """

    def __init__(
        self,
        message: str,
        *,
        segment: Optional[str] = None,
        field: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.segment = segment
        self.field = field

    def __repr__(self) -> str:
        return (
            f"HL7ValidationError(segment={self.segment!r}, "
            f"field={self.field!r}, message={str(self)!r})"
        )


# ---------------------------------------------------------------------------
# ADTEvent domain model
# ---------------------------------------------------------------------------

class ADTEvent(BaseModel):
    """Typed representation of a parsed HL7 ADT message.

    Produced by ``HL7Parser.parse()`` and consumed by:
      - The Pub/Sub publisher (serialised to JSON for the ``adt-events`` topic)
      - The Coordinator Agent (deserialized from Pub/Sub message)
      - Unit tests (constructed directly from test fixtures)

    PHI fields (patient_mrn, patient_last_name, patient_first_name,
    patient_dob, patient_address) are redacted in ``safe_dict()`` and
    ``__repr__`` to prevent accidental PHI leakage in logs (BR-020).

    Extraction sources (segment → field):
      MSH-3   → sending_application
      MSH-7   → message_datetime
      MSH-9.2 → event_type (via EventType enum)
      MSH-10  → source_message_id
      EVN-2   → event_time
      PID-3   → patient_mrn        (first CX component with type "MR")
      PID-5   → patient_last_name, patient_first_name  [PHI]
      PID-7   → patient_dob                            [PHI]
      PID-11  → patient_address                        [PHI]
      PV1-2   → patient_class
      PV1-3   → assigned_location
      PV1-7   → attending_provider
      PV1-18  → patient_type
      PV1-19  → encounter_id
      PV2-3   → admit_reason
      DG1-3   → diagnoses  (list; DG1 may repeat)

    Design refs:
        FR-002, FR-003, AIR-002, DR-022, BR-020, US-012 DoD
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    # -- Identification (non-PHI) -------------------------------------------
    source_message_id: str = Field(
        description="MSH-10: unique message control ID from the sending system.",
    )
    event_type: EventType = Field(
        description="Classified ADT event type derived from MSH-9.2 trigger code.",
    )
    sending_application: str = Field(
        description="MSH-3: name of the sending application (e.g. 'EHR_PROD').",
    )
    message_datetime: datetime.datetime = Field(
        description="MSH-7: date/time the message was generated (UTC).",
    )
    event_time: datetime.datetime = Field(
        description="EVN-2: date/time the triggering event occurred (UTC).",
    )

    # -- Patient identification (PHI — excluded from default serialisation) --
    patient_mrn: str = Field(
        description="[PHI] PID-3: Medical Record Number (first CX component typed 'MR').",
    )
    patient_last_name: Optional[str] = Field(
        default=None,
        description="[PHI] PID-5.1: Patient family name.",
    )
    patient_first_name: Optional[str] = Field(
        default=None,
        description="[PHI] PID-5.2: Patient given name.",
    )
    patient_dob: Optional[datetime.date] = Field(
        default=None,
        description="[PHI] PID-7: Date of birth.",
    )
    patient_address: Optional[str] = Field(
        default=None,
        description="[PHI] PID-11: Street address (concatenated).",
    )

    # -- Encounter / visit (non-PHI) ----------------------------------------
    encounter_id: str = Field(
        description="PV1-19: Visit number / encounter identifier.",
    )
    patient_class: Optional[str] = Field(
        default=None,
        description="PV1-2: Patient class (I=Inpatient, O=Outpatient, E=Emergency).",
    )
    assigned_location: Optional[str] = Field(
        default=None,
        description="PV1-3: Assigned patient location (e.g. '2E^2012^A').",
    )
    attending_provider: Optional[str] = Field(
        default=None,
        description="PV1-7: Attending doctor identifier / name composite.",
    )
    patient_type: Optional[str] = Field(
        default=None,
        description="PV1-18: Patient type code.",
    )
    admit_reason: Optional[str] = Field(
        default=None,
        description="PV2-3: Admit reason text from the Pre-Admission Information segment.",
    )

    # -- Clinical (non-PHI identifiers only) --------------------------------
    diagnoses: list[str] = Field(
        default_factory=list,
        description="DG1-3: List of ICD diagnosis codes (one entry per DG1 segment).",
    )

    # -----------------------------------------------------------------------
    # PHI-safe serialisation helper
    # -----------------------------------------------------------------------

    _PHI_FIELDS: frozenset[str] = frozenset({
        "patient_mrn",
        "patient_last_name",
        "patient_first_name",
        "patient_dob",
        "patient_address",
    })

    def safe_dict(self) -> dict:
        """Return a dict representation with PHI fields redacted.

        Use this method when logging or publishing to Pub/Sub to ensure
        PHI does not appear in structured logs or message payloads.

        PHI fields are replaced with ``"[REDACTED]"``.
        """
        data = self.model_dump()
        for field in self._PHI_FIELDS:
            if field in data and data[field] is not None:
                data[field] = "[REDACTED]"
        return data

    def __repr__(self) -> str:
        """Override repr to prevent PHI appearing in log output."""
        return (
            f"ADTEvent(event_type={self.event_type!r}, "
            f"source_message_id={self.source_message_id!r}, "
            f"encounter_id={self.encounter_id!r})"
        )
