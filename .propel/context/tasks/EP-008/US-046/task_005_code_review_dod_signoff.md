---
id: TASK-005
title: "Code Review & DoD Sign-off — US-046 Encrypted Chatbot Transcripts"
user_story: US-046
epic: EP-008
sprint: 2
layer: Process
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer + Security Engineer
upstream: [US-046/TASK-001, US-046/TASK-002, US-046/TASK-003, US-046/TASK-004]
---

# TASK-005: Code Review & DoD Sign-off — US-046 Encrypted Chatbot Transcripts

> **Story:** US-046 | **Epic:** EP-008 | **Sprint:** 2 | **Layer:** Process | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-046. It verifies that TASK-001 through TASK-004 are complete, all Definition of Done items are satisfied, and a peer code review (with mandatory Security Engineer co-review) has been completed.

A **Security Engineer review is mandatory** for this story because it introduces three high-risk surfaces:

---

### 1. Field-level encryption correctness (HIPAA / DR-002 / US-046 AC Scenario 3)

The `message` column on `chatbot_transcript` uses `EncryptedString` (AES-256-GCM, non-deterministic, fresh nonce per write). A mis-wiring — such as using `String` or `Text` instead of `EncryptedString` — would silently store plaintext PHI in the database.

**Verify:**
- `ChatbotTranscript.message` is declared as `mapped_column(EncryptedString, ...)` — not `String` or `Text`
- `test_encrypted_string_bind_param_is_not_plaintext` passes: `process_bind_param("chest pain", ...)` returns ciphertext ≠ plaintext
- A direct `SELECT message FROM chatbot_transcript WHERE id=<id>` on the dev DB returns base64url-encoded ciphertext, not human-readable text
- `EncryptedString` is imported from `app.db.encryption` (US-007) — no new encryption implementation introduced in this story

### 2. Transcript immutability via RLS (HIPAA / DR-003 / US-008 pattern)

The `chatbot_transcript` table is clinical audit data. `app_write` must not be able to UPDATE or DELETE rows — only INSERT new rows is permitted. This mirrors the `audit_log` immutability enforced in US-008.

**Verify:**
- `ALTER TABLE chatbot_transcript ENABLE ROW LEVEL SECURITY` is present in the Alembic migration
- `CREATE POLICY transcript_immutable ... AS RESTRICTIVE FOR ALL TO app_write USING (false)` is present
- `CREATE POLICY transcript_insert_allowed ... AS PERMISSIVE FOR INSERT TO app_write WITH CHECK (true)` is present
- Manual DB check: `SET ROLE app_write; UPDATE chatbot_transcript SET urgency_flag=false WHERE id=<id>;` → error `new row violates row-level security policy`
- Downgrade function removes both policies cleanly

### 3. Patient JWT scope enforcement — no encounter enumeration (HIPAA / SEC-002 / US-046 AC Scenario 4)

`GET /api/v1/encounters/{encounter_id}/chat-transcript` must reject patient requests for other patients' encounters with a fixed 403, disclosing nothing about whether the target encounter exists.

**Verify:**
- `_enforce_scope` check (patient `encounter_id` claim vs path param) is the **first operation** in the handler — before the `db.execute()` call
- 403 response body is exactly `{"detail": "Access denied."}` — no indication of whether the encounter exists
- `test_get_transcript_patient_cross_encounter_returns_403` is present and passes (TASK-004)
- There is **no admin bypass** or query parameter that skips the encounter scope check
- Staff (`role=staff`, `role=compliance`) are not subject to the encounter restriction — RBAC check only

---

## Code Review Checklist

### Security (Security Engineer)

