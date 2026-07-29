"""Loads the approved discharge summary content for a given encounter (US-043).

The discharge document content column is AES-256-GCM encrypted at the ORM layer
(ADR-007, design.md §6.1 DR-002). SQLAlchemy TypeDecorators transparently decrypt
on read — the plaintext string is returned here.

This module returns ONLY the content field — it does NOT return patient name,
MRN, or any other PHI beyond the clinical narrative the LLM is permitted to use
(AIR-021: minimum-necessary principle for LLM prompts).

Design refs:
    US-025 — approved discharge document as context source (dependency)
    design.md §6.1 DR-002 — document.content encrypted via SQLAlchemy TypeDecorator
    design.md §7.3 AIR-021 — minimum-necessary PHI in LLM prompts
    design.md §8.3 — patient role can only access own encounter documents
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Lazy import avoids circular imports — the ORM model is defined in the core DB layer
_DISCHARGE_DOCUMENT_MODEL = None


def _get_document_model():
    global _DISCHARGE_DOCUMENT_MODEL
    if _DISCHARGE_DOCUMENT_MODEL is None:
        from backend.app.db.models import DischargeDocument  # noqa: PLC0415
        _DISCHARGE_DOCUMENT_MODEL = DischargeDocument
    return _DISCHARGE_DOCUMENT_MODEL


async def load_discharge_summary(encounter_id: str, db: AsyncSession) -> str | None:
    """Return the decrypted `content` of the approved discharge document.

    Args:
        encounter_id: UUID of the encounter to look up.
        db: Async SQLAlchemy session bound to the read replica (TASK-004 supplies this).

    Returns:
        The plaintext discharge summary string, or ``None`` if no approved
        document exists yet (e.g. document not yet generated or not yet approved).
    """
    DischargeDocument = _get_document_model()

    stmt = (
        select(DischargeDocument.content)
        .where(
            DischargeDocument.encounter_id == encounter_id,
            DischargeDocument.status == "APPROVED",
        )
        .order_by(DischargeDocument.updated_at.desc())
        .limit(1)
    )

    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        logger.warning(
            "No approved discharge document found for encounter_id=%s; "
            "chatbot will use fallback instructions.",
            encounter_id,
        )
    return row
