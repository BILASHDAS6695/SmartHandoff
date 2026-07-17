---
id: TASK-003
title: "GET /api/v1/encounters/{id}/chat-transcript — JWT Scope Enforcement & Pagination"
user_story: US-046
epic: EP-008
sprint: 2
layer: Backend / API
estimate: 2.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-046/TASK-001, US-046/TASK-002]
---

# TASK-003: GET /api/v1/encounters/{id}/chat-transcript — JWT Scope Enforcement & Pagination

> **Story:** US-046 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-046 requires a `GET /api/v1/encounters/{id}/chat-transcript` endpoint that returns the decrypted, chronologically ordered chatbot transcript for an encounter. The endpoint enforces dual-role JWT scoping (patient vs staff) and supports cursor-based pagination.

### Endpoint behaviour

```
GET /api/v1/encounters/{encounter_id}/chat-transcript?cursor=<opaque_cursor>
Authorization: Bearer {staff_jwt | patient_jwt}

1. Validate JWT (existing middleware — design.md §3.3)
2. Determine caller role from token claims:
   a. Patient JWT (role=patient) → enforce encounter_id claim matches path {id}
      → HTTP 403 {"detail": "Access denied."} if mismatch (no encounter existence disclosed)
   b. Staff JWT (role=staff | compliance | nurse | doctor) → RBAC check only; no encounter restriction
3. Query: SELECT * FROM chatbot_transcript
          WHERE encounter_id = {id}
          [AND timestamp < cursor_timestamp if cursor provided]
          ORDER BY timestamp DESC
          LIMIT 51   (PAGE_SIZE+1 to detect next page)
4. Slice to PAGE_SIZE=50; set next_cursor from oldest row timestamp if has_more=True
5. Reverse slice to chronological (ascending) order for response
6. Write audit log entry: action=READ, entity_type=CHATBOT_TRANSCRIPT, entity_id=encounter_id (BR-012)
7. Return TranscriptPageResponse { messages: [...], next_cursor: str|None, total_in_page: int }
```

### Dual-role JWT scope enforcement

| Caller | JWT claims | Access rule |
|--------|-----------|-------------|
| Patient | `role=patient`, `encounter_id=<uuid>` | Can only read transcript for their own `encounter_id` claim |
| Staff / Compliance | `role=staff` or `role=compliance` | Can read any encounter's transcript (RBAC role check only) |

**Security constraints:**
- Patient check is performed **before** any DB query — no encounter existence information leaked via 403
- `403` response body is always `{"detail": "Access denied."}` regardless of whether encounter exists
- No `encounter_id` enumeration: a patient cannot probe for other encounters via repeated requests

### Pagination design

- **Default:** 50 most recent messages (DESC query, then reversed to ascending for response)
- **Cursor:** opaque `base64url(timestamp.isoformat())` — encodes the `timestamp` of the oldest message in the current page
- **`next_cursor = None`** when no older messages remain
- **Client flow:** pass `?cursor=<value>` to fetch the next (older) page

**Design references:**
- design.md §3.3 — middleware stack: JWT Validator → RBAC Enforcer → PHI Log Sanitiser → HIPAA Audit Logger → Handler
- design.md §8.2 — patient portal JWT: encounter-scoped, 60-minute expiry; `encounter_id` claim is immutable
- design.md §8.3 — RBAC: `compliance_reader` role can access audit/clinical data including transcripts
- design.md §10.1 — HIPAA audit log: `entity_type=CHATBOT_TRANSCRIPT`, `entity_id=encounter_id`; no PHI content
- US-046 AC Scenario 4 — staff JWT returns decrypted transcript; patient JWT scoped to own encounter
- US-046 Technical Notes — most recent 50 messages by default; `?cursor=` for older messages

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 4 | Staff JWT → 200 for any encounter; patient JWT → 403 on cross-encounter access; decrypted list in ascending timestamp order; audit log entry created on each access |

---

## Implementation Steps

### 1. Create transcript router

**File:** `api-gateway/app/routers/transcript.py`

