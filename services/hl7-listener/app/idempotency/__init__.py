"""Idempotency sub-package — MSH-10 duplicate detection.

Exports:
  IdempotencyChecker  — async guard that queries adt_event.source_message_id

Design refs:
    DR-022  — HL7 message idempotency: MSH-10 unique constraint on adt_event
    US-013  — SC-2: duplicate detection before Pub/Sub publish
"""
from app.idempotency.idempotency_checker import IdempotencyChecker

__all__ = ["IdempotencyChecker"]
