"""FastAPI router for the AI Chatbot endpoint (US-043 + US-044 urgency detection).

Route: POST /api/v1/chat

Security (US-043 AC Scenario 3):
    The patient JWT must contain an `encounter_id` claim matching the
    `encounter_id` field in the request body. Mismatch → HTTP 403.
    No information about the target encounter is disclosed in the error body.

Urgency Detection (US-044):
    The urgency detector runs BEFORE any LLM call (DoD requirement).
    If urgency is detected, the endpoint returns an emergency reply immediately
    without invoking Gemini, within 10 seconds SLA.

Audit logging (US-043 DoD / design.md §10.1):
    Only `encounter_id` and `message_timestamp` (UTC) are written to the
    HIPAA audit log. Message content MUST NOT be logged.

PHI safety (design.md AIR-021):
    `ChatRequest.message` is passed to GeminiFlashClient via ContextAssembler.
    It does NOT appear in any structured log field.

Design refs:
    design.md §3.3 — middleware stack; JWT validated before this handler is reached
    design.md §8.2 — patient JWT encounter scope; 60-minute expiry
    design.md §8.3 — patient role: own encounter only
    design.md §10.1 — HIPAA audit log fields
    US-043 AC Scenarios 1, 2, 3, 4
    US-044 DoD — urgency detection BEFORE LLM call; 10-second SLA
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.agents.patient_comm.chatbot.context_assembler import ContextAssembler
from backend.app.agents.patient_comm.chatbot.discharge_loader import load_discharge_summary
from backend.app.agents.patient_comm.chatbot.gemini_client import GeminiFlashClient
from backend.app.agents.patient_comm.chatbot.history_service import ConversationHistoryService
from backend.app.agents.patient_comm.chatbot.schemas import (
    ChatAuditEvent,
    ChatRequest,
    ChatResponse,
    ConversationMessage,
    MessageRole,
)
from backend.app.agents.patient_comm.chatbot.transcript_service import (
    TranscriptPersistenceService,
)
from backend.app.agents.patient_comm.urgency.detector import UrgencyDetector
from backend.app.agents.patient_comm.urgency.emergency_handler import EmergencyAlertHandler
from backend.app.core.auth.dependencies import get_current_patient_user
from backend.app.core.auth.jwt import _ALGORITHM, _jwt_signing_key
from backend.app.db.deps import get_read_db
from backend.app.models.encounter import Encounter
from backend.app.models.patient import Patient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chatbot"])

# Module-level singletons — instantiated once, reused across requests
_history_service = ConversationHistoryService()
_context_assembler = ContextAssembler()
_gemini_client = GeminiFlashClient()
_urgency_detector = UrgencyDetector()
_emergency_handler = EmergencyAlertHandler()


def _enforce_encounter_scope(
    request_encounter_id: str,
    jwt_encounter_id: str,
) -> None:
    """Raise HTTP 403 if the request encounter_id does not match the JWT claim.

    US-043 AC Scenario 3:
        The comparison is performed BEFORE any DB or LLM call.
        The 403 response body contains no information about whether the
        target encounter exists — preventing information enumeration.
    """
    if request_encounter_id != jwt_encounter_id:
        logger.warning(
            "Encounter scope violation: request_encounter_id=%s jwt_encounter_id=%s",
            request_encounter_id,
            jwt_encounter_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied.",
        )


async def _get_patient_encounter_scope(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer(auto_error=True))],
    patient_user: Annotated[dict, Depends(get_current_patient_user)] = None,
) -> str:
    """Extract and validate encounter_id from patient JWT.

    Steps:
        1. Verify the user is a patient (via get_current_patient_user).
        2. Decode the JWT token to extract the encounter_id claim.
        3. Return the encounter_id for use in scope enforcement.

    Args:
        credentials: Bearer token from Authorization header (extracted by HTTPBearer).
        patient_user: Validated patient TokenClaims (used only to ensure patient role).

    Returns:
        str: The encounter_id claim from the JWT.

    Raises:
        HTTPException 401: If the token is invalid or encounter_id is missing.
    """
    # Step 1 is satisfied by the patient_user dependency
    # (get_current_patient_user validates role, raises 401 on invalid JWT)

    # Step 2: Decode JWT to extract encounter_id claim
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            _jwt_signing_key(),
            algorithms=[_ALGORITHM],
            options={"verify_exp": True},
        )
    except JWTError as exc:
        logger.warning(
            "JWT decode failed when extracting encounter_id: %s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from exc

    # Step 3: Extract and validate encounter_id claim
    encounter_id = payload.get("encounter_id")
    if not encounter_id:
        logger.warning("JWT missing required encounter_id claim")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token: missing encounter_id claim",
        )

    return str(encounter_id)


def _get_read_session() -> AsyncSession:
    """Return an async SQLAlchemy session bound to the read replica.

    This dependency is injected via Depends(get_read_db), which provides
    an AsyncSession from the read replica connection pool (design.md §6.2).
    """
    # Placeholder - the actual implementation is provided by FastAPI
    # dependency injection via Depends(get_read_db)
    pass


async def _get_patient_first_name(db: AsyncSession, encounter_id: str) -> str:
    """Retrieve patient first name (only) from the encounter record.

    The ORM decrypts the field-level encryption (ADR-007) transparently.
    Only first_name is retrieved — not full name, not MRN, not DOB.

    Returns 'Patient' as fallback if the encounter is not found, ensuring
    the alert can still be dispatched without blocking on a DB error.
    """
    try:
        result = await db.execute(
            select(Patient.first_name)
            .join(Encounter, Encounter.patient_id == Patient.id)
            .where(Encounter.id == encounter_id)
            .limit(1)
        )
        first_name = result.scalar_one_or_none()
        return first_name or "Patient"
    except Exception:
        return "Patient"


async def _write_audit_event(event: ChatAuditEvent) -> None:
    """Write an event to the HIPAA audit log via structured logging.

    Args:
        event: ChatAuditEvent with encounter_id, session_id, message_timestamp, generation_type.

    Note:
        Per US-043 DoD: Only encounter_id, session_id, message_timestamp, and generation_type
        are logged. Message content is NEVER logged (PHI protection).
    """
    logger.info(
        "HIPAA audit: patient_chat",
        extra={
            "event_type": "PATIENT_CHAT",
            "encounter_id": str(event.encounter_id),
            "session_id": str(event.session_id),
            "message_timestamp": event.message_timestamp.isoformat(),
            "generation_type": event.generation_type,
        },
    )


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    request: ChatRequest,
    encounter_id: Annotated[str, Depends(_get_patient_encounter_scope)],
    db: AsyncSession = Depends(get_read_db),
) -> ChatResponse:
    """Process a patient chatbot message and return a scoped LLM reply.

    Pipeline order (US-044 DoD: urgency detection BEFORE LLM call):
        1. Enforce JWT encounter scope (AC Scenario 3) — raises 403 on mismatch.
        2. [NEW] Urgency detection (US-044) — returns emergency reply if urgent
        3. Load discharge summary from DB (read replica, encrypted field).
        4. Load conversation history from Redis.
        5. Assemble 8K context window (system prompt + discharge + history).
        6. Call Gemini Flash with 3s timeout — returns FALLBACK on timeout.
        7. Append user+assistant turns and persist updated history to Redis.
        8. Write HIPAA audit event (encounter_id + timestamp only).
        9. Return ChatResponse.
    """
    # ── 1. Scope enforcement ──────────────────────────────────────────────────
    # Extracted by _get_patient_encounter_scope() dependency;
    # now validate it matches the request body.
    _enforce_encounter_scope(request.encounter_id, encounter_id)

    # ── 2. [NEW] Urgency detection (US-044) ────────────────────────────────────
    # US-044 DoD: urgency detection BEFORE LLM call, NOT as post-processing
    urgency_result = await _urgency_detector.detect(request.message)

    if urgency_result.is_urgent:
        # Retrieve patient first name for the alert (minimum PHI)
        patient_first_name = await _get_patient_first_name(db, request.encounter_id)

        # Dispatch emergency response: hardcoded reply + Pub/Sub alert + DB flag
        emergency_reply = await _emergency_handler.handle(
            urgency_result=urgency_result,
            encounter_id=request.encounter_id,
            patient_first_name=patient_first_name,
            db_session=db,
        )

        # ── [US-046] Persist urgent exchange to transcript ──────────────────────
        # Even urgent messages must be persisted with urgency_flag=True
        # escalated=True because emergency_handler publishes to Pub/Sub
        now = datetime.now(timezone.utc)
        transcript_svc = TranscriptPersistenceService(db)
        await transcript_svc.persist_exchange(
            encounter_id=uuid.UUID(request.encounter_id),
            patient_message=request.message,
            assistant_reply=emergency_reply,
            exchange_timestamp=now,
            urgency_flag=True,
            escalated=True,
        )

        # Return emergency reply immediately — no LLM call (US-044 DoD)
        return ChatResponse(
            reply=emergency_reply,
            session_id=request.session_id,
            encounter_id=request.encounter_id,
            generation_type="EMERGENCY",
            tokens_used=None,
        )

    # ── 3. Load discharge summary ─────────────────────────────────────────────
    discharge_summary = await load_discharge_summary(request.encounter_id, db)

    # ── 4. Load conversation history ──────────────────────────────────────────
    history = await _history_service.load(request.encounter_id, request.session_id)

    # ── 5. Assemble context window ────────────────────────────────────────────
    messages = _context_assembler.assemble(
        user_message=request.message,
        discharge_summary=discharge_summary,
        conversation_history=history,
    )

    # ── 6. Call Gemini Flash ──────────────────────────────────────────────────
    reply_text, generation_type, tokens_used = await _gemini_client.complete(
        messages=messages,
        encounter_id=request.encounter_id,
        session_id=request.session_id,
    )

    # ── 7. Persist updated history ────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    user_turn = ConversationMessage(
        role=MessageRole.USER,
        content=request.message,
        timestamp=now,
    )
    assistant_turn = ConversationMessage(
        role=MessageRole.ASSISTANT,
        content=reply_text,
        timestamp=now,
    )
    await _history_service.append_and_save(history, user_turn, assistant_turn)

    # ── 8. [NEW] Persist transcript (US-046) ───────────────────────────────────
    # Fire-and-forget: DB write failure must NOT block HTTP response
    # Escalation was not triggered in normal (non-urgent) flow
    transcript_svc = TranscriptPersistenceService(db)
    await transcript_svc.persist_exchange(
        encounter_id=uuid.UUID(request.encounter_id),
        patient_message=request.message,
        assistant_reply=reply_text,
        exchange_timestamp=now,
        urgency_flag=False,
        escalated=False,
    )

    # ── 9. Write HIPAA audit event ────────────────────────────────────────────
    # Only encounter_id and timestamp are logged — NO message content (US-043 DoD)
    audit_event = ChatAuditEvent(
        encounter_id=request.encounter_id,
        session_id=request.session_id,
        message_timestamp=now,
        generation_type=generation_type,
    )
    await _write_audit_event(audit_event)

    # ── 10. Return response ───────────────────────────────────────────────────
    return ChatResponse(
        reply=reply_text,
        session_id=request.session_id,
        encounter_id=request.encounter_id,
        generation_type=generation_type,
        tokens_used=tokens_used,
    )