```python
"""FastAPI router for chatbot transcript retrieval (US-046).

Route: GET /api/v1/encounters/{encounter_id}/chat-transcript

Security (US-046 AC Scenario 4):
    - Patient JWT: encounter_id claim must match path param → HTTP 403 if mismatch.
      Check performed BEFORE any DB query (no encounter existence disclosure).
    - Staff JWT: any encounter_id permitted (RBAC role check by existing middleware).

Audit logging (BR-012 / design.md §10.1):
    action=READ, entity_type=CHATBOT_TRANSCRIPT, entity_id=encounter_id.
    Written for every access — patient and staff alike.

Pagination:
    Default page size: 50 messages (most recent first from DB, returned in
    ascending timestamp order). Pass ?cursor= for older pages.
    Cursor: opaque base64url-encoded ISO 8601 timestamp.
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.audit import write_audit_entry
from app.db.session import get_db
from app.models.audit_log import AuditAction
from app.models.chatbot_transcript import ChatbotTranscript
from app.agents.patient_comm.chatbot.transcript_schemas import (
    TranscriptMessageRead,
    TranscriptPageResponse,
)
from app.auth.dependencies import get_current_token_claims

router = APIRouter(prefix="/api/v1/encounters", tags=["transcript"])

PAGE_SIZE = 50


def _encode_cursor(timestamp: datetime) -> str:
    """Encode a datetime as an opaque base64url cursor string."""
    return base64.urlsafe_b64encode(timestamp.isoformat().encode()).decode()


def _decode_cursor(cursor: str) -> datetime:
    """Decode a base64url cursor string to a datetime.

    Raises HTTP 400 if the cursor is malformed.
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
    """Return decrypted chatbot transcript for an encounter, paginated.

    Patient callers may only access their own encounter (encounter_id JWT claim).
    Staff and compliance callers may access any encounter.
    """
    # 1. JWT scope enforcement — patient restricted to own encounter_id claim
    caller_role = token_claims.get("role", "")
    if caller_role == "patient":
        jwt_encounter_id = token_claims.get("encounter_id")
        if str(encounter_id) != jwt_encounter_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied.",
            )

    # 2. Build paginated query (DESC to get most recent; reversed before response)
    stmt = (
        select(ChatbotTranscript)
        .where(ChatbotTranscript.encounter_id == encounter_id)
        .order_by(ChatbotTranscript.timestamp.desc())
        .limit(PAGE_SIZE + 1)
    )
    if cursor:
        cursor_ts = _decode_cursor(cursor)
        stmt = stmt.where(ChatbotTranscript.timestamp < cursor_ts)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    # 3. Detect next page
    has_more = len(rows) > PAGE_SIZE
    page_rows = rows[:PAGE_SIZE]

    # 4. Reverse to chronological (ascending) order for response
    page_rows = list(reversed(page_rows))

    # 5. Build next_cursor from the oldest row in this page (first after reversal)
    next_cursor: Optional[str] = None
    if has_more and page_rows:
        next_cursor = _encode_cursor(page_rows[0].timestamp)

    # 6. Audit log entry for every transcript read (BR-012)
    caller_sub = token_claims.get("sub")
    await write_audit_entry(
        db=db,
        user_id=uuid.UUID(caller_sub) if caller_sub else None,
        action=AuditAction.READ,
        entity_type="CHATBOT_TRANSCRIPT",
        entity_id=encounter_id,
        ip_address=None,   # Populated by HIPAA middleware from X-Forwarded-For
        user_agent=None,
    )

    messages = [TranscriptMessageRead.model_validate(row) for row in page_rows]
    return TranscriptPageResponse(
        messages=messages,
        next_cursor=next_cursor,
        total_in_page=len(messages),
    )
```

### 2. Register router in application entry point

In `api-gateway/app/main.py`, include the transcript router:

```python
from app.routers.transcript import router as transcript_router

app.include_router(transcript_router)
```

---

## Definition of Done Checklist

- [ ] `api-gateway/app/routers/transcript.py` created with `GET /{encounter_id}/chat-transcript` route
- [ ] Patient JWT scope check is the **first operation** in the handler — before any DB query
- [ ] Patient cross-encounter → `HTTP 403 {"detail": "Access denied."}` (no encounter existence disclosure)
- [ ] Staff JWT → `HTTP 200` for any `encounter_id`
- [ ] Query uses `ORDER BY timestamp DESC LIMIT 51` (PAGE_SIZE+1 to detect next page)
- [ ] Response messages are in ascending timestamp order (chronological)
- [ ] `next_cursor` is `None` when fewer than 50 rows returned; non-null when more pages exist
- [ ] `?cursor=<malformed>` → `HTTP 400 {"detail": "Invalid cursor."}`
- [ ] `write_audit_entry()` called with `entity_type="CHATBOT_TRANSCRIPT"` and `entity_id=encounter_id` for every request
- [ ] Router registered in `api-gateway/app/main.py`
