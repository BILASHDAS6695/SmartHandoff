---
id: TASK-007
title: "Implement JSON Structured Logging and PHI Redaction Middleware (Shared Python Library)"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: Application
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-006]
---

# TASK-007: Implement JSON Structured Logging and PHI Redaction Middleware (Shared Python Library)

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Application | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-004 DoD requires: *"Structured logging format (JSON) with PHI redaction middleware active in all services"*. Acceptance Criterion 4 (Scenario 4) specifies that PHI fields (patient name, MRN) in logged messages are replaced with `[REDACTED]` before reaching Cloud Logging standard export.

This task creates a **shared Python logging library** (`services/shared/logging/`) with:

1. A JSON log formatter that outputs structured log entries compatible with Cloud Logging's structured payload format.
2. A PHI redaction filter that scrubs known sensitive field names from `jsonPayload` before emission.
3. A `configure_logging()` helper that each service calls once at startup to wire these components into the root logger.

This complements the Terraform-layer defence-in-depth from TASK-005. The goal is for redaction to happen at the application layer so that even the `_Default` bucket never receives PHI.

---

## Acceptance Criteria Addressed

| US-004 AC | Requirement |
|---|---|
| **Scenario 4** | Cloud Logging export shows PHI fields replaced with `[REDACTED]`; application-layer redaction prevents PHI from reaching the standard log bucket |

---

## Implementation Steps

### 1. Create `services/shared/logging/__init__.py`

```python
"""Shared structured JSON logging library with PHI redaction for SmartHandoff."""
from .setup import configure_logging
from .formatters import JsonFormatter
from .filters import PhiRedactionFilter

__all__ = ["configure_logging", "JsonFormatter", "PhiRedactionFilter"]
```

### 2. Create `services/shared/logging/formatters.py`

Outputs log records as Cloud Logging-compatible JSON. Includes the active OpenTelemetry trace ID so Cloud Logging can correlate logs with traces.

```python
"""JSON log formatter that emits Cloud Logging-compatible structured entries."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from opentelemetry import trace as otel_trace


# Map Python log level names to Cloud Logging severity strings
_SEVERITY_MAP: dict[int, str] = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}


class JsonFormatter(logging.Formatter):
    """
    Format log records as JSON for structured ingestion by Cloud Logging.

    The output payload matches the Cloud Logging structured log entry format:
    https://cloud.google.com/logging/docs/structured-logging
    """

    def __init__(self, service_name: str, project_id: str | None = None) -> None:
        super().__init__()
        self._service_name = service_name
        self._project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "severity": _SEVERITY_MAP.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "timestamp": {
                "seconds": int(record.created),
                "nanos": int((record.created % 1) * 1e9),
            },
            "logging.googleapis.com/sourceLocation": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
            "serviceContext": {
                "service": self._service_name,
            },
        }

        # Attach active trace context so Cloud Logging links to Cloud Trace
        span_ctx = otel_trace.get_current_span().get_span_context()
        if span_ctx.is_valid and self._project_id:
            entry["logging.googleapis.com/trace"] = (
                f"projects/{self._project_id}/traces/{span_ctx.trace_id:032x}"
            )
            entry["logging.googleapis.com/spanId"] = f"{span_ctx.span_id:016x}"
            entry["logging.googleapis.com/traceSampled"] = span_ctx.trace_flags.sampled

        # Merge any extra structured fields passed via `extra={}` on the log call
        if hasattr(record, "extra"):
            entry.update(record.extra)

        # Include exception info if present
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)
```

### 3. Create `services/shared/logging/filters.py`

```python
"""
PHI redaction log filter.

Scrubs known PHI field names from structured log ``extra`` payloads
and from free-text ``message`` fields using a pattern-based approach.
"""
from __future__ import annotations

import logging
import re

# Structured field names that must never appear unredacted in standard logs.
# These match the SQLAlchemy ORM model field names defined in the data model.
_PHI_FIELD_NAMES: frozenset[str] = frozenset({
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
})

# Regex patterns for PHI leakage in free-text messages.
# These are conservative patterns that catch common accidental PHI exposure.
_PHI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # MRN formats: MRN: 12345678, mrn=12345678
    (re.compile(r"\b(MRN|mrn)\s*[=:]\s*\d{5,12}\b"), r"\1=[REDACTED]"),
    # DOB patterns: DOB: 1990-01-01, dob=01/01/1990
    (re.compile(r"\b(DOB|dob|date_of_birth)\s*[=:]\s*[\d/\-]+\b"), r"\1=[REDACTED]"),
    # Phone numbers: +1-555-123-4567, (555) 123-4567
    (re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"), "[REDACTED-PHONE]"),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[REDACTED-EMAIL]"),
]

_REDACTED = "[REDACTED]"


class PhiRedactionFilter(logging.Filter):
    """
    Logging filter that redacts PHI from structured ``extra`` fields and
    applies regex-based scrubbing to free-text ``message`` fields.

    Apply to the root logger or to individual handlers.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact structured extra fields
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            record.extra = {
                k: _REDACTED if k in _PHI_FIELD_NAMES else v
                for k, v in record.extra.items()
            }

        # Redact PHI patterns from the formatted message
        message = record.getMessage()
        for pattern, replacement in _PHI_PATTERNS:
            message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()  # Clear args to prevent double-formatting

        return True  # Always pass the record through (redacted)
```

### 4. Create `services/shared/logging/setup.py`

```python
"""
Logging configuration entrypoint.

Call ``configure_logging(service_name)`` once at application startup.
"""
from __future__ import annotations

import logging
import os
import sys

from .filters import PhiRedactionFilter
from .formatters import JsonFormatter


def configure_logging(service_name: str, level: int = logging.INFO) -> None:
    """
    Configure the root logger with JSON structured output and PHI redaction.

    This replaces any existing handlers on the root logger. Call once
    at application startup before the ASGI server begins handling requests.

    Args:
        service_name: Identifies the service in ``serviceContext.service``.
        level:        Root logging level. Defaults to INFO.
    """
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")

    formatter = JsonFormatter(service_name=service_name, project_id=project_id)
    phi_filter = PhiRedactionFilter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(phi_filter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Prevent third-party libraries from bypassing the root handler
    logging.captureWarnings(True)
```

---

## Files Changed

| File | Action |
|---|---|
| `services/shared/logging/__init__.py` | Create |
| `services/shared/logging/formatters.py` | Create |
| `services/shared/logging/filters.py` | Create |
| `services/shared/logging/setup.py` | Create |

---

## Definition of Done

- [ ] `configure_logging("test-svc")` executes without error
- [ ] Log output is valid JSON with `severity`, `message`, `timestamp`, and `serviceContext` fields
- [ ] A log message containing `mrn=12345678` has the MRN replaced with `[REDACTED]` in the emitted JSON
- [ ] A structured log with `extra={"first_name": "John"}` emits `"first_name": "[REDACTED]"` in the JSON output
- [ ] Trace context (`logging.googleapis.com/trace`) is present in log entries when an active OTel span exists
- [ ] Unit tests cover: PHI regex patterns, structured field redaction, trace ID injection, and JSON format compliance
