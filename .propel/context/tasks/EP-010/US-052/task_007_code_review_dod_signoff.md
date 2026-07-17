---
id: TASK-007
title: "Code Review & DoD Sign-Off — US-052 OTP Passwordless Authentication"
user_story: US-052
epic: EP-010
sprint: 2
layer: Review / QA
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-052/TASK-001, US-052/TASK-002, US-052/TASK-003, US-052/TASK-004, US-052/TASK-005, US-052/TASK-006]
---

# TASK-007: Code Review & DoD Sign-Off — US-052 OTP Passwordless Authentication

> **Story:** US-052 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Review / QA | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task is the gate task for US-052. It verifies that all implementation tasks
(TASK-001 through TASK-006) are complete, the Definition of Done is satisfied, and
the work is ready for pull request review and merge.

A second engineer reviews all changes before this task is marked Done.

---

## Definition of Done Checklist

### Backend endpoints

- [ ] `POST /api/v1/auth/patient/otp` — generates 6-digit OTP via `secrets.randbelow`, hashes with `bcrypt` (12 rounds), stores hash in Redis (`otp:{portal_token}`, TTL=600 s), triggers Notification Service OTP send
- [ ] `POST /api/v1/auth/patient/verify` — validates OTP hash from Redis with `bcrypt.checkpw`; issues patient JWT on success; deletes OTP key after success (one-time use)
- [ ] OTP rate limit: Redis counter `otp_attempts:{portal_token}` with TTL=3600 s; block on 6th attempt (≥5); `Retry-After` header set in 429 response
- [ ] Patient JWT: HS256, claims `sub=patient_id`, `encounter_id`, `role=patient`, `exp=now+3600`

### Security

- [ ] OTP stored as `bcrypt` hash — NOT plaintext — in Redis
- [ ] Portal token is a signed JWT (HS256) — NOT a UUID; `purpose=portal_access` claim validated
- [ ] OTP plaintext does NOT appear in any log or structured output
- [ ] `patient_id` / phone number does NOT appear in any log
- [ ] Patient JWT stored in `sessionStorage` by Angular (NOT `localStorage`) — OWASP A02
- [ ] `PORTAL_TOKEN_SECRET` and `PATIENT_JWT_SECRET` sourced from GCP Secret Manager

### Frontend

- [ ] `PatientOtpComponent` renders 6 single-character `<input>` elements with auto-advance-to-next
- [ ] Countdown timer counts 10:00 → 0:00; inputs disabled at 0:00
- [ ] Error messages: expired OTP, invalid OTP, and success paths all handled
- [ ] `aria-label` on each digit input; `role="alert"` on error messages (WCAG 2.1 AA)
- [ ] `autocomplete="one-time-code"` on each input (iOS/Android SMS autofill)

### Middleware

- [ ] `PatientEncounterScopeMiddleware` enforces that JWT `encounter_id` matches request `encounter_id` for all patient-scoped API calls
- [ ] Scope mismatch → HTTP 403; no encounter information disclosed in response body

### Tests

- [ ] All unit tests in `api-gateway/tests/auth/` pass: `pytest api-gateway/tests/auth/ -v`
- [ ] OTP expiry test asserts exact 401 message matching AC Scenario 3
- [ ] Rate limit test asserts 5th allowed; 6th blocked with `Retry-After`
- [ ] Scope enforcement test covers path param, query param, and JSON body mismatches

### Integration

- [ ] Portal token decoder (TASK-001) wired into both OTP endpoints
- [ ] `PatientEncounterScopeMiddleware` registered after `JwtValidatorMiddleware` in middleware stack
- [ ] Both auth routers (`/otp` and `/verify`) registered in FastAPI app
- [ ] `PatientOtpComponent` registered at `/portal/otp` route in Angular router

---

## Review Checklist (Reviewer)

- [ ] No secrets hardcoded in source files
- [ ] No plaintext OTP in logs, Redis values, or HTTP responses
- [ ] `bcrypt` rounds = 12 in production code (not test value of 4)
- [ ] Redis TTL values match US-052 spec: OTP key = 600 s; attempts key = 3600 s
- [ ] JWT `exp` = 3600 s (60 minutes) — not longer
- [ ] `PatientEncounterScopeMiddleware` does not bypass on missing `encounter_id` in JWT (returns 403)
- [ ] Angular component does not store JWT in `localStorage` or cookies
- [ ] All 401/403 responses use non-enumerable error messages (no encounter existence leakage)
- [ ] HIPAA audit events written for `PATIENT_AUTH_SUCCESS` only — no OTP content in audit log

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-052/TASK-001 through TASK-006 | Tasks | All implementation tasks must be complete before sign-off |
