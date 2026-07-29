"""Transcript Persistence Service for chatbot exchanges (US-046 TASK-002).

Persists every patient message and assistant reply after each chatbot exchange.
The patient message urgency_flag and escalated fields are set by the caller
based on urgency detector (US-044) and escalation publisher (US-045) outputs.

FIRE-AND-FORGET:
    DB write failures are caught, logged (no PHI in log message), and swallowed.
    A transcript write failure MUST NOT propagate to the HTTP response.
    This mirrors the write_audit_entry() pattern from US-008.

ENCRYPTION:
    The `message` column on ChatbotTranscript uses EncryptedString (AES-256-GCM).
    This service passes plaintext strings to the ORM — encryption is handled
    transparently by the TypeDecorator's process_bind_param() method at DB write time.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chatbot_transcript import ChatbotTranscript, MessageRole

logger = logging.getLogger(__name__)


class TranscriptPersistenceService:
    """Service for persisting chatbot message transcripts (US-046).

    Writes patient and assistant messages to the transcript table after
    each chatbot exchange completes. Urgency and escalation flags are
    propagated to the patient row only; assistant rows always have both
    flags set to False.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the persistence service with a database session.

        Args:
            db: AsyncSession for database operations.
        """
        self._db = db

    async def persist_exchange(
        self,
        *,
        encounter_id: uuid.UUID,
        patient_message: str,
        assistant_reply: str,
        exchange_timestamp: datetime,
        urgency_flag: bool = False,
        escalated: bool = False,
    ) -> None:
        """Persist a patient message and assistant reply as two transcript rows.

        Writes exactly 2 rows per call: one PATIENT row and one ASSISTANT row.
        Both rows share the same encounter_id and exchange_timestamp.

        US-046 AC Scenario 1:
            After 5 patient messages, 10 rows exist in the DB (5 PATIENT + 5 ASSISTANT).

        US-046 AC Scenario 2:
            Patient row with urgency_flag=True is stored when detected.
            Escalated status propagates to patient row when escalation was published.

        US-046 AC Scenario 3:
            Message content is encrypted transparently by EncryptedString
            TypeDecorator at database write time. Plaintext passed here is
            never written to the DB.

        Args:
            encounter_id:        FK to encounter; must match the JWT encounter_id claim.
            patient_message:     Plaintext patient input. Encrypted by TypeDecorator at bind time.
            assistant_reply:     Plaintext LLM or fallback reply. Encrypted at bind time.
            exchange_timestamp:  UTC datetime of the exchange (from POST /api/v1/chat handler).
            urgency_flag:        True when urgency detection was triggered (US-044 output).
            escalated:           True when escalation alert was published (US-045 output).

        Note:
            Fire-and-forget contract: DB write failures do NOT raise exceptions.
            The HTTP response is sent unaffected by transcript persistence failures.
        """
        try:
            # Patient message row: receives urgency and escalation flags from caller
            patient_row = ChatbotTranscript(
                encounter_id=encounter_id,
                message=patient_message,
                role=MessageRole.PATIENT,
                timestamp=exchange_timestamp,
                urgency_flag=urgency_flag,
                escalated=escalated,
            )

            # Assistant reply row: always has both flags as False
            assistant_row = ChatbotTranscript(
                encounter_id=encounter_id,
                message=assistant_reply,
                role=MessageRole.ASSISTANT,
                timestamp=exchange_timestamp,
                urgency_flag=False,
                escalated=False,
            )

            # Add both rows and commit in a single transaction
            self._db.add(patient_row)
            self._db.add(assistant_row)
            await self._db.commit()

        except Exception:
            # Log with encounter_id only — no PHI (message content) in log
            logger.exception(
                "transcript_persist_failed encounter_id=%s — HTTP response unaffected",
                encounter_id,
            )
            await self._db.rollback()
            # Fire-and-forget: exception is NOT re-raised
            # HTTP response to patient continues unaffected
