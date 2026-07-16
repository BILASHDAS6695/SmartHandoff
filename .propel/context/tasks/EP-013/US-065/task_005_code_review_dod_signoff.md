---
id: TASK-005
title: "Code Review & DoD Sign-Off — US-065 OTP Delivery"
user_story: US-065
epic: EP-013
sprint: 2
layer: Quality / Review
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-065/TASK-001, US-065/TASK-002, US-065/TASK-003, US-065/TASK-004]
---

# TASK-005: Code Review & DoD Sign-Off — US-065 OTP Delivery

> **Story:** US-065 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Quality / Review | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This is the final gate task for US-065. It ensures all security, correctness, and DoD requirements are met before the PR is raised. The reviewer must walk through each DoD item and each acceptance criteria scenario to confirm complete coverage.

---

## Acceptance Criteria Addressed

All four scenarios from US-065 must be verifiable from code + test evidence.

---

## Review Checklist

### Security Review (SEC-003, AIR-043)

- [ ] **No plaintext OTP in Redis** — `hash_otp()` is called before any Redis `set`; raw OTP code is never stored
- [ ] **No plaintext phone in Redis keys** — `rate_limit_redis_key()` uses SHA-256 + salt; confirm `OTP_PHONE_SALT` from Secret Manager, not hardcoded
- [ ] **No plaintext portal token in Redis keys** — `otp_redis_key()` and `failures_redis_key()` use SHA-256 digest
- [ ] **Twilio credentials from Secret Manager** — `settings.TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SID` populated via environment injection; no literals in code
- [ ] **`OTP_PHONE_SALT` from Secret Manager** — `settings.OTP_PHONE_SALT` populated via environment injection
- [ ] **Rate limit checked before Twilio call** — confirmed in `auth_patient_otp.py` — `redis.incr` branch precedes `verifications.create`
- [ ] **JWT issued only on `check.status == "approved"`** — `create_access_token` call only reachable after Twilio approval

### Functional Review

- [ ] **AC Scenario 1** — `202 Accepted` returned; Redis key `otp:{digest}` present with TTL ≤ 600 s after request
- [ ] **AC Scenario 2** — 6th request returns `429` with `Retry-After: 3600`; Twilio mock `verifications.create` not called (covered by `test_rate_limit_exceeded_returns_429`)
- [ ] **AC Scenario 3** — Wrong code → `401 {"error": "invalid_otp", "attempts_remaining": 2}` on first failure; `0` on third; Redis keys deleted (covered by test suite)
- [ ] **AC Scenario 4** — Expired OTP (absent Redis key) → `401 {"error": "otp_expired", "message": "Please request a new code"}` (covered by `test_otp_expired_when_redis_key_absent`)

### Code Quality Review

- [ ] `otp_helpers.py` has no business logic — pure key derivation + crypto only (single responsibility)
- [ ] Router files import from `otp_helpers` — no inline SHA-256 or bcrypt calls in routers
- [ ] Pydantic model `OTPVerifyRequest` validates `otp_code` as 6-digit numeric string (`pattern=r"^\d{6}$"`)
- [ ] `get_twilio_client` uses `@lru_cache` — single Twilio `Client` instance per process (no reconnect on every request)
- [ ] Error responses follow the project error schema (`{"detail": {"error": "...", ...}}`)
- [ ] No N+1 Redis calls — `redis.delete(otp_key, fail_key)` in a single call (variadic delete)

### Test Coverage Review

- [ ] `pytest` runs clean: 0 failures, 0 errors
- [ ] Coverage for `otp_helpers.py` ≥ 90 %
- [ ] All four DoD test scenarios present and named clearly
- [ ] No real network calls in tests (Twilio and Redis mocked via `unittest.mock`)

### Dependency Review

- [ ] `bcrypt>=4.0.0` in `requirements.txt`
- [ ] `twilio>=9.0.0` in `requirements.txt`
- [ ] Both packages added to `pyproject.toml` / `requirements-lock.txt` if used

---

## Files to Review

| File | Review Focus |
|---|---|
| `backend/app/core/auth/otp_helpers.py` | Key derivation correctness, bcrypt rounds=10, no business logic leakage |
| `backend/app/routers/auth_patient_otp.py` | Rate limit before Twilio call, Redis TTLs, no plaintext storage |
| `backend/app/routers/auth_patient_verify.py` | Failure counter logic, expiry guard, JWT issuance, Redis cleanup |
| `backend/app/dependencies/twilio.py` | `lru_cache` singleton, credentials from settings |
| `backend/app/core/config.py` | All new settings present: `OTP_PHONE_SALT`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SID` |
| `backend/tests/unit/core/auth/test_otp_helpers.py` | Key derivation and bcrypt coverage |
| `backend/tests/unit/routers/test_auth_patient_otp.py` | Rate limit coverage |
| `backend/tests/unit/routers/test_auth_patient_verify.py` | Expiry, failures, success coverage |

---

## Definition of Done Checklist (Final US-065 DoD)

- [ ] `POST /api/v1/auth/patient/otp`: Twilio Verify `verifications.create()` called; Redis `otp:` key with TTL=600s; rate limit enforced
- [ ] OTP session stored as Twilio verification SID in Redis — NOT a plaintext code
- [ ] `POST /api/v1/auth/patient/verify`: Twilio `verification_checks.create()` called; JWT issued on `approved`
- [ ] Rate limit: `otp_rate:{SHA-256(phone + salt)}` with TTL=3600 s; max 5 requests/hour
- [ ] Failed attempts: `otp_failures:{otp_key}` counter; OTP invalidated after 3 failures
- [ ] Twilio Verify SID from Secret Manager (`settings.TWILIO_VERIFY_SID`)
- [ ] All unit tests pass (`pytest` clean run)
- [ ] Code reviewed and approved (this task)
