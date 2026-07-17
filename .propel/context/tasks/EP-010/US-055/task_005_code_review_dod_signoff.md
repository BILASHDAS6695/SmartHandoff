---
id: TASK-005
title: "Code Review & DoD Sign-off — US-055 Chatbot Widget & Appointment Summary"
user_story: US-055
epic: EP-010
sprint: 2
layer: Process
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer + Security Engineer
upstream: [US-055/TASK-001, US-055/TASK-002, US-055/TASK-003, US-055/TASK-004]
---

# TASK-005: Code Review & DoD Sign-off — US-055 Chatbot Widget & Appointment Summary

> **Story:** US-055 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Process | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the final task for US-055. It verifies all implementation tasks (TASK-001 through TASK-004) are complete, all Definition of Done checklist items are satisfied, and a peer code review has been conducted.

A **Security Engineer review is mandatory** for this story due to two high-risk surfaces:

### 1. Patient JWT scope isolation (HIPAA / BR-020, SEC-001)

The chatbot widget sends `encounter_id` from the patient JWT claim — the patient cannot supply a different `encounter_id` to access another patient's context. Confirm:

- `ChatbotService.sendMessage()` reads `encounter_id` exclusively from `PatientAuthService.getEncounterId()` (JWT claim), never from a function parameter or local form state
- No component template or service exposes a mechanism for the patient to override `encounter_id`
- `POST /api/v1/chat` server-side handler validates that the JWT `encounter_id` matches the request body `encounter_id` (server-side responsibility — confirm with US-043 implementation)
- Browser `localStorage` and `sessionStorage` do not contain raw JWT strings beyond what `PatientAuthService` manages securely

### 2. PHI in browser logs and DOM (HIPAA / BR-020)

- No Angular component logs patient name, MRN, DOB, or diagnosis keywords via `console.log` / `console.error`
- Chat messages (patient questions and chatbot responses) are held in component memory only; they are NOT persisted to `localStorage` or `sessionStorage`
- `.ics` file content does not include patient MRN, DOB, or any PHI beyond appointment type, date, time, and provider name (which the patient already sees on screen)
- Network request headers in the `POST /api/v1/chat` and `GET /api/v1/patients/{id}/appointments` calls contain only the Authorization header — no PHI in query parameters or URL path beyond the `patient_id` UUID

---

## Pre-Review Validation Sequence

Run all checks before submitting for review:

```bash
# -----------------------------------------------------------------------
# 1. TypeScript strict mode — no errors
# -----------------------------------------------------------------------
cd frontend
npx tsc --noEmit

# -----------------------------------------------------------------------
# 2. Unit tests — all passing
# -----------------------------------------------------------------------
ng test --watch=false --code-coverage

# -----------------------------------------------------------------------
# 3. Lint — no warnings
# -----------------------------------------------------------------------
ng lint

# -----------------------------------------------------------------------
# 4. Build — production bundle compiles cleanly
# -----------------------------------------------------------------------
ng build --configuration=production
```

Expected output:
- `tsc --noEmit`: zero errors
- `ng test`: all specs pass; coverage ≥80% branch for `chatbot-widget.component.ts`, `ics-generator.ts`, `appointment-summary.component.ts`
- `ng lint`: zero errors, zero warnings
- `ng build`: bundle size for `patient-portal` lazy chunk <200 KB (gzipped)

---

## Definition of Done Checklist

### Functional

- [ ] `ChatbotWidgetComponent`: floating chat bubble (bottom-right), expand/collapse, message history, typing indicator
- [ ] Widget uses patient JWT from `PatientAuthService`; sends `encounter_id` from JWT claim
- [ ] `AppointmentSummaryComponent`: lists appointments from `GET /api/v1/patients/{id}/appointments`
- [ ] `.ics` calendar file generation: `BEGIN:VCALENDAR` format with `DTSTART:YYYYMMDDTHHMMSSZ` and `SUMMARY:SmartHandoff Follow-up Appointment`
- [ ] Urgency response: CSS override for `urgency=true` messages — full-width red banner with `<a href="tel:911">` link
- [ ] Mobile-friendly: chatbot widget uses 85% viewport height when expanded on mobile

### Quality

- [ ] Unit tests: chatbot widget scope enforcement — passing
- [ ] Unit tests: urgency response rendering — passing
- [ ] Unit tests: .ics download — passing
- [ ] Code reviewed and approved by a second Frontend Engineer
- [ ] Security Engineer sign-off on JWT scope isolation and PHI log hygiene

### Acceptance Criteria

- [ ] **AC Scenario 1**: Response displayed within 3 seconds; `POST /api/v1/chat` called with patient JWT — verified in browser DevTools
- [ ] **AC Scenario 2**: "Your Appointments" section shows appointment type, date, time (if set), and calendar-add button — verified with mock appointment data
- [ ] **AC Scenario 3**: Scope-refusal message renders without alteration; no urgency banner shown — verified via unit test
- [ ] **AC Scenario 4**: `urgency=true` response renders full-width red banner with `<a href="tel:911">` within 10 seconds — verified via unit test and manual test

---

## Security Review Checklist

| Item | Status |
|------|--------|
| `encounter_id` sourced exclusively from JWT claim in `ChatbotService` | ☐ |
| No mechanism for patient to override `encounter_id` in UI | ☐ |
| Chat messages NOT persisted to localStorage/sessionStorage | ☐ |
| No PHI in `console.log` / `console.error` in any new component | ☐ |
| `.ics` content free of MRN, DOB, or sensitive identifiers | ☐ |
| `Authorization: Bearer` header on all API calls (no PHI in URL query params) | ☐ |
| Angular strict mode — no `any` type bypasses | ☐ |

---

## Files Changed Summary

| File | Change Type | Task |
|------|-------------|------|
| `features/patient-portal/models/chat.model.ts` | New | TASK-001 |
| `features/patient-portal/services/chatbot.service.ts` | New | TASK-001 |
| `features/patient-portal/components/chatbot-widget/chatbot-widget.component.ts` | New | TASK-001 |
| `features/patient-portal/components/chatbot-widget/chatbot-widget.component.html` | New | TASK-001, TASK-003 |
| `features/patient-portal/components/chatbot-widget/chatbot-widget.component.scss` | New | TASK-001, TASK-003 |
| `features/patient-portal/models/appointment.model.ts` | New | TASK-002 |
| `features/patient-portal/services/appointments.service.ts` | New | TASK-002 |
| `features/patient-portal/utils/ics-generator.ts` | New | TASK-002 |
| `features/patient-portal/components/appointment-summary/appointment-summary.component.ts` | New | TASK-002 |
| `features/patient-portal/components/appointment-summary/appointment-summary.component.html` | New | TASK-002 |
| `features/patient-portal/components/appointment-summary/appointment-summary.component.scss` | New | TASK-002 |
| `features/patient-portal/patient-portal.module.ts` | Modified | TASK-001, TASK-002 |
| `features/patient-portal/patient-portal.component.html` | Modified | TASK-001, TASK-002 |
| `features/patient-portal/components/chatbot-widget/chatbot-widget.component.spec.ts` | New | TASK-004 |
| `features/patient-portal/utils/ics-generator.spec.ts` | New | TASK-004 |
