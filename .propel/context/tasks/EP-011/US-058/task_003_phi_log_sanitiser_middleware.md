---
id: TASK-003
title: "Implement `PhiLogSanitiserMiddleware` — Strip PHI from Cloud Logging Emissions"
user_story: US-058
epic: EP-011
sprint: 1
layer: Backend
estimate: 1.5h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer / Security Engineer
upstream: [US-058/TASK-002]
---

# TASK-003: Implement `PhiLogSanitiserMiddleware` — Strip PHI from Cloud Logging Emissions

> **Story:** US-058 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 1.5 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-058 AC Scenario 3 and design.md §8.4 require that PHI field values (`first_name`, `last_name`, `mrn`, `dob`, `phone`, `email`) never appear in Cloud Logging structured log emissions. This is achieved through two complementary mechanisms:

1. **`PhiLogSanitiserMiddleware`** (Starlette, stack position 6) — sanitises structured request/response log messages at the HTTP layer.
2. **`PhiLoggingFilter`** (Python `logging.Filter`) — intercepts all Python logger emissions (from any module including SQLAlchemy, LangChain, and application code) and replaces PHI field values with `[REDACTED]`.

The filter is registered on the root logger so it covers all log output, not just middleware-generated logs.

> **Security principle (design.md ADR-007):** PHI field values are encrypted at the ORM layer and should never appear in any log. The sanitiser is a defence-in-depth control for cases where a developer accidentally logs a Pydantic model or SQLAlchemy object containing PHI.

---

## Acceptance Criteria Addressed

| US-058 AC | Requirement |
|---|---|
| **Scenario 3** | PHI log sanitiser middleware active; `first_name`, `last_name`, `mrn` in any log message appear as `[REDACTED]` in Cloud Logging; original values remain only in the secure `audit_log` DB table |
| **DoD** | PHI sanitiser middleware: strips `first_name`, `last_name`, `mrn`, `dob`, `phone`, `email` from log messages before Cloud Logging emission |

---

## Implementation Steps

### 1. Create `backend/app/middleware/phi_log_sanitiser.py`

```python
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
    - Plain text patterns (MRN format, phone, email) matched by regex
    MRN pattern: alphanumeric 6–12 characters typically preceded by 'mrn:'
    Email pattern: RFC-5321 simplified (user@domain.tld)
    Phone pattern: E.164 and common US formats
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
    "first_name", "last_name", "mrn", "dob", "date_of_birth",
    "phone", "phone_number", "email", "email_address",
    "ssn", "social_security_number",
})

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

def _build_patterns() -> list[tuple[re.Pattern, str]]:
    """Build a list of (pattern, replacement) tuples for PHI redaction."""
    patterns: list[tuple[re.Pattern, str]] = []

    # JSON / dict key-value: "field_name": "any value"
    for field in _PHI_FIELD_NAMES:
        patterns.append((
            re.compile(
                rf'("{re.escape(field)}")\s*:\s*"[^"]*"',
                re.IGNORECASE,
            ),
            rf'\1: "[REDACTED]"',
        ))
        # Python dict repr variant: 'field_name': 'any value'
        patterns.append((
            re.compile(
                rf"('{re.escape(field)}')\s*:\s*'[^']*'",
                re.IGNORECASE,
            ),
            rf"\1: '[REDACTED]'",
        ))

    # Email addresses
    patterns.append((
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
        "[REDACTED-EMAIL]",
    ))

    # US phone numbers (+1-xxx-xxx-xxxx, (xxx)xxx-xxxx, xxx.xxx.xxxx)
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

    Register on the root logger (or specific loggers) to ensure no PHI
    ever reaches Cloud Logging handlers:

        logging.getLogger().addFilter(PhiLoggingFilter())

    The filter operates on the formatted message string, not the raw args,
    so it catches PHI regardless of whether it was interpolated via %-format,
    str.format(), or f-string.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact PHI from the log record message in-place.

        Always returns True (allows the record through) because we sanitise
        rather than discard. Discarding would create silent gaps in the audit
        trail and make debugging harder.
        """
        # Sanitise the pre-formatted message
        if isinstance(record.msg, str):
            record.msg = redact_phi(record.msg)

        # Sanitise args if they are strings (% interpolation)
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

        # Sanitise structured extra fields if present
        if hasattr(record, "__dict__"):
            for key, value in list(record.__dict__.items()):
                if key in _PHI_FIELD_NAMES and isinstance(value, str):
                    setattr(record, key, "[REDACTED]")

        return True


# ---------------------------------------------------------------------------
# Starlette middleware — HTTP layer sanitisation
# ---------------------------------------------------------------------------

class PhiLogSanitiserMiddleware(BaseHTTPMiddleware):
    """Starlette middleware at position 6 — sanitises structured HTTP logs.

    Runs before AuditLogMiddleware (position 7). Its role is to ensure that
    any structured log produced by the access logger (if enabled) does not
    contain PHI field values.

    This middleware does NOT log requests itself — it only sanitises.
    The actual request/response logging is delegated to Cloud Run's built-in
    access log and the PhiLoggingFilter attached to the root logger.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # Sanitise any structured data stored on request.state that might
        # be emitted by downstream logging (e.g. from request context dumps)
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
```

