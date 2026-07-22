"""MSH-10 idempotency guard for the HL7 Listener service.

Queries the ``adt_event`` table to determine whether an HL7 message with
the given MSH-10 message control ID has already been processed.

Why MSH-10 (message control ID)?
  DR-022 designates MSH-10 as the natural idempotency key.  EHR systems
  retransmit unacknowledged messages with the same MSH-10, so a unique
  constraint on ``adt_event.source_message_id`` (plus a B-tree index)
  allows the listener to short-circuit duplicate processing in O(log n)
  time before doing any Pub/Sub publish or agent work.

Database contract:
  - Table: ``adt_event``
  - Column: ``source_message_id``  (VARCHAR, unique, indexed)
  - The column and index are created by US-006 (schema migration).
  - This module performs a read-only ``SELECT EXISTS`` — it never writes.

Async pattern:
  - Uses ``AsyncSession`` from SQLAlchemy 2.x async engine.
  - Session is injected by the caller (MLLP pipeline, TASK-004) so this
    module remains independently testable.

Design refs:
    DR-022  — MSH-10 idempotency unique constraint
    US-013  — SC-2: duplicate returns AA ACK, no adt_event record created
    TR-001  — API async handlers; read replica for GET endpoints
    ADR-003 — Cloud SQL PostgreSQL as system of record
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class IdempotencyChecker:
    """Async guard that checks whether an HL7 message has already been processed.

    Usage::

        checker = IdempotencyChecker()

        async with async_session() as session:
            if await checker.is_duplicate(session, "MSG-20260714-001"):
                # Return AA ACK immediately — skip all processing
                return build_ack_response(raw_hl7)

    This class is stateless; instantiate once and reuse across requests.
    """

    async def is_duplicate(
        self,
        session: AsyncSession,
        msg_control_id: str,
    ) -> bool:
        """Check whether ``msg_control_id`` already exists in ``adt_event``.

        Uses ``SELECT EXISTS`` which short-circuits on the first matching
        index entry — O(log n) via the B-tree index on ``source_message_id``.

        Args:
            session:         SQLAlchemy async session (read-only access used).
            msg_control_id:  MSH-10 value from the incoming HL7 message.

        Returns:
            ``True``  — duplicate: ACK and skip further processing.
            ``False`` — new message: proceed with archive and publish.

        Raises:
            sqlalchemy.exc.SQLAlchemyError — propagated on DB connectivity failure.
                The MLLP pipeline (TASK-004) catches this and treats it as a
                non-duplicate (fail-open) to avoid blocking ACK indefinitely.
        """
        stmt = text(
            "SELECT EXISTS("
            "  SELECT 1 FROM adt_event"
            "  WHERE source_message_id = :msg_id"
            ")"
        )
        result = await session.execute(stmt, {"msg_id": msg_control_id})
        exists: bool = result.scalar_one()

        if exists:
            logger.info(
                "duplicate_message_skipped",
                extra={
                    "event": "duplicate_message_skipped",
                    "message_id": msg_control_id,
                },
            )
        return exists
