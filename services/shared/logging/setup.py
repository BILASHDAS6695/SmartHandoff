"""
services/shared/logging/setup.py

Logging configuration entrypoint.

Call ``configure_logging(service_name)`` once at application startup,
immediately after ``init_tracer()``.

Example:
    from shared.otel import init_tracer
    from shared.logging import configure_logging

    init_tracer(service_name="api-gateway")
    configure_logging(service_name="api-gateway")
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

    * Replaces any existing handlers on the root logger.
    * Uses ``JsonFormatter`` for Cloud Logging-compatible structured output.
    * Installs ``PhiRedactionFilter`` on the root logger so every handler
      benefits from PHI scrubbing.
    * Reads ``GOOGLE_CLOUD_PROJECT`` to embed the project ID in trace links.
    * Reads ``LOG_LEVEL`` env var to allow runtime level override without
      re-deploying (e.g. ``LOG_LEVEL=DEBUG`` in Cloud Run revision env).

    Args:
        service_name: Logical service identifier embedded in every log entry.
        level:        Default log level; overridden by ``LOG_LEVEL`` env var.
    """
    log_level = _parse_level(os.environ.get("LOG_LEVEL", ""), default=level)
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")

    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove any pre-existing handlers (avoids duplicate output when called
    # by test fixtures that reinitialise the logging config).
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(JsonFormatter(service_name=service_name, project_id=project_id))
    root.addHandler(handler)

    # Add PHI redaction filter at the root logger level so it applies to
    # *all* handlers, including any added later by third-party libraries.
    root.addFilter(PhiRedactionFilter())


def _parse_level(level_str: str, default: int) -> int:
    """
    Convert a string log level to a ``logging`` integer constant.

    Returns ``default`` if ``level_str`` is empty or unrecognised.
    """
    if not level_str:
        return default
    numeric = logging.getLevelName(level_str.upper())
    if isinstance(numeric, int):
        return numeric
    return default
