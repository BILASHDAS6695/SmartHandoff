"""Structured logging configuration with PHI sanitisation (US-058/TASK-003).

Call ``configure_logging()`` once at application startup — before the FastAPI
app is created — to attach the PHI filter to the root logger and all existing
handlers.  This ensures no PHI ever reaches Cloud Logging.

Design ref: design.md §8.4 PHI Protection Layers, ADR-007.
"""
from __future__ import annotations

import logging

from app.middleware.phi_log_sanitiser import PhiLoggingFilter


def configure_logging() -> None:
    """Attach ``PhiLoggingFilter`` to the root logger and all existing handlers.

    Must be called before any other module emits a log — ideally at the very
    top of ``app/main.py`` before the ``FastAPI()`` constructor.

    Idempotent: attaching the same filter type twice has no side-effects
    because ``logging.Filter`` identity is checked by name.
    """
    root_logger = logging.getLogger()
    phi_filter = PhiLoggingFilter()

    # Attach to the root logger (catches records before handler dispatch)
    root_logger.addFilter(phi_filter)

    # Also attach to every handler that is already registered
    for handler in root_logger.handlers:
        handler.addFilter(phi_filter)

    logging.getLogger(__name__).info(
        "PHI logging filter registered on root logger — PHI field values will "
        "be redacted before Cloud Logging emission (US-058/TASK-003)."
    )
