---
id: TASK-005
title: "Chatbot Pipeline Integration — Insert UrgencyDetector Before LLM Call in POST /api/v1/chat"
user_story: US-044
epic: EP-008
sprint: 2
layer: Backend / API
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Backend Engineer
upstream: [US-044/TASK-001, US-044/TASK-002, US-044/TASK-003, US-044/TASK-004, US-043/TASK-004]
---

# TASK-005: Chatbot Pipeline Integration — Insert UrgencyDetector Before LLM Call in POST /api/v1/chat

> **Story:** US-044 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Backend / API | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-044 DoD explicitly states: *"Urgency detection runs BEFORE LLM call — not as post-processing."* This task modifies the existing `POST /api/v1/chat` endpoint (implemented in US-043 TASK-004) to insert the `UrgencyDetector` as the first processing step after JWT scope enforcement.

The integration creates a short-circuit path: if `UrgencyDetector.detect()` returns `is_urgent=True`, the endpoint calls `EmergencyAlertHandler.handle()` and returns the hardcoded emergency reply immediately — bypassing the normal `ContextAssembler` + `GeminiFlashClient` pipeline entirely.

### Modified request flow

```
POST /api/v1/chat
  │
  ├─ 1. JWT scope enforcement (US-043) — unchanged
  │
  ├─ 2. [NEW] UrgencyDetector.detect(message)
  │       ├─ is_urgent=True  → EmergencyAlertHandler.handle() → return emergency reply (HTTP 200)
  │       └─ is_urgent=False → continue to step 3
  │
  ├─ 3. ConversationHistoryService.load() (US-043)
  ├─ 4. ContextAssembler.assemble() (US-043)
  ├─ 5. GeminiFlashClient.chat() (US-043)
  └─ 6. ConversationHistoryService.save() + ChatAuditEvent write (US-043)
```

**Design references:**
- design.md §3.3 — FastAPI backend middleware stack and router structure
- design.md §8.2 — patient JWT encounter-scoped; scope enforcement first
- US-044 DoD — urgency detection runs BEFORE LLM call
- US-043 TASK-004 — `POST /api/v1/chat` handler (being modified by this task)
- US-044 AC Scenario 4 — non-urgent messages proceed to normal chatbot pipeline (no regression)

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Urgency detection runs before LLM; emergency reply returned within 10s |
| Scenario 4 | Non-urgent messages bypass urgency handler and proceed to normal Gemini pipeline |
| Regression (US-043) | All US-043 AC scenarios continue to pass after integration |

---

## Implementation Steps

### 1. Locate and review the existing chat router

The existing handler lives at `api-gateway/app/routers/chat.py` (created in US-043 TASK-004). Review the handler signature before modifying.

```bash
# Confirm the file exists and review its structure
grep -n "async def post_chat\|encounter_id\|GeminiFlashClient\|ContextAssembler" \
    api-gateway/app/routers/chat.py | head -30
```

### 2. Update `api-gateway/app/routers/chat.py`

Modify the `post_chat` handler to inject `UrgencyDetector` and `EmergencyAlertHandler` as module-level singletons and insert the urgency gate as step 2.

```python
# Add to the imports section at the top of api-gateway/app/routers/chat.py:

from backend.app.agents.patient_comm.urgency.detector import UrgencyDetector
from backend.app.agents.patient_comm.urgency.emergency_handler import EmergencyAlertHandler

# Module-level singletons — instantiated once per Cloud Run instance
_urgency_detector = UrgencyDetector()
_emergency_handler = EmergencyAlertHandler()
```

Modify the `post_chat` handler body to add the urgency gate after scope enforcement:

