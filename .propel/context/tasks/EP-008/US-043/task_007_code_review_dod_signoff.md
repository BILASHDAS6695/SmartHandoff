---
id: TASK-007
title: "Code Review & DoD Sign-off — US-043 AI Chatbot with Scoped Discharge Q&A"
user_story: US-043
epic: EP-008
sprint: 2
layer: Process
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Security Engineer
upstream: [US-043/TASK-001, US-043/TASK-002, US-043/TASK-003, US-043/TASK-004, US-043/TASK-005, US-043/TASK-006]
---

# TASK-007: Code Review & DoD Sign-off — US-043 AI Chatbot with Scoped Discharge Q&A

> **Story:** US-043 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Process | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-043. It verifies that TASK-001 through TASK-006 are complete, all Definition of Done items are satisfied, and a peer code review (Security Engineer co-review) has been completed.

A **Security Engineer review is mandatory** for this story because it introduces three high-risk surfaces:

### 1. PHI in LLM prompts and audit logs (HIPAA / BR-020, AIR-021)

The chatbot passes discharge document content to Gemini Flash. This clinical narrative may contain PHI (patient name, diagnosis, medications). The following protections must be verified:

- **`GeminiFlashClient` logs** include only `encounter_id` (UUID), `session_id` (UUID), `tokens_used` (integer), `generation_type` — never the `messages` list or `reply` text.
- **`ChatAuditEvent`** written by the router contains only `encounter_id`, `session_id`, `message_timestamp`, `generation_type` — no `message` content, no `reply` text.
- **`ConversationHistoryService` logs** include only `encounter_id`, `session_id`, `messages` (count integer) — never the `content` field of any `ConversationMessage`.
- **`ContextAssembler`** has no logging at all — it manipulates text in memory only.
- Vertex AI is **not configured to store prompts or responses** — confirm via `ChatGoogleGenerativeAI` constructor parameters (no `log_to_bigquery=True` or equivalent).
- Confirm Cloud Logging log sink for `patient-comm-agent` service excludes field `content` (verify via `gcloud logging sinks describe`).

### 2. JWT scope enforcement on cross-patient data access (HIPAA / SEC-002 / US-043 AC Scenario 3)

The `encounter_id` scope check is the single most critical security control in this story. Failure would allow a patient to exfiltrate another patient's discharge instructions via the LLM.

- `_enforce_encounter_scope()` is called as the **first operation** in the endpoint handler — before any DB query or LLM call.
- The 403 response body is `{"detail": "Access denied."}` — no information about the target encounter (prevents existence enumeration).
- The JWT `encounter_id` claim is extracted from `token_claims` (already validated signature, not user-supplied input).
- Unit test `test_post_chat_wrong_encounter_id_returns_403` is present and passes (TASK-005).
- There is **no bypass path** (no admin override, no query parameter that skips the check).

### 3. Redis key injection prevention (SEC-012)

The Redis key pattern `conversation-history:{encounter_id}:{session_id}` is constructed from user-supplied UUIDs. If non-UUID values were accepted, an attacker could craft keys that target other namespaces (e.g., `conversation-history:token-blocklist:...`).

- `ChatRequest.validate_uuid()` rejects non-UUID values with `ValidationError` before any Redis operation.
- `_build_key()` constructs the key from pre-validated UUIDs only.
- Unit test `test_non_uuid_encounter_id_rejected` confirms Pydantic validation blocks invalid input.

---

## Pre-Review Validation Sequence

Run all checks before submitting for peer review:

