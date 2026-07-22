"""HL7 ADT event handler sub-package.

Exports:
  register_cancellation_handlers — registers A11/A12/A13 handlers on the
                                    default ADTRouter at application startup.

Usage (in ``main.py`` startup)::

    from app.handlers import register_cancellation_handlers
    register_cancellation_handlers()

Design refs:
    FR-006  — A11/A12/A13 triggers must halt in-progress agent workflows
    US-015  — TASK-004: HL7 listener → API Gateway HTTP call for cancellations
"""
from app.handlers.cancellation_handlers import register_cancellation_handlers

__all__ = ["register_cancellation_handlers"]
