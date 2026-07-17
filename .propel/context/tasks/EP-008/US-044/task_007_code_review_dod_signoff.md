---
id: TASK-007
title: "Code Review & DoD Sign-off — US-044 Urgency Detection & Emergency Alert"
user_story: US-044
epic: EP-008
sprint: 2
layer: Process
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: AI/ML Engineer + Security Engineer
upstream: [US-044/TASK-001, US-044/TASK-002, US-044/TASK-003, US-044/TASK-004, US-044/TASK-005, US-044/TASK-006]
---

# TASK-007: Code Review & DoD Sign-off — US-044 Urgency Detection & Emergency Alert

> **Story:** US-044 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Process | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-044. It verifies that TASK-001 through TASK-006 are complete, all Definition of Done items are satisfied, and a peer code review has been completed. A **Security Engineer co-review is mandatory** due to three high-risk surfaces in this story.

### 1. PHI in LLM prompts and alert payloads (HIPAA / BR-020, AIR-021)

The semantic classifier (TASK-003) passes the patient's raw message to Gemini Flash. The emergency alert handler (TASK-004) includes `patient_first_name` in the Pub/Sub payload. The following protections must be verified:

- **`semantic_classifier.py` logs** contain only `confidence`, `threshold`, `attempt`, `error_type` — never `patient_message` content.
- **`keyword_matcher.py` logs** contain only `matched_phrase` (the keyword, not the patient message) and `elapsed_ms`.
- **`emergency_handler.py` logs** contain only `encounter_id` (UUID), `detection_phase`, `pubsub_message_id` — never patient name, DOB, MRN, or message content.
- **`UrgencyAlertPayload`** published to Pub/Sub contains `patient_first_name` ONLY — not `last_name`, not `dob`, not `mrn`, not the raw patient message.
- **Gemini is not configured** with `log_to_bigquery=True` or any prompt logging feature. Confirm via `ChatVertexAI` constructor parameters in `semantic_classifier.py`.
- **`message_summary`** in `UrgencyDetectionResult` is always system-generated text (e.g., "Urgency keyword detected: 'chest pain'") — never a reproduction of the patient's raw message.

### 2. Patient safety: false negative vs false positive trade-off (US-044 AC / clinical risk)

The safe fallback strategy (TASK-003, AIR-020) returns `is_urgent=False` when Gemini classification fails. This is a deliberate clinical risk trade-off:
- A false negative (missed urgency) is handled by the keyword Phase 1 for the most critical symptoms.
- A false positive (spurious care team alert) causes alert fatigue and desensitises staff to real urgencies.

Review must confirm:
- Phase 1 keyword list covers all life-threatening symptoms listed in AC Scenario 2.
- Phase 2 fallback returns `is_urgent=False` — never `is_urgent=True` without a valid Gemini confidence score.
- The test `test_safe_fallback_never_triggers_urgency` passes (TASK-006).

### 3. Emergency reply is hardcoded, not LLM-generated (US-044 DoD)

The patient safety requirement states the emergency reply must display BEFORE any LLM response. Review must confirm:
- `EmergencyAlertHandler.handle()` returns `self._config.display_message` directly — not an LLM output.
- The `GeminiFlashClient` (US-043 pipeline) is NOT called when `is_urgent=True` (confirmed by `test_urgent_message_returns_emergency_reply_without_llm_call`).
- The integration test `mock_llm.assert_not_called()` assertion passes.

### 4. Urgency gate runs before LLM, after scope enforcement (US-044 DoD, SEC-002)

Review must confirm the pipeline order in `api-gateway/app/routers/chat.py`:
1. `_enforce_encounter_scope()` — first
2. `_urgency_detector.detect()` — second
3. LLM pipeline (US-043) — third (only if not urgent)

---

## Pre-Review Validation Sequence

Run all checks before submitting for peer review:

