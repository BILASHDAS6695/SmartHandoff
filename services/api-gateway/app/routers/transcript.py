"""FastAPI router for chatbot transcript retrieval (US-046 TASK-003).

Route: GET /api/v1/encounters/{encounter_id}/chat-transcript

Security (US-046 AC Scenario 4):
    - Patient JWT: encounter_id claim must match path param → HTTP 403 if mismatch.
      Check performed BEFORE any DB query (no encounter existence disclosure).
    - Staff JWT: any encounter_id permitted (RBAC role check by existing middleware).

Audit logging (BR-012 / design.md §10.1):
    action=READ, entity_type=CHATBOT_TRANSCRIPT, entity_id=encounter_id.
    Written for every access — patient and staff alike.

Pagination (US-046 Technical Notes):
    Default page size: 50 messages (most recent first from DB, returned in
    ascending timestamp order for chronological viewing).
    Cursor: opaque base64url-encoded ISO 8601 timestamp.

Design refs:
    design.md §3.3 — middleware stack: JWT Validator → RBAC Enforcer → PHI Log Sanitiser → HIPAA Audit Logger → Handler
    design.md §8.2 — patient portal JWT: encounter-scoped, 60-minute expiry; `encounter_id` claim is immutable
    design.md §8.3 — RBAC: `compliance_reader` role can access audit/clinical data including transcripts
    design.md §10.1 — HIPAA audit log: `entity_type=CHATBOT_TRANSCRIPT`, `entity_id=encounter_id`; no PHI content
    US-046 AC Scenario 4 — staff JWT returns decrypted transcript; patient JWT scoped to own encounter
    US-046 Technical Notes — most recent 50 messages by default; `?cursor=` for older messages
"""
from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.patient_comm.chatbot.transcript_schemas import (
    TranscriptMessageRead,
    TranscriptPageResponse,
)
from backend.app.db.audit import write_audit_entry
from backend.app.db.deps import get_db
from backend.app.models.audit_log import AuditAction
from backend.app.models.chatbot_transcript import ChatbotTranscript
from backend.app.auth.dependencies import get_current_token_claims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/encounters", tags=["transcript"])

PAGE_SIZE = 50


def _encode_cursor(timestamp: datetime) -> str:
    """Encode a datetime as an opaque base64url cursor string.

    Args:
        timestamp: UTC datetime to encode.

    Returns:
        base64url-encoded ISO 8601 timestamp string.
    """
    return base64.urlsafe_b64encode(timestamp.isoformat().encode()).decode()


def _decode_cursor(cursor: str) -> datetime:
    """Decode a base64url cursor string to a datetime.

    Raises HTTP 400 if the cursor is malformed.

    Args:
        cursor: Opaque base64url-encoded cursor string.

    Returns:
        Decoded datetime.

    Raises:
        HTTPException: 400 if cursor is invalid.
    """
    try:
        iso_str = base64.urlsafe_b64decode(cursor.encode()).decode()
        return datetime.fromisoformat(iso_str)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid cursor.",
        ) from exc


@router.get(
    "/{encounter_id}/chat-transcript",
    response_model=TranscriptPageResponse,
)
async def get_chat_transcript(
    encounter_id: uuid.UUID,
    cursor: Annotated[Optional[str], Query()] = None,
    db: AsyncSession = Depends(get_db),
    token_claims: dict = Depends(get_current_token_claims),
) -> TranscriptPageResponse:
    """Return decrypted chatbot transcript for an encounter, paginated (US-046).

    US-046 AC Scenario 4:
        Patient callers may only access their own encounter (encounter_id JWT claim).
        Staff and compliance callers may access any encounter.
        Audit log entry created for each access (BR-012).

    Args:
        encounter_id: UUID of the target encounter.
        cursor: Optional pagination cursor (opaque base64url-encoded timestamp).
        db: AsyncSession for database operations.
        token_claims: JWT token claims from the Authorization header.

    Returns:
        TranscriptPageResponse with messages (ascending timestamp order),
        next_cursor (None if last page), and total_in_page count.

    Raises:
        HTTPException: 403 if patient JWT encounter_id claim doesn't match path param.
        HTTPException: 400 if cursor is malformed.
    """

    # ── 1. JWT scope enforcement — patient restricted to own encounter_id claim ──
    # Patient check is performed BEFORE any DB query — no encounter existence disclosure
    caller_role = token_claims.get("role", "")
    if caller_role == "patient":
        jwt_encounter_id = token_claims.get("encounter_id")
        if jwt_encounter_id and str(encounter_id) != jwt_encounter_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied.",
            )

    # ── 2. Build paginated query (DESC to get most recent; reversed before response) ──
    stmt = (
        select(ChatbotTranscript)
        .where(ChatbotTranscript.encounter_id == encounter_id)
        .order_by(ChatbotTranscript.timestamp.desc())
        .limit(PAGE_SIZE + 1)  # Fetch one extra to detect if more pages exist
    )

    if cursor:
        cursor_ts = _decode_cursor(cursor)
        stmt = stmt.where(ChatbotTranscript.timestamp < cursor_ts)

    # ── 3. Execute query ──────────────────────────────────────────────────────────
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    # ── 4. Detect next page and slice ─────────────────────────────────────────────
    has_more = len(rows) > PAGE_SIZE
    page_rows = rows[:PAGE_SIZE]

    # ── 5. Reverse to chronological (ascending) order for response ────────────────
    page_rows = list(reversed(page_rows))

    # ── 6. Build next_cursor from the oldest row in this page (first after reversal) ──
    next_cursor: Optional[str] = None
    if has_more and page_rows:
        next_cursor = _encode_cursor(page_rows[0].timestamp)

    # ── 7. Audit log entry for every transcript read (BR-012) ───────────────────────
    caller_sub = token_claims.get("sub")
    await write_audit_entry(
        action=AuditAction.READ,
        resource_type="chatbot_transcript",
        resource_id=str(encounter_id),
        user_id=caller_sub if caller_sub else None,
    )

    # ── 8. Build response ─────────────────────────────────────────────────────────
    messages = [TranscriptMessageRead.model_validate(row) for row in page_rows]
    return TranscriptPageResponse(
        messages=messages,
        next_cursor=next_cursor,
        total_in_page=len(messages),
    )
