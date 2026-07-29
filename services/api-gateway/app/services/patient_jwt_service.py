"""Patient JWT issuance for the OTP passwordless auth flow (US-052).

Issues a short-lived patient-scoped JWT after successful OTP verification.
The JWT encodes patient_id (sub), encounter_id, and role='patient'.

Design refs:
    US-052 DoD — HS256; sub=patient_id; encounter_id; exp=60 min
    US-052 AC Scenario 1 — JWT returned within 30 s of SMS tap
    US-052 AC Scenario 4 — encounter_id claim enforced by middleware (TASK-004)
    design.md §8.2 — patient JWT scope
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt

from api_gateway.app.core.config import settings

_ALGORITHM = "HS256"
_EXPIRY_MINUTES = 60


def issue_patient_jwt(patient_id: str, encounter_id: str) -> str:
    """Issue a patient-scoped HS256 JWT with encounter_id and 60-minute expiry.

    Claims:
        sub          — patient_id (UUID string)
        encounter_id — encounter UUID string
        role         — "patient"
        exp          — UTC timestamp 60 minutes from now
        iat          — UTC timestamp now

    Returns:
        Signed JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": patient_id,
        "encounter_id": encounter_id,
        "role": "patient",
        "iat": now,
        "exp": now + timedelta(minutes=_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, settings.PATIENT_JWT_SECRET, algorithm=_ALGORITHM)
