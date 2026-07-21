"""
services/shared/logging/filters.py

PHI redaction log filter.

Scrubs known PHI field names from structured ``extra`` payloads and applies
regex-based scrubbing to free-text ``message`` fields before records reach
any handler.

This is the primary application-layer control.  The Terraform
``google_logging_project_exclusion`` resource (TASK-005) is the defence-in-depth
backstop for any records that bypass this filter.
"""
from __future__ import annotations

import logging
import re

# Structured field names that must never appear unredacted in standard logs.
# These match the SQLAlchemy ORM model field names defined in the data model.
_PHI_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "patient_name",
        "first_name",
        "last_name",
        "mrn",
        "date_of_birth",
        "dob",
        "phone_number",
        "phone",
        "email_address",
        "email",
        "ssn",
        "address",
        "zip_code",
    }
)

# Regex patterns for PHI leakage in free-text message strings.
# Listed in order from most-specific to least-specific to avoid partial matches.
_PHI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # SSN: 123-45-6789
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED-SSN]"),
    # MRN patterns: MRN: 12345678, mrn=87654321
    (re.compile(r"\b(MRN|mrn)\s*[=:]\s*\d{5,12}\b"), r"\1=[REDACTED]"),
    # DOB patterns: DOB: 1990-01-01, dob=01/01/1990
    (
        re.compile(r"\b(DOB|dob|date_of_birth)\s*[=:]\s*[\d/\-]+\b"),
        r"\1=[REDACTED]",
    ),
    # Phone numbers: +1-555-123-4567, (555) 123-4567, 5551234567
    (
        re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
        "[REDACTED-PHONE]",
    ),
    # Email addresses
    (
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED-EMAIL]",
    ),
]

_REDACTED = "[REDACTED]"


class PhiRedactionFilter(logging.Filter):
    """
    Logging filter that redacts PHI from structured ``extra`` fields and
    applies regex-based scrubbing to free-text ``message`` fields.

    Always returns ``True`` (passes the record through) so no log entries are
    suppressed — they are redacted, not dropped.

    Apply to the root logger at startup via ``configure_logging()``.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        # Redact structured extra fields by field name
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            record.extra = {
                k: _REDACTED if k in _PHI_FIELD_NAMES else v
                for k, v in record.extra.items()
            }

        # Redact PHI patterns from the free-text message
        message = record.getMessage()
        for pattern, replacement in _PHI_PATTERNS:
            message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()  # Clear args to prevent double-formatting after mutation

        return True  # Always pass the (now-redacted) record through
