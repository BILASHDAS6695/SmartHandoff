---
id: TASK-005
title: "Code Review & Definition of Done Sign-Off for US-066 — SendGrid Dynamic Email Templates"
user_story: US-066
epic: EP-013
sprint: 2
layer: Process
estimate: 0.5h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004]
---

# TASK-005: Code Review & Definition of Done Sign-Off for US-066 — SendGrid Dynamic Email Templates

> **Story:** US-066 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Process | **Est:** 0.5 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task is the final gate for US-066. It verifies all Definition of Done (DoD) items are complete before the story is marked `Done` and the PR is merged to the `main` branch.

It must be executed after TASK-001 through TASK-004 are complete and all unit tests are passing.

---

## Definition of Done Checklist

### Deliverables

- [ ] **6 SendGrid Dynamic Template JSON files** created in `notifications/templates/`:
  - [ ] `patient_portal_link.json`
  - [ ] `appointment_reminder.json`
  - [ ] `medication_reminder.json`
  - [ ] `care_team_escalation.json`
  - [ ] `ed_boarding_alert.json`
  - [ ] `housekeeping_notification.json`

- [ ] **Pydantic substitution schemas** in `notification-service/app/schemas/sendgrid_templates.py`:
  - [ ] `PatientPortalLinkSchema`
  - [ ] `AppointmentReminderSchema`
  - [ ] `MedicationReminderSchema`
  - [ ] `CareTeamEscalationSchema`
  - [ ] `EDBoardingAlertSchema`
  - [ ] `HousekeepingNotificationSchema`
  - [ ] `TEMPLATE_SCHEMA_REGISTRY` with all 6 entries

- [ ] **CI/CD upload script** `notifications/upload_sendgrid_templates.py` created and tested locally
- [ ] **`config/sendgrid_templates.yaml`** committed with placeholder values; script populates IDs at deploy

### PHI Minimisation

- [ ] No `last_name`, `mrn`, or `dob` fields in any patient-facing template schema
- [ ] No `{{last_name}}`, `{{mrn}}`, `{{dob}}` Handlebars tokens in any patient-facing template HTML
- [ ] Staff-facing templates use `encounter_id` only — no patient name or identifiers

### Security

- [ ] `SENDGRID_API_KEY` read exclusively from environment variable in upload script
- [ ] No API keys or secrets in any committed file
- [ ] `config/sendgrid_templates.yaml` contains no sensitive values (only template IDs)

### Quality Gates

- [ ] All JSON template files are valid JSON (verified with `python -m json.tool`)
- [ ] Handlebars tokens in HTML match field names in corresponding Pydantic schemas exactly
- [ ] All unit tests in `test_sendgrid_template_schemas.py` pass: `pytest notification-service/tests/test_sendgrid_template_schemas.py -v`
- [ ] No regressions in existing notification-service tests

### Code Review

- [ ] PR opened against `build/development` branch
- [ ] Reviewer confirmed PHI minimisation compliance
- [ ] Reviewer confirmed upload script handles both create and update code paths
- [ ] Reviewer confirmed unit test coverage for all 6 schemas
- [ ] PR approved and merged

---

## Acceptance Criteria Cross-Check

| Scenario | Verified By | Status |
|---|---|---|
| **Scenario 1**: `patient_portal_link` renders hospital logo, `{{first_name}}`, portal button, discharge date, footer | TASK-002 HTML review + Pydantic schema in TASK-001 | [ ] |
| **Scenario 2**: All 6 templates upload without errors; SendGrid Activity shows `delivered` | TASK-003 upload script + manual CI/CD dry-run | [ ] |
| **Scenario 3**: Updated template uploaded via CI/CD; previous version archived | TASK-003 update code path + Git history | [ ] |
| **Scenario 4**: `medication_reminder` shows drug name, dose, frequency, instructions, care team contact | TASK-002 HTML + TASK-001 `MedicationReminderSchema` | [ ] |

---

## Files Involved (Full US-066 Deliverable Surface)

| File | Task | Role |
|------|------|------|
| `notification-service/app/schemas/__init__.py` | TASK-001 | Schema package export |
| `notification-service/app/schemas/sendgrid_templates.py` | TASK-001 | 6 Pydantic schemas + registry |
| `notifications/templates/patient_portal_link.json` | TASK-002 | SendGrid template |
| `notifications/templates/appointment_reminder.json` | TASK-002 | SendGrid template |
| `notifications/templates/medication_reminder.json` | TASK-002 | SendGrid template |
| `notifications/templates/care_team_escalation.json` | TASK-002 | SendGrid template |
| `notifications/templates/ed_boarding_alert.json` | TASK-002 | SendGrid template |
| `notifications/templates/housekeeping_notification.json` | TASK-002 | SendGrid template |
| `notifications/upload_sendgrid_templates.py` | TASK-003 | CI/CD upload script |
| `config/sendgrid_templates.yaml` | TASK-003 | Template ID registry |
| `notification-service/tests/__init__.py` | TASK-004 | Test package |
| `notification-service/tests/test_sendgrid_template_schemas.py` | TASK-004 | Unit tests |