- [ ] `ChatbotTranscript.message` uses `EncryptedString` — not a plain `String` or `Text` column
- [ ] No plaintext PHI appears in any log statement in `transcript_service.py` or `routers/transcript.py`
- [ ] Patient scope check in `get_chat_transcript()` precedes `db.execute()` call
- [ ] 403 response body is `{"detail": "Access denied."}` — no encounter existence disclosure
- [ ] RLS migration: `transcript_immutable` policy uses `AS RESTRICTIVE` and `USING (false)`
- [ ] RLS migration: INSERT policy uses `WITH CHECK (true)` — not `USING (true)`
- [ ] `write_audit_entry()` is called for every transcript access (both patient and staff)
- [ ] `write_audit_entry()` records only `entity_type=CHATBOT_TRANSCRIPT` and `entity_id=encounter_id` — no message content

### Functional (Backend Engineer)

- [ ] `persist_exchange()` writes exactly 2 rows per call: PATIENT row + ASSISTANT row
- [ ] Patient row: `urgency_flag` and `escalated` reflect US-044/US-045 outputs
- [ ] Assistant row: `urgency_flag=False` and `escalated=False` always
- [ ] DB write failure in `persist_exchange()` is caught, logged (`transcript_persist_failed`), rolled back, and **not** re-raised
- [ ] GET endpoint returns messages in ascending timestamp order (chronological)
- [ ] Default page size is 50 messages
- [ ] `next_cursor` is `None` when fewer than 50 rows returned; non-null when more pages exist
- [ ] Malformed `?cursor=` returns HTTP 400 `{"detail": "Invalid cursor."}`
- [ ] Transcript router is registered in `api-gateway/app/main.py`
- [ ] `ChatbotTranscript` model is importable in `backend/app/models/__init__.py` (if models registry exists)

### Testing (Backend Engineer)

- [ ] `test_persist_exchange_creates_two_rows` — 2 `db.add` calls per exchange
- [ ] `test_persist_exchange_urgency_flag_set_on_patient_row` — patient row `urgency_flag=True`
- [ ] `test_persist_exchange_assistant_row_flags_always_false` — assistant row flags are both False
- [ ] `test_persist_exchange_escalated_flag_propagated` — patient row `escalated=True`
- [ ] `test_persist_exchange_db_error_does_not_raise` — fire-and-forget confirmed
- [ ] `test_encrypted_string_bind_param_is_not_plaintext` — ciphertext ≠ plaintext (AC Scenario 3)
- [ ] `test_get_transcript_patient_cross_encounter_returns_403` — 403 + correct body
- [ ] `test_get_transcript_staff_any_encounter_returns_200` — staff unrestricted
- [ ] `test_get_transcript_audit_log_written` — `write_audit_entry` called with correct args
- [ ] `test_get_transcript_next_cursor_present_when_more_pages` — cursor set when PAGE_SIZE+1 rows
- [ ] `test_get_transcript_next_cursor_none_when_last_page` — cursor None on last page
- [ ] `test_get_transcript_invalid_cursor_returns_400` — malformed cursor → 400
- [ ] Branch coverage ≥80% on `transcript_service.py` and `routers/transcript.py`

---

## Definition of Done — Final Sign-off

| DoD Item | Owner | Status |
|----------|-------|--------|
| `chatbot_transcript` ORM with `EncryptedString` on `message` | Backend Engineer | [ ] |
| Transcript persistence: every message (patient + assistant) stored after each exchange | Backend Engineer | [ ] |
| `urgency_flag` and `escalated` boolean fields on `chatbot_transcript` | Backend Engineer | [ ] |
| `GET /api/v1/encounters/{id}/chat-transcript`: staff JWT (any) + patient JWT (own) | Backend Engineer | [ ] |
| Audit log entry created for each transcript access (BR-012) | Backend Engineer | [ ] |
| Unit tests: encryption verification, urgency flag persistence, scope enforcement | Backend Engineer | [ ] |
| All tests pass (`pytest` green) | Backend Engineer | [ ] |
| Security Engineer co-review completed | Security Engineer | [ ] |
| PR approved and merged to `main` | Backend Engineer | [ ] |
