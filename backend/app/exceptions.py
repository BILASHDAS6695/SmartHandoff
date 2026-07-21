"""Application-level exception hierarchy.

Exceptions here are caught by FastAPI exception handlers and converted
to structured HTTP responses. No PHI is included in exception messages.
"""
from __future__ import annotations

from fastapi import HTTPException, status


class EncounterStateTransitionError(HTTPException):
    """Raised when an invalid encounter status transition is attempted.

    Returns HTTP 409 Conflict.
    No encounter data (patient ID, MRN) is included in the detail message
    to prevent PHI leakage in error responses (OWASP A01).
    """

    def __init__(
        self,
        from_status: str,
        to_status: str,
        *,
        encounter_id: str | None = None,
    ) -> None:
        detail = (
            f"Invalid encounter status transition: "
            f"'{from_status}' \u2192 '{to_status}'. "
            "Transition is not permitted by the clinical workflow rules."
        )
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )
        self.from_status = from_status
        self.to_status = to_status
        self.encounter_id = encounter_id  # Used for logging only, not exposed in response