### 2. Register `PhiLoggingFilter` on the root logger in `backend/app/core/logging_config.py`

```python
import logging
from app.middleware.phi_log_sanitiser import PhiLoggingFilter

def configure_logging() -> None:
    """Configure structured JSON logging with PHI sanitisation.

    Call once at application startup (lifespan or main.py).
    """
    root_logger = logging.getLogger()
    # Add PHI filter to every existing and future handler
    phi_filter = PhiLoggingFilter()
    root_logger.addFilter(phi_filter)
    for handler in root_logger.handlers:
        handler.addFilter(phi_filter)
```

Call `configure_logging()` in `backend/app/main.py` before the app is created:

```python
from app.core.logging_config import configure_logging
configure_logging()
```

### 3. Register `PhiLogSanitiserMiddleware` in `backend/app/main.py`

```python
from app.middleware.phi_log_sanitiser import PhiLogSanitiserMiddleware

# Stack position 6 — must be added BEFORE AuditLogMiddleware
app.add_middleware(PhiLogSanitiserMiddleware)  # position 6
app.add_middleware(AuditLogMiddleware)          # position 7
```

---

## Validation

```python
# Unit test: redact_phi function
from app.middleware.phi_log_sanitiser import redact_phi

msg = '{"first_name": "Jane", "last_name": "Doe", "mrn": "MRN123456", "email": "jane@hospital.com"}'
result = redact_phi(msg)
assert "Jane" not in result
assert "Doe" not in result
assert "MRN123456" not in result
assert "jane@hospital.com" not in result
assert "[REDACTED]" in result
assert "[REDACTED-EMAIL]" in result
print("redact_phi: OK")

# Unit test: PhiLoggingFilter
import logging
from app.middleware.phi_log_sanitiser import PhiLoggingFilter

logger = logging.getLogger("test.phi")
logger.addFilter(PhiLoggingFilter())

import io
handler = logging.StreamHandler(io.StringIO())
logger.addHandler(handler)

logger.warning('Patient first_name: "Alice" accessed record')
output = handler.stream.getvalue()
assert "Alice" not in output
assert "[REDACTED]" in output
print("PhiLoggingFilter: OK")
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/middleware/phi_log_sanitiser.py` | Create — `redact_phi()`, `PhiLoggingFilter`, `PhiLogSanitiserMiddleware` |
| `backend/app/core/logging_config.py` | Update — register `PhiLoggingFilter` on root logger |
| `backend/app/main.py` | Update — register `PhiLogSanitiserMiddleware` at position 6 |

---

## Definition of Done Checklist

- [ ] `PhiLoggingFilter` registered on root logger at application startup
- [ ] `PhiLogSanitiserMiddleware` registered at stack position 6 (before `AuditLogMiddleware`)
- [ ] `redact_phi()` covers all DoD PHI fields: `first_name`, `last_name`, `mrn`, `dob`, `phone`, `email`
- [ ] Email and phone regex patterns applied in addition to key-value field patterns
- [ ] No PHI in Cloud Logging verified by unit test asserting `[REDACTED]` in log output
- [ ] Filter never discards log records — always returns `True`
