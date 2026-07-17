---
id: TASK-002
title: "Transcript Persistence Service — Store Each Message Pair After Exchange"
user_story: US-046
epic: EP-008
sprint: 2
layer: Backend / Service
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-046/TASK-001, US-043/TASK-004, US-044, US-045]
---

# TASK-002: Transcript Persistence Service — Store Each Message Pair After Exchange

> **Story:** US-046 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / Service | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-046 requires every chatbot message (both patient input and assistant reply) to be persisted after each exchange. This task creates the `TranscriptPersistenceService` and wires it into the existing `POST /api/v1/chat` handler from US-043, immediately after the escalation publish step.

### Service behaviour

After the chatbot produces a reply, the persistence service must:
1. Write the **patient message** row: `role=PATIENT`, `urgency_flag` from urgency detector (US-044), `escalated` from escalation publisher (US-045)
2. Write the **assistant reply** row: `role=ASSISTANT`, `urgency_flag=False`, `escalated=False`
3. Both rows are written in a single DB transaction within the same `AsyncSession`
4. If the DB write fails, the exception is caught, logged, and swallowed — **fire-and-forget** (same pattern as `write_audit_entry()` from US-008)
5. The HTTP response to the patient is unaffected by a transcript write failure

### Integration point in `POST /api/v1/chat`

The persistence call is inserted as step 10, after urgency detection (step 8) and escalation publish (step 9) from US-043/US-044/US-045:

```
POST /api/v1/chat
1.  Validate JWT (middleware)
2.  JWT scope enforcement (encounter_id claim vs request body)
3.  Load discharge summary (DischargeLoader)
4.  Load conversation history (ConversationHistoryService, Redis)
5.  Assemble 8K context window (ContextAssembler)
6.  Call GeminiFlashClient.complete() — 3s timeout
7.  Append turns + save history to Redis (ConversationHistoryService)
8.  Run urgency detector → urgency_flag (US-044)
9.  If urgency_flag → publish escalation alert → escalation_published (US-045)
10. [US-046] persist_exchange(encounter_id, patient_msg, assistant_reply,
        urgency_flag, escalated=escalation_published)   ← NEW THIS TASK
11. Write ChatAuditEvent to HIPAA audit log (encounter_id + timestamp only)
12. Return ChatResponse
```

**Design references:**
- design.md §3.1 — Patient Communication Agent: chatbot, urgency detection, escalation routing
- design.md §10.1 — HIPAA audit log: fire-and-forget; failures must not block HTTP response
- US-043 TASK-004 — `POST /api/v1/chat` handler (`api-gateway/app/routers/chat.py`) is the call site
- US-044 — urgency detector returns `urgency_flag: bool`
- US-045 — escalation publisher sets `escalation_published: bool`
- US-046 AC Scenario 1 — after 5 exchanges, 10 `chatbot_transcript` rows exist (5 PATIENT + 5 ASSISTANT)
- US-046 AC Scenario 2 — urgency message has `urgency_flag=True` and `escalated=True` when escalation was published

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `persist_exchange()` writes 2 rows per call (PATIENT + ASSISTANT); 5 calls → 10 DB rows |
| Scenario 2 | `urgency_flag` and `escalated` passed from urgency detector and escalation publisher to the patient row |
| Scenario 3 | `EncryptedString` TypeDecorator encrypts on `process_bind_param`; plaintext strings passed by this service are encrypted transparently before DB write |

---

## Implementation Steps

### 1. Create transcript persistence service

**File:** `backend/app/agents/patient_comm/chatbot/transcript_service.py`

```python
"""Transcript Persistence Service for chatbot exchanges (US-046).

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
    def __init__(self, db: AsyncSession) -> None:
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

        Args:
            encounter_id:        FK to encounter; must match the JWT encounter_id claim.
            patient_message:     Plaintext patient input. Encrypted by TypeDecorator at bind time.
            assistant_reply:     Plaintext LLM or fallback reply. Encrypted at bind time.
            exchange_timestamp:  UTC datetime of the exchange (from POST /api/v1/chat handler).
            urgency_flag:        True when urgency detection was triggered (US-044 output).
            escalated:           True when escalation alert was published (US-045 output).
        """
        try:
            patient_row = ChatbotTranscript(
                encounter_id=encounter_id,
                message=patient_message,
                role=MessageRole.PATIENT,
                timestamp=exchange_timestamp,
                urgency_flag=urgency_flag,
                escalated=escalated,
            )
            assistant_row = ChatbotTranscript(
                encounter_id=encounter_id,
                message=assistant_reply,
                role=MessageRole.ASSISTANT,
                timestamp=exchange_timestamp,
                urgency_flag=False,
                escalated=False,
            )
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
```

### 2. Wire persistence service into `POST /api/v1/chat` handler

In `api-gateway/app/routers/chat.py` (US-043 TASK-004), insert the persistence call after the escalation publish step and before the HIPAA audit log write:

```python
from datetime import datetime, timezone
import uuid

from app.agents.patient_comm.chatbot.transcript_service import TranscriptPersistenceService

# ... inside the route handler, after escalation_published is set ...

# Step 10 — Persist transcript (US-046); fire-and-forget, must not block response
transcript_svc = TranscriptPersistenceService(db)
await transcript_svc.persist_exchange(
    encounter_id=uuid.UUID(chat_request.encounter_id),
    patient_message=chat_request.message,
    assistant_reply=chat_response.reply,
    exchange_timestamp=datetime.now(tz=timezone.utc),
    urgency_flag=urgency_result.urgency_flag,
    escalated=escalation_published,
)
```

**Note:** `escalation_published` is a `bool` set by the US-045 escalation publisher:
- `True` when `asyncio.create_task(publish_escalation_alert(...))` was invoked
- `False` when urgency_flag was False or escalation was skipped

---

## Definition of Done Checklist

- [ ] `backend/app/agents/patient_comm/chatbot/transcript_service.py` created
- [ ] `TranscriptPersistenceService.persist_exchange()` writes exactly 2 rows per call (PATIENT + ASSISTANT)
- [ ] Patient row receives `urgency_flag` and `escalated` from caller arguments
- [ ] Assistant row always has `urgency_flag=False` and `escalated=False` (hardcoded)
- [ ] DB write failure is caught, logged with encounter_id only (no PHI), rolled back, and **not** re-raised
- [ ] Wired into `POST /api/v1/chat` handler (US-043 TASK-004) as step 10, after escalation publish
- [ ] Log message key: `transcript_persist_failed` — does not include patient message content
- [ ] US-043 handler tests continue to pass after integration
