---
id: TASK-004
title: "POST /api/v1/chat Endpoint — JWT Scope Enforcement, Full Pipeline Integration"
user_story: US-043
epic: EP-008
sprint: 2
layer: Backend / API
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-043/TASK-001, US-043/TASK-002, US-043/TASK-003]
---

# TASK-004: POST /api/v1/chat Endpoint — JWT Scope Enforcement, Full Pipeline Integration

> **Story:** US-043 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task wires together all components from TASK-001 through TASK-003 into the `POST /api/v1/chat` FastAPI endpoint and implements the security-critical JWT scope enforcement (US-043 AC Scenario 3).

### Endpoint behaviour

```
POST /api/v1/chat
Authorization: Bearer {patient_jwt}
Body: ChatRequest {message, encounter_id, session_id}

1. Validate JWT (existing middleware — design.md §3.3)
2. Extract `encounter_id` claim from JWT
3. Compare claim with ChatRequest.encounter_id → 403 if mismatch (AC Scenario 3)
4. Load discharge summary via DischargeLoader (TASK-003)
5. Load conversation history via ConversationHistoryService (TASK-002)
6. Assemble 8K context window via ContextAssembler (TASK-003)
7. Call GeminiFlashClient.complete() with 3s timeout (TASK-003)
8. Append user+assistant turns and save history to Redis (TASK-002)
9. Write ChatAuditEvent to HIPAA audit log (encounter_id + timestamp only)
10. Return ChatResponse
```

### JWT scope enforcement (AC Scenario 3)

The patient JWT is issued by the portal flow (design.md §8.2) with a custom claim `encounter_id` set to the specific encounter the patient authenticated for. The endpoint dependency `require_patient_scope` extracts this claim and raises `HTTP 403` if the claim does not match the `encounter_id` in the request body. This prevents a patient from retrieving another patient's discharge context by crafting a request with a different `encounter_id`.

**Security model:**
- The JWT `encounter_id` claim is immutable (signed by the FastAPI auth service at portal login)
- The comparison is performed in the FastAPI dependency — before any DB or LLM call
- The 403 response body contains no information about whether the target encounter exists

**Design references:**
- design.md §3.3 — middleware stack: JWT Validator → RBAC Enforcer → PHI Log Sanitiser → HIPAA Audit Logger → Handler
- design.md §8.2 — patient portal JWT: encounter-scoped, 60-minute expiry
- design.md §8.3 — RBAC: patient role can access own encounter only
- design.md §10.1 — HIPAA audit log: `encounter_id` + event type; no PHI message content
- US-043 AC Scenario 1 — 95th percentile response latency <3 seconds (enforced by GeminiFlashClient)
- US-043 AC Scenario 3 — `encounter_id` in request must match JWT claim; cross-patient access returns 403
- US-043 DoD — audit log records `encounter_id` + message timestamp; no PHI content

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Full pipeline returns response via GeminiFlashClient (3s timeout from TASK-003) |
| Scenario 2 | System prompt from ContextAssembler restricts LLM to own discharge docs |
| Scenario 3 | JWT `encounter_id` claim checked before any data access; mismatch → 403 |
| Scenario 4 | Full context window assembled by ContextAssembler; FIFO history via TASK-002 |

---

## Implementation Steps

### 1. Create router file

```bash
mkdir -p api-gateway/app/routers
touch api-gateway/app/routers/chat.py
```

### 2. Implement `api-gateway/app/routers/chat.py`

