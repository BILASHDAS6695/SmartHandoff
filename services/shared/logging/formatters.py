"""
services/shared/logging/formatters.py

JSON structured log formatter compatible with Cloud Logging ingestion format.

Produces JSON objects on a single line per record that Cloud Logging parses
into structured ``jsonPayload`` entries with automatic severity mapping and
source location.

Trace correlation fields are injected from the active OpenTelemetry span so
Cloud Logging automatically links log entries to Cloud Trace.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from opentelemetry import trace as otel_trace

_SEVERITY_MAP: dict[int, str] = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}


class JsonFormatter(logging.Formatter):
    """
    Format log records as single-line JSON for structured Cloud Logging ingestion.

    Reference:
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
                "nanos": int((record.created % 1) * 1_000_000_000),
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

        # Attach active OTel trace context so Cloud Logging links to Cloud Trace
        span_ctx = otel_trace.get_current_span().get_span_context()
        if span_ctx.is_valid and self._project_id:
            entry["logging.googleapis.com/trace"] = (
                f"projects/{self._project_id}/traces/{span_ctx.trace_id:032x}"
            )
            entry["logging.googleapis.com/spanId"] = f"{span_ctx.span_id:016x}"
            entry["logging.googleapis.com/traceSampled"] = (
                span_ctx.trace_flags.sampled
            )

        # Merge any extra structured fields passed via ``extra={}`` on the log call
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            entry.update(record.extra)

        # Include exception traceback if present
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)
