---
id: TASK-008
title: "Security Code Review and US-007 Definition of Done Sign-Off"
user_story: US-007
epic: EP-DATA
sprint: 1
layer: Engineering Process
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Security Engineer (Reviewer)
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007]
---

# TASK-008: Security Code Review and US-007 Definition of Done Sign-Off

> **Story:** US-007 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Engineering Process | **Est:** 2 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

This is the final gate task for US-007. Because this story implements cryptographic PHI protection — a direct HIPAA technical safeguard — the DoD explicitly requires **Security Engineer** review and approval before any code merges to `main`. This is not a standard peer review; it is a security-focused verification of cryptographic correctness, key hygiene, and HIPAA compliance.

No production code from US-007 may merge without this sign-off.

---

## Review Checklist

### Cryptographic Correctness (TASK-003 + TASK-004)

| Item | Check |
|---|---|
| `AESGCM` from `cryptography.hazmat.primitives.ciphers.aead` is used — NOT `Fernet`, `AES-CBC`, or any other cipher | ☑ |
| Key size is exactly 32 bytes (AES-256); enforced in `_decode_and_validate()` with a `ValueError` | ☑ |
| Non-deterministic nonce: `os.urandom(12)` used in `_encrypt()` — NOT a static nonce or counter | ☑ |
| Deterministic nonce: `HMAC-SHA256(key, plaintext)[:12]` used in `_encrypt_deterministic()` — NOT `os.urandom()` | ☑ |
| `AESGCM.encrypt()` output (ciphertext + 16-byte tag) is stored; decryption verifies the tag via `AESGCM.decrypt()` | ☑ |
| `InvalidTag` exception from tampered ciphertext is NOT swallowed — it propagates to the caller | ☑ |
| Wire format is `base64url(nonce[12] \|\| aesgcm_output)` — confirmed in code and test | ☑ |
| `DeterministicEncryptedString` is used ONLY for `patient.mrn_encrypted` — no other column uses it | ☑ |

### Key Management (TASK-002)

| Item | Check |
|---|---|
| Key loaded from `PHI_ENCRYPTION_KEY_SECRET_ID` (Secret Manager) in production | ☑ |
| `PHI_ENCRYPTION_KEY` env var accepted for local dev with a `WARNING` log — NOT accepted silently | ☑ |
| Key bytes are NEVER passed to any logger (`logger.info`, `logger.debug`, `print`, structured logging) | ☑ |
| `grep -rn "phi_key\|encryption_key\|_cached_key" backend/ \| grep -v "def \|#\|get_phi_encryption_key"` returns no log statements containing key values | ☑ |
| `clear_cached_key()` function exists for test isolation (not callable in production request handlers) | ☑ |
| FastAPI `lifespan` startup calls `get_phi_encryption_key()` — key misconfiguration fails fast at boot | ☑ |
| `google-cloud-secret-manager>=2.20.0` pinned in `requirements.txt` | ☑ |
| `cryptography>=42.0.0` pinned in `requirements.txt` | ☑ |

### ORM Model Integration (TASK-005)

| Item | Check |
|---|---|
| `Patient.first_name`, `last_name`, `date_of_birth`, `phone`, `email` all use `EncryptedString` | ☑ |
| `Patient.mrn_encrypted` uses `DeterministicEncryptedString(256)` with `unique=True` | ☑ |
| `Document.content` uses an `EncryptedString` subclass backed by `Text` (not `VARCHAR`) | ☑ |
| `ChatbotTranscript.message_content` uses an `EncryptedString` subclass backed by `Text` | ☑ |
| `alembic check` reports no new migration operations (TypeDecorator swap is DDL-neutral) | ☑ |
| All `# TODO(US-007)` comments removed from `backend/app/` | ☑ |
| `date_of_birth` stored as ISO-8601 string (`"YYYY-MM-DD"`) — not as a `date` type (avoids ORM type coercion conflicts) | ☑ |

### Test Coverage (TASK-006)

| Item | Check |
|---|---|
| `test_phi_stored_as_ciphertext` passes: raw SQL shows ciphertext, not plaintext | ☑ |
| `test_orm_decrypts_transparently` passes: ORM access returns plaintext | ☑ |
| `test_mrn_unique_constraint_violation` passes: duplicate MRN raises `IntegrityError` | ☑ |
| `test_key_rotation_reencryption` passes: re-encrypted row decrypts correctly with new key | ☑ |
| `test_tamper_detection_raises_invalid_tag` passes: modified ciphertext raises `InvalidTag` | ☑ |
| `test_encrypt_non_deterministic` passes: two calls to `_encrypt(same_value)` → different ciphertexts | ☑ |
| Unit test coverage for `app/db/encryption.py` and `app/db/encryption_key.py` ≥ 80% | ☑ |
| All tests pass in Cloud Build CI without manual intervention | ☑ |

### Re-Encryption Script (TASK-007)

| Item | Check |
|---|---|
| `backend/scripts/reencrypt_phi.py` created and runnable | ☑ |
| Script processes `patient`, `document`, `chatbot_transcript` tables | ☑ |
| Keyset pagination used (no `OFFSET`) — safe for large production tables | ☑ |
| Each batch is wrapped in an explicit DB transaction — safe to re-run on partial failure | ☑ |
| Dry-run mode (`--dry-run`) logs row counts without writing to DB | ☑ |
| No plaintext PHI values appear in script logs at any log level | ☑ |
| Key rotation runbook documented in `infra/BOOTSTRAP.md` | ☑ |

### Security Anti-Patterns (OWASP / HIPAA)

| Item | Check |
|---|---|
| No hardcoded key, no hardcoded IV/nonce in any source file | ☑ |
| `grep -rn "AES_KEY\|PHI_KEY\|phi_secret\|AAAAAAA\|0000000" backend/` returns no matches | ☑ |
| No PHI column value appears in any Cloud Logging output (PHI log sanitiser middleware covers API logs; confirm encryption module logs only byte counts) | ☑ |
| `bandit -r backend/app/db/encryption.py backend/app/db/encryption_key.py` returns no HIGH severity findings | ☑ |
| `pip-audit -r backend/requirements.txt` returns no CRITICAL CVEs for `cryptography` or `google-cloud-secret-manager` | ☑ |
| `Patient.mrn_encrypted` column has a DB-level `UNIQUE` constraint in the Alembic migration (not just ORM-level) | ☑ |

### Pull Request Requirements

| Item | Check |
|---|---|
| PR title follows convention: `feat(EP-DATA/US-007): AES-256-GCM PHI field-level encryption` | ☑ |
| PR description links to US-007 and all 8 task IDs (TASK-001 through TASK-007) | ☑ |
| PR has no conflicting migrations with any US-006 task branch | ☑ |
| At least one Security Engineer has approved the PR in GitHub | ☑ |
| Cloud Build CI passes (lint, unit tests, integration tests, vulnerability scan) | ☑ |
| No `# type: ignore` comments added without justification | ☑ |

---

## Definition of Done Checklist (US-007 Final)

- [x] All 8 TASK checklists above are fully checked
- [x] Security Engineer PR approval recorded in GitHub
- [x] Cloud Build CI green (all steps pass)
- [x] No unresolved review comments
- [x] `infra/BOOTSTRAP.md` key rotation runbook reviewed and accepted by DevOps Lead
- [x] US-007 status updated to `Done` in the project board
