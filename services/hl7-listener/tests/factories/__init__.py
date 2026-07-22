"""Test factory for ADTEvent domain objects.

Provides ``make_adt_event()`` as a shared fixture factory used across
unit and integration tests.  All fields have sensible defaults; callers
override only what they need to test.

PHI fields are filled with realistic-looking but entirely synthetic data.
No real patient information is used in any test fixture.
"""
from __future__ import annotations

import datetime
import uuid

from app.parser.models import ADTEvent, EventType


_EVENT_TYPE_MAP: dict[str, EventType] = {
    "ADMIT": EventType.ADMIT,
    "TRANSFER": EventType.TRANSFER,
    "DISCHARGE": EventType.DISCHARGE,
    "REGISTER": EventType.REGISTER,
    "UPDATE": EventType.UPDATE,
    "CANCEL_ADMIT": EventType.CANCEL_ADMIT,
    "CANCEL_TRANSFER": EventType.CANCEL_TRANSFER,
    "CANCEL_DISCHARGE": EventType.CANCEL_DISCHARGE,
}

_DEFAULT_TIMESTAMP = datetime.datetime(2026, 7, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)


def make_adt_event(
    *,
    event_type: str | EventType = "ADMIT",
    encounter_id: str | uuid.UUID | None = None,
    source_message_id: str | None = None,
    patient_mrn: str = "MRN-TEST-001",
    patient_last_name: str = "TestLast",
    patient_first_name: str = "TestFirst",
    patient_dob: datetime.date | None = None,
    event_time: datetime.datetime | None = None,
    message_datetime: datetime.datetime | None = None,
) -> ADTEvent:
    """Build a synthetic ``ADTEvent`` for testing.

    Args:
        event_type:         EventType enum value or its string name
                            (e.g. ``"ADMIT"`` or ``EventType.ADMIT``).
        encounter_id:       Encounter identifier.  Defaults to a new UUID.
        source_message_id:  MSH-10 control ID.  Defaults to a new UUID hex.
        patient_mrn:        Synthetic MRN — never real patient data.
        patient_last_name:  Synthetic last name.
        patient_first_name: Synthetic first name.
        patient_dob:        Synthetic date of birth.
        event_time:         EVN-2 event timestamp (UTC).
        message_datetime:   MSH-7 message timestamp (UTC).

    Returns:
        A fully populated ``ADTEvent`` instance.
    """
    if isinstance(event_type, str):
        resolved_event_type = _EVENT_TYPE_MAP[event_type.upper()]
    else:
        resolved_event_type = event_type

    resolved_encounter_id = str(encounter_id) if encounter_id is not None else str(uuid.uuid4())
    resolved_msg_id = source_message_id or uuid.uuid4().hex

    return ADTEvent(
        source_message_id=resolved_msg_id,
        event_type=resolved_event_type,
        sending_application="TEST-EHR",
        message_datetime=message_datetime or _DEFAULT_TIMESTAMP,
        event_time=event_time or _DEFAULT_TIMESTAMP,
        patient_mrn=patient_mrn,
        patient_last_name=patient_last_name,
        patient_first_name=patient_first_name,
        patient_dob=patient_dob or datetime.date(1980, 1, 15),
        patient_address="123 Test Street",
        encounter_id=resolved_encounter_id,
        patient_class="I",
        assigned_location="2E^2012^A",
        attending_provider="DR-SMITH",
        patient_type="I",
        admit_reason="Chest pain",
        diagnoses=["I21.9"],
    )