```bash
# -----------------------------------------------------------------------
# 1. Syntax check — all US-043 modules
# -----------------------------------------------------------------------
python -c "
import ast, pathlib
modules = [
    'backend/app/agents/patient_comm/chatbot/schemas.py',
    'backend/app/agents/patient_comm/chatbot/token_counter.py',
    'backend/app/agents/patient_comm/chatbot/history_service.py',
    'backend/app/agents/patient_comm/chatbot/discharge_loader.py',
    'backend/app/agents/patient_comm/chatbot/context_assembler.py',
    'backend/app/agents/patient_comm/chatbot/gemini_client.py',
    'api-gateway/app/routers/chat.py',
]
for path in modules:
    p = pathlib.Path(path)
    if p.exists():
        ast.parse(p.read_text())
        print(f'{path} — syntax OK')
    else:
        print(f'MISSING: {path}')
"

# -----------------------------------------------------------------------
# 2. Static security scan (bandit)
# -----------------------------------------------------------------------
bandit -r backend/app/agents/patient_comm/ api-gateway/app/routers/chat.py \
    -ll --exit-zero

# -----------------------------------------------------------------------
# 3. Unit tests — all pass, coverage ≥80%
# -----------------------------------------------------------------------
pytest backend/tests/unit/agents/patient_comm/chatbot/ \
       api-gateway/tests/unit/routers/test_chat_endpoint.py \
       --cov=backend.app.agents.patient_comm.chatbot \
       --cov=api_gateway.app.routers.chat \
       --cov-report=term-missing \
       --cov-fail-under=80 \
       -v --tb=short

# -----------------------------------------------------------------------
# 4. PHI field audit — no PHI in logger calls
# -----------------------------------------------------------------------
python -c "
import re, pathlib, sys
phi_fields = ['mrn', 'first_name', 'last_name', 'dob', 'phone', 'email']
modules = [
    'backend/app/agents/patient_comm/chatbot/schemas.py',
    'backend/app/agents/patient_comm/chatbot/token_counter.py',
    'backend/app/agents/patient_comm/chatbot/history_service.py',
    'backend/app/agents/patient_comm/chatbot/discharge_loader.py',
    'backend/app/agents/patient_comm/chatbot/context_assembler.py',
    'backend/app/agents/patient_comm/chatbot/gemini_client.py',
    'api-gateway/app/routers/chat.py',
]
violations = []
for path in modules:
    p = pathlib.Path(path)
    if not p.exists():
        continue
    src = p.read_text()
    for field in phi_fields:
        # Check logger.* calls for PHI field names
        matches = re.findall(rf'logger\.\w+\([^)]*{field}[^)]*\)', src, re.IGNORECASE)
        if matches:
            violations.append(f'{path}: PHI field \"{field}\" in logger call: {matches}')

if violations:
    for v in violations:
        print(f'VIOLATION: {v}')
    sys.exit(1)
else:
    print('PHI field audit — all logger calls clean ✓')
"

# -----------------------------------------------------------------------
# 5. Audit event schema — confirm no message/content fields
# -----------------------------------------------------------------------
python -c "
from backend.app.agents.patient_comm.chatbot.schemas import ChatAuditEvent
fields = set(ChatAuditEvent.model_fields.keys())
phi_fields = {'message', 'content', 'reply', 'first_name', 'last_name', 'mrn'}
found = fields & phi_fields
assert not found, f'ChatAuditEvent contains PHI fields: {found}'
print(f'ChatAuditEvent fields: {fields} — no PHI ✓')
"

# -----------------------------------------------------------------------
# 6. Scope enforcement is first call in endpoint
# -----------------------------------------------------------------------
python -c "
import pathlib
src = pathlib.Path('api-gateway/app/routers/chat.py').read_text()
# _enforce_encounter_scope must appear before load_discharge_summary
esc_pos = src.index('_enforce_encounter_scope')
load_pos = src.index('load_discharge_summary')
assert esc_pos < load_pos, (
    'SECURITY: _enforce_encounter_scope must be called before load_discharge_summary'
)
print('Scope enforcement order verified — before DB call ✓')
"

# -----------------------------------------------------------------------
# 7. Redis key pattern validation
# -----------------------------------------------------------------------
python -c "
from backend.app.agents.patient_comm.chatbot.history_service import _build_key
import uuid
enc = str(uuid.uuid4())
ses = str(uuid.uuid4())
key = _build_key(enc, ses)
assert key.startswith('conversation-history:'), f'Unexpected key prefix: {key}'
parts = key.split(':')
assert len(parts) == 3, f'Key must have 3 parts: {key}'
assert parts[1] == enc and parts[2] == ses
print(f'Redis key pattern: {key} ✓')
"
```

---

## Code Review Checklist

### Security (mandatory — Security Engineer sign-off required)

- [ ] `_enforce_encounter_scope()` is the **first operation** in `post_chat()` — before any DB or LLM call
- [ ] 403 response body is `{"detail": "Access denied."}` — no encounter information disclosed
- [ ] `ChatRequest.validate_uuid()` rejects non-UUID `encounter_id` and `session_id` values
- [ ] No PHI field names (`mrn`, `first_name`, `last_name`, `dob`, `phone`, `email`, `message`, `content`) appear in `logger.*` calls
- [ ] `ChatAuditEvent` schema contains no `message` or `reply` fields
- [ ] `GCP_PROJECT_ID` and `REDIS_URL` read from env vars — no hardcoded values
- [ ] Vertex AI constructor has no prompt-logging configuration

### Functional

- [ ] System prompt contains "You ONLY answer questions based on the discharge instructions" (AC Scenario 2)
- [ ] System prompt contains "I don't know" instruction (AC Scenario 2)
- [ ] `GeminiFlashClient` timeout is 3 seconds (`_GEMINI_TIMEOUT_SECONDS = 3.0`)
- [ ] Timeout returns `GenerationType.FALLBACK` — no exception propagated to endpoint
- [ ] FIFO pruning drops oldest messages; `MAX_HISTORY_MESSAGES = 10` enforced
- [ ] Redis TTL is 86 400 seconds (24 hours)
- [ ] `chat_router` registered in `api-gateway/app/main.py`

### Test Coverage

- [ ] `test_post_chat_wrong_encounter_id_returns_403` — passes
- [ ] `test_post_chat_correct_encounter_id_returns_200` — passes
- [ ] `test_post_chat_timeout_returns_fallback_not_500` — passes
- [ ] `test_fifo_pruning_drops_oldest_messages` — passes
- [ ] `test_system_prompt_contains_scope_restriction` — passes
- [ ] `test_gemini_timeout_returns_fallback_not_exception` — passes
- [ ] Coverage ≥80% branch (`--cov-fail-under=80`)

### Performance

- [ ] Load test (`task_006`) executed against staging — p95 < 3 000 ms confirmed
- [ ] Load test HTML report uploaded to Cloud Storage and linked in PR

---

## US-043 Definition of Done Sign-off

| DoD Item | Task | Status |
|----------|------|--------|
| `POST /api/v1/chat` endpoint with `{message, encounter_id, session_id}` | TASK-004 | [ ] |
| JWT scope enforcement: `encounter_id` claim matches request body | TASK-004 | [ ] |
| Context assembly: system (2K) + discharge (4K) + history (2K) | TASK-003 | [ ] |
| Vertex AI Gemini Flash call with 3-second timeout and structured output | TASK-003 | [ ] |
| Graceful fallback message on timeout (not an exception) | TASK-003 | [ ] |
| Conversation history in Redis: `conversation-history:{enc}:{ses}` (TTL=24h) | TASK-002 | [ ] |
| Performance test: p95 <3s at 100 concurrent users | TASK-006 | [ ] |
| Unit tests: scope enforcement, context assembly, FIFO pruning, timeout fallback | TASK-005 | [ ] |
| Code reviewed and approved (peer + Security Engineer) | TASK-007 | [ ] |