```bash
# -----------------------------------------------------------------------
# 1. Syntax check — all US-044 modules
# -----------------------------------------------------------------------
python -c "
import ast, pathlib
modules = [
    'backend/app/agents/patient_comm/urgency/schemas.py',
    'backend/app/agents/patient_comm/urgency/config_loader.py',
    'backend/app/agents/patient_comm/urgency/keyword_matcher.py',
    'backend/app/agents/patient_comm/urgency/semantic_classifier.py',
    'backend/app/agents/patient_comm/urgency/detector.py',
    'backend/app/agents/patient_comm/urgency/emergency_handler.py',
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
# 2. YAML config validation
# -----------------------------------------------------------------------
python -c "
import yaml, pathlib
for f in ['config/urgency_keywords.yaml', 'config/emergency_contacts.yaml']:
    data = yaml.safe_load(pathlib.Path(f).read_text())
    print(f'{f} — YAML valid: {list(data.keys())}')
"

# -----------------------------------------------------------------------
# 3. Static security scan (bandit)
# -----------------------------------------------------------------------
bandit -r backend/app/agents/patient_comm/urgency/ \
          api-gateway/app/routers/chat.py \
    -ll --exit-zero

# -----------------------------------------------------------------------
# 4. Unit tests — all pass, coverage ≥80%
# -----------------------------------------------------------------------
pytest backend/tests/unit/agents/patient_comm/urgency/ \
       api-gateway/tests/unit/routers/test_chat_urgency_integration.py \
       --cov=backend.app.agents.patient_comm.urgency \
       --cov=api_gateway.app.routers.chat \
       --cov-report=term-missing \
       --cov-fail-under=80 \
       -v --tb=short

# -----------------------------------------------------------------------
# 5. Regression — all US-043 tests still pass
# -----------------------------------------------------------------------
pytest api-gateway/tests/unit/routers/test_chat_endpoint.py \
       backend/tests/unit/agents/patient_comm/chatbot/ \
       -v --tb=short

# -----------------------------------------------------------------------
# 6. PHI field audit — patient_message never logged
# -----------------------------------------------------------------------
python -c "
import re, pathlib, sys
modules = [
    'backend/app/agents/patient_comm/urgency/keyword_matcher.py',
    'backend/app/agents/patient_comm/urgency/semantic_classifier.py',
    'backend/app/agents/patient_comm/urgency/emergency_handler.py',
    'api-gateway/app/routers/chat.py',
]
violations = []
for path in modules:
    p = pathlib.Path(path)
    if not p.exists():
        continue
    src = p.read_text()
    for field in ['patient_message', 'last_name', 'dob', 'mrn', 'phone', 'email']:
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
# 7. UrgencyAlertPayload PHI field audit
# -----------------------------------------------------------------------
python -c "
from backend.app.agents.patient_comm.urgency.schemas import UrgencyAlertPayload
fields = set(UrgencyAlertPayload.model_fields.keys())
forbidden = {'last_name', 'dob', 'mrn', 'phone', 'email', 'message', 'content', 'reply'}
found = fields & forbidden
assert not found, f'UrgencyAlertPayload contains forbidden PHI fields: {found}'
assert 'patient_first_name' in fields, 'patient_first_name required (minimum PHI)'
assert 'encounter_id' in fields
assert 'urgency_message_summary' in fields
print(f'UrgencyAlertPayload fields: {fields} — PHI bounds enforced ✓')
"

# -----------------------------------------------------------------------
# 8. Pipeline order assertion — urgency before LLM in source
# -----------------------------------------------------------------------
python -c "
import pathlib
src = pathlib.Path('api-gateway/app/routers/chat.py').read_text()
scope_pos = src.find('_enforce_encounter_scope')
urgency_pos = src.find('_urgency_detector.detect')
llm_pos = max(src.find('GeminiFlashClient'), src.find('gemini_client'), src.find('_gemini_client'))
assert scope_pos != -1 and scope_pos < urgency_pos, 'Scope enforcement must precede urgency detection'
assert urgency_pos != -1 and urgency_pos < llm_pos, 'Urgency detection must precede LLM call'
print(f'Pipeline order verified: scope({scope_pos}) < urgency({urgency_pos}) < LLM({llm_pos}) ✓')
"

# -----------------------------------------------------------------------
# 9. Hardcoded reply assertion — emergency reply is not LLM output
# -----------------------------------------------------------------------
python -c "
import pathlib
src = pathlib.Path('backend/app/agents/patient_comm/urgency/emergency_handler.py').read_text()
assert 'self._config.display_message' in src, 'Emergency reply must come from config, not LLM'
assert 'ainvoke' not in src, 'emergency_handler.py must not call any LLM (ainvoke)'
print('Emergency reply is hardcoded from config — no LLM call ✓')
"
```

---

## Peer Review Checklist

### Security Engineer Review Items

- [ ] `patient_message` confirmed absent from all logger calls in urgency modules
- [ ] `UrgencyAlertPayload` contains only: `event_type`, `encounter_id`, `patient_first_name`, `urgency_message_summary`, `timestamp`, `channel` — no raw message content
- [ ] `semantic_classifier.py` — `ChatVertexAI` constructor has no `log_to_bigquery` or prompt logging parameters
- [ ] `message_summary` in `UrgencyDetectionResult` is system-generated (not a copy of the patient message)
- [ ] Safe fallback `is_urgent=False` confirmed — never defaults to `True` on error
- [ ] Alembic migration reviewed: `urgency_flag` column type `BOOLEAN DEFAULT FALSE`, partial index on `TRUE` values only

### AI/ML Engineer Review Items

- [ ] Phase 1 keyword list covers all six AC Scenario 2 symptoms (chest pain, can't breathe, severe bleeding, unconscious, stroke, suicide) — confirmed in `urgency_keywords.yaml`
- [ ] Phase 2 confidence threshold `0.8` is the single source of truth — not duplicated across files
- [ ] `UrgencyDetector.detect()` calls `detect_urgency_keyword()` synchronously before `classify_urgency_semantic()` — Phase 2 never called when Phase 1 matches
- [ ] `asyncio.gather(return_exceptions=True)` in `EmergencyAlertHandler.handle()` prevents Pub/Sub/DB failure from blocking the emergency reply
- [ ] `_get_patient_first_name()` has a safe fallback return value (`"Patient"`) — does not raise on DB error

---

## Definition of Done — Full Story Checklist

- [ ] **TASK-001**: `config/urgency_keywords.yaml`, `config/emergency_contacts.yaml`, all Pydantic schemas created
- [ ] **TASK-002**: `UrgencyDetector` Phase 1 keyword matcher — all AC Scenario 2 keywords match; non-urgent excluded; <10ms
- [ ] **TASK-003**: `UrgencyDetector` Phase 2 Gemini semantic classification — confidence ≥0.8 threshold; retry+fallback; `UrgencyDetector` facade
- [ ] **TASK-004**: `EmergencyAlertHandler` — hardcoded reply, `CARE_TEAM_URGENCY_ALERT` published to `notification-requests`, `urgency_flag=True` persisted; Alembic migration applied
- [ ] **TASK-005**: `POST /api/v1/chat` — urgency gate after scope enforcement, before LLM; emergency short-circuit; non-urgent fallthrough confirmed
- [ ] **TASK-006**: Unit tests pass; coverage ≥80%; US-043 regression tests pass
- [ ] **TASK-007**: Pre-review validation sequence executed clean; Security Engineer sign-off received; code merged to `main`
