"""PHI log sanitiser — removes PHI field values from structured log output.

Two components:
  1. PhiLoggingFilter: Python logging.Filter that redacts PHI patterns from
     all logger emissions across the entire process.
  2. PhiLogSanitiserMiddleware: Starlette middleware (stack position 6) that
     strips PHI from any structured dict logged at the HTTP request/response
     boundary.

Design refs:
    design.md §3.3 middleware stack position 6
    design.md §8.4 PHI Protection Layers
    ADR-007         — PHI containment
    SEC-006, BR-021, US-058 AC Scenario 3

PHI fields redacted:
    first_name, last_name, mrn, dob, date_of_birth, phone, phone_number,
    email, email_address, ssn, social_security_number

Redaction strategy:
    - JSON key-value pairs: ``"key": "value"`` → ``"key": "[REDACTED]"``
    - Python dict repr: ``'key': 'value'`` → ``'key': '[REDACTED]'``
    - Standalone email and phone patterns matched by regex
"""
from __future__ import annotations

import logging
import re
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# PHI field names to redact
# ---------------------------------------------------------------------------

_PHI_FIELD_NAMES: frozenset[str] = frozenset({
    "first_name",
    "last_name",
    "mrn",
    "dob",
    "date_of_birth",
    "phone",
    "phone_number",
    "email",
    "email_address",
    "ssn",
    "social_security_number",
})

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------


def _build_patterns() -> list[tuple[re.Pattern, str]]:
    """Build compiled (pattern, replacement) pairs for PHI redaction."""
    patterns: list[tuple[re.Pattern, str]] = []

    for field in _PHI_FIELD_NAMES:
        # JSON format: "field_name": "any value"
        patterns.append((
            re.compile(
                rf'("{re.escape(field)}")\s*:\s*"[^"]*"',
                re.IGNORECASE,
            ),
            r'\1: "[REDACTED]"',
        ))
        # Python dict repr: 'field_name': 'any value'
        patterns.append((
            re.compile(
                rf"('{re.escape(field)}')\s*:\s*'[^']*'",
                re.IGNORECASE,
            ),
            r"\1: '[REDACTED]'",
        ))

    # Standalone email addresses (RFC-5321 simplified)
    patterns.append((
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
        "[REDACTED-EMAIL]",
    ))

    # US phone numbers (+1-xxx-xxx-xxxx, (xxx)xxx-xxxx, xxx.xxx.xxxx, etc.)
    patterns.append((
        re.compile(r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
        "[REDACTED-PHONE]",
    ))

    return patterns


_PATTERNS: list[tuple[re.Pattern, str]] = _build_patterns()


# ---------------------------------------------------------------------------
# Core redaction function
# ---------------------------------------------------------------------------


def redact_phi(text: str) -> str:
    """Apply all PHI redaction patterns to a string.

    Args:
        text: A log message string (JSON, Python repr, or plain text).

    Returns:
        The string with all PHI field values replaced by ``[REDACTED]``.
    """
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Python logging.Filter — covers all logger emissions
# ---------------------------------------------------------------------------


class PhiLoggingFilter(logging.Filter):
    """Logging filter that redacts PHI values from all log record messages.

    Register on the root logger to ensure no PHI ever reaches Cloud Logging::

        logging.getLogger().addFilter(PhiLoggingFilter())

    The filter operates on the pre-formatted message and its args so it catches
    PHI regardless of whether it was interpolated via %-format, str.format(),
    or f-string.  Always returns True (sanitises rather than discards records).
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        """Redact PHI from the log record message in-place.

        Returns:
            Always True — never discards records; only sanitises them.
        """
        # Sanitise the pre-formatted message string
        if isinstance(record.msg, str):
            record.msg = redact_phi(record.msg)

        # Sanitise % interpolation args
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_phi(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_phi(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )

        # Sanitise any extra structured fields that match PHI names
        for key in _PHI_FIELD_NAMES:
            if hasattr(record, key) and isinstance(getattr(record, key), str):
                setattr(record, key, "[REDACTED]")

        return True


# ---------------------------------------------------------------------------
# Starlette middleware — HTTP layer sanitisation
# ---------------------------------------------------------------------------


class PhiLogSanitiserMiddleware(BaseHTTPMiddleware):
    """Starlette middleware at stack position 6 — sanitises structured HTTP logs.

    Runs BEFORE AuditLogMiddleware (position 7).  Does not log requests itself;
    it sanitises any PHI that may have been stored on ``request.state.log_context``
    by upstream middleware or route handlers.

    Registration in main.py (must appear BEFORE AuditLogMiddleware add_middleware
    call because Starlette wraps in reverse order)::

        app.add_middleware(AuditLogMiddleware)        # position 7
        app.add_middleware(PhiLogSanitiserMiddleware) # position 6
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Sanitise any PHI that may have leaked into request.state.log_context
        if hasattr(request.state, "log_context") and isinstance(
            request.state.log_context, dict
        ):
            sanitised: dict[str, Any] = {}
            for k, v in request.state.log_context.items():
                if k in _PHI_FIELD_NAMES:
                    sanitised[k] = "[REDACTED]"
                elif isinstance(v, str):
                    sanitised[k] = redact_phi(v)
                else:
                    sanitised[k] = v
            request.state.log_context = sanitised

        return response