```python
@router.post("/chat", response_model=ChatResponse, status_code=200)
async def post_chat(
    request: ChatRequest,
    token_claims: dict = Depends(get_current_patient_token),
    db: AsyncSession = Depends(get_db_session),
) -> ChatResponse:
    """Handle a patient chatbot message.

    Pipeline order (US-044 DoD):
        1. JWT scope enforcement (US-043)
        2. Urgency detection — BEFORE LLM call (US-044)
        3. Normal chatbot pipeline (US-043)
    """
    # -----------------------------------------------------------------------
    # Step 1: JWT scope enforcement (US-043 — unchanged)
    # -----------------------------------------------------------------------
    _enforce_encounter_scope(request.encounter_id, token_claims)

    # -----------------------------------------------------------------------
    # Step 2: Urgency detection — BEFORE LLM call (US-044)
    # -----------------------------------------------------------------------
    urgency_result = await _urgency_detector.detect(request.message)

    if urgency_result.is_urgent:
        # Retrieve patient first name from encounter record (minimum PHI)
        patient_first_name = await _get_patient_first_name(db, request.encounter_id)

        emergency_reply = await _emergency_handler.handle(
            urgency_result=urgency_result,
            encounter_id=request.encounter_id,
            patient_first_name=patient_first_name,
            db_session=db,
        )

        # Return hardcoded emergency reply immediately — no LLM call
        return ChatResponse(
            reply=emergency_reply,
            session_id=request.session_id,
            encounter_id=request.encounter_id,
            generation_type=GenerationType.LLM,  # Reuse existing enum; consider adding EMERGENCY in future
            tokens_used=None,
        )

    # -----------------------------------------------------------------------
    # Step 3–6: Normal chatbot pipeline (US-043 — unchanged)
    # -----------------------------------------------------------------------
    # ... existing US-043 implementation continues here ...
```

### 3. Add `_get_patient_first_name()` helper

Add a private helper function to the chat router that retrieves the patient's first name for the alert payload. The name is decrypted at the ORM layer (ADR-007).

```python
async def _get_patient_first_name(db: AsyncSession, encounter_id: str) -> str:
    """Retrieve patient first name (only) from the encounter record.

    The ORM decrypts the field-level encryption (ADR-007) transparently.
    Only first_name is retrieved — not full name, not MRN, not DOB.

    Returns 'Patient' as fallback if the encounter is not found, ensuring
    the alert can still be dispatched without blocking on a DB error.
    """
    from sqlalchemy import select
    from backend.app.models.patient import Patient
    from backend.app.models.encounter import Encounter

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
```

---

## Validation Checklist

```bash
# Syntax check on modified router
python -c "
import ast, pathlib
ast.parse(pathlib.Path('api-gateway/app/routers/chat.py').read_text())
print('chat.py — syntax OK after integration')
"

# Regression: urgency gate must appear BEFORE LLM call in source order
python -c "
import pathlib
src = pathlib.Path('api-gateway/app/routers/chat.py').read_text()
urgency_pos = src.find('_urgency_detector.detect')
llm_pos = src.find('GeminiFlashClient') or src.find('gemini_client') or src.find('ainvoke')
# Ensure urgency detection appears before the LLM call in source
assert urgency_pos != -1, 'UrgencyDetector not found in chat.py'
assert urgency_pos < llm_pos, (
    f'Urgency detection (pos {urgency_pos}) must appear BEFORE LLM call (pos {llm_pos})'
)
print('Urgency gate appears before LLM call ✓')
"

# Bandit static security scan on modified router
bandit api-gateway/app/routers/chat.py -ll --exit-zero

# Run existing US-043 unit tests to confirm no regression
pytest api-gateway/tests/unit/routers/test_chat_endpoint.py -v --tb=short
```

---

## Definition of Done

- [ ] `api-gateway/app/routers/chat.py` updated with `UrgencyDetector` and `EmergencyAlertHandler` imports
- [ ] `_urgency_detector` and `_emergency_handler` instantiated as module-level singletons (not per-request)
- [ ] Urgency gate runs after `_enforce_encounter_scope()` and BEFORE any `ContextAssembler` or `GeminiFlashClient` call
- [ ] `_get_patient_first_name()` helper retrieves only `first_name` — not `last_name`, `dob`, or `mrn`
- [ ] Emergency branch returns `ChatResponse` without calling any LLM
- [ ] Non-urgent messages fall through to the unchanged US-043 pipeline (no regression)
- [ ] Syntax check passes on modified `chat.py`
- [ ] Urgency-before-LLM order assertion passes
- [ ] All existing US-043 unit tests continue to pass