```python
"""FastAPI router for the AI Chatbot endpoint (US-043).

Route: POST /api/v1/chat

Security (US-043 AC Scenario 3):
    The patient JWT must contain an `encounter_id` claim matching the
    `encounter_id` field in the request body. Mismatch → HTTP 403.
    No information about the target encounter is disclosed in the error body.

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
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
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
from api_gateway.app.core.auth import get_current_patient_token  # existing auth dependency
from api_gateway.app.core.audit import write_audit_event          # existing HIPAA audit writer
from api_gateway.app.db.session import get_read_session           # read-replica session factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["chatbot"])

# Module-level singletons — instantiated once, reused across requests
_history_service = ConversationHistoryService()
_context_assembler = ContextAssembler()
_gemini_client = GeminiFlashClient()


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


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    request: ChatRequest,
    token_claims: dict = Depends(get_current_patient_token),
    db: AsyncSession = Depends(get_read_session),
) -> ChatResponse:
    """Process a patient chatbot message and return a scoped LLM reply.

    Steps:
        1. Enforce JWT encounter scope (AC Scenario 3) — raises 403 on mismatch.
        2. Load discharge summary from DB (read replica, encrypted field).
        3. Load conversation history from Redis.
        4. Assemble 8K context window (system prompt + discharge + history).
        5. Call Gemini Flash with 3s timeout — returns FALLBACK on timeout.
        6. Append user+assistant turns and persist updated history to Redis.
        7. Write HIPAA audit event (encounter_id + timestamp only).
        8. Return ChatResponse.
    """
    # ── 1. Scope enforcement ──────────────────────────────────────────────────
    jwt_encounter_id: str = token_claims.get("encounter_id", "")
    _enforce_encounter_scope(request.encounter_id, jwt_encounter_id)

    # ── 2. Load discharge summary ─────────────────────────────────────────────
    discharge_summary = await load_discharge_summary(request.encounter_id, db)

    # ── 3. Load conversation history ──────────────────────────────────────────
    history = await _history_service.load(request.encounter_id, request.session_id)

    # ── 4. Assemble context window ────────────────────────────────────────────
    messages = _context_assembler.assemble(
        user_message=request.message,
        discharge_summary=discharge_summary,
        conversation_history=history,
    )

    # ── 5. Call Gemini Flash ──────────────────────────────────────────────────
    reply_text, generation_type, tokens_used = await _gemini_client.complete(
        messages=messages,
        encounter_id=request.encounter_id,
        session_id=request.session_id,
    )

    # ── 6. Persist updated history ────────────────────────────────────────────
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

    # ── 7. Write HIPAA audit event ────────────────────────────────────────────
    # Only encounter_id and timestamp are logged — NO message content (US-043 DoD)
    audit_event = ChatAuditEvent(
        encounter_id=request.encounter_id,
        session_id=request.session_id,
        message_timestamp=now,
        generation_type=generation_type,
    )
    await write_audit_event("PATIENT_CHAT", audit_event.model_dump())

    # ── 8. Return response ────────────────────────────────────────────────────
    return ChatResponse(
        reply=reply_text,
        session_id=request.session_id,
        encounter_id=request.encounter_id,
        generation_type=generation_type,
        tokens_used=tokens_used,
    )
```

### 3. Register the router in `api-gateway/app/main.py`

Add to the existing router registration block:

```python
from api_gateway.app.routers.chat import router as chat_router

app.include_router(chat_router)
```

---

## Validation Checklist

```bash
# Syntax check
python -c "
import ast, pathlib
src = pathlib.Path('api-gateway/app/routers/chat.py').read_text()
ast.parse(src)
print('chat.py — syntax OK')
"

# Confirm the router is registered in main.py
python -c "
src = open('api-gateway/app/main.py').read()
assert 'chat_router' in src, 'chat_router not registered in main.py'
print('chat_router registered in main.py ✓')
"

# Confirm no PHI field names appear in logger calls within the router
python -c "
import re, pathlib
src = pathlib.Path('api-gateway/app/routers/chat.py').read_text()
phi_fields = ['mrn', 'first_name', 'last_name', 'dob', 'phone', 'email']
for field in phi_fields:
    pattern = rf'logger\.\w+\(.*{field}.*\)'
    if re.search(pattern, src, re.IGNORECASE):
        raise AssertionError(f'PHI field \"{field}\" found in logger call')
print('No PHI fields in logger calls ✓')
"
```

---

## Definition of Done

- [ ] `api-gateway/app/routers/chat.py` created with `POST /api/v1/chat` endpoint
- [ ] `_enforce_encounter_scope()` called before any DB or LLM operation — 403 on mismatch
- [ ] 403 response body is `{"detail": "Access denied."}` — no encounter existence disclosure
- [ ] `discharge_loader.load_discharge_summary()` called with read-replica session
- [ ] `ConversationHistoryService.load()` and `append_and_save()` called in correct order
- [ ] `GeminiFlashClient.complete()` result destructured to `(reply_text, generation_type, tokens_used)`
- [ ] `ChatAuditEvent` written with `encounter_id`, `session_id`, `message_timestamp` only — no `message` content
- [ ] `chat_router` registered in `api-gateway/app/main.py`
- [ ] Syntax check passes without errors
