"""HIPAA audit event logging for patient authentication and portal access."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

log = logging.getLogger(__name__)


async def write_audit_event(
    event_type: str,
    encounter_id: str | UUID,
    patient_id: str | UUID | None = None,
    details: dict | None = None,
) -> None:
    """Write a HIPAA-compliant audit event for patient portal access.

    Audit events are structured logs that include:
    - event_type: e.g., "PATIENT_AUTH_SUCCESS", "PATIENT_AUTH_FAILED"
    - encounter_id: UUID of the encounter (required for audit trail)
    - patient_id: UUID of the patient (if available; PHI tracked separately)
    - timestamp: UTC timestamp of the event
    - details: Additional structured context (no OTP, password, or PHI details)

    Args:
        event_type: Type of event (e.g., "PATIENT_AUTH_SUCCESS")
        encounter_id: UUID string or UUID object of the encounter
        patient_id: UUID string or UUID object of the patient (optional, PHI)
        details: Dictionary of non-sensitive structured data

    Security notes:
        - No OTP, password, or patient phone number in details
        - No raw request body data
        - Encounter and patient IDs are acceptable (encrypted at rest in Cloud Logging)
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    encounter_id_str = str(encounter_id)
    patient_id_str = str(patient_id) if patient_id else None

    audit_payload = {
        "event_type": event_type,
        "encounter_id": encounter_id_str,
        "timestamp": timestamp,
    }

    if patient_id_str:
        audit_payload["patient_id"] = patient_id_str

    if details:
        audit_payload.update(details)

    log.info("audit_event", extra=audit_payload)
