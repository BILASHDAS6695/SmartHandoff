---
id: TASK-002
title: "Create `notifications/templates/` — 6 SendGrid Dynamic Template HTML/JSON Files"
user_story: US-066
epic: EP-013
sprint: 2
layer: Backend / Templates
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001]
---

# TASK-002: Create `notifications/templates/` — 6 SendGrid Dynamic Template HTML/JSON Files

> **Story:** US-066 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Templates | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-066 DoD specifies:

> *"6 SendGrid Dynamic Template JSON files: `patient_portal_link`, `appointment_reminder`, `medication_reminder`, `care_team_escalation`, `ed_boarding_alert`, `housekeeping_notification`"*
> *"Templates stored in `notifications/templates/` in source control"*

Each SendGrid Dynamic Template is stored as a JSON envelope matching the [SendGrid Dynamic Templates API v3](https://docs.sendgrid.com/api-reference/transactional-templates) payload structure. The JSON contains:
- `name` — template name (matches `TEMPLATE_SCHEMA_REGISTRY` key)
- `versions[0].subject` — email subject line (may use Handlebars)
- `versions[0].html_content` — full responsive HTML body using Handlebars `{{variable}}` tokens
- `versions[0].plain_content` — plain-text fallback

**Handlebars tokens must exactly match field names defined in TASK-001 Pydantic schemas.**

Design decisions:

| Decision | Rationale |
|----------|-----------|
| JSON envelope per template | SendGrid API v3 `POST /v3/templates` accepts this payload directly; upload script can POST as-is |
| Responsive HTML using inline CSS | Email clients (Outlook, Gmail) do not support external stylesheets; inline CSS required for consistent rendering |
| Hospital logo via CDN URL `{{hospital_logo_url}}` | Avoids base64 bloating JSON; CDN-hosted per US-066 Technical Notes |
| Plain-text fallback required | WCAG 2.1 + email deliverability best practice; some mail clients are text-only |
| `{{#if discharge_date}}` conditional block | `discharge_date` is optional in `PatientPortalLinkSchema`; Handlebars conditional prevents blank line in email |
| Staff templates: no patient greeting | PHI minimisation — staff templates do not reference patient name |
| `active: 1` on `versions[0]` | SendGrid only renders the active version; new deploys activate the uploaded version |

Design refs: US-066 Technical Notes, TASK-001 schemas, ADR-007 (PHI minimisation).

---

## Acceptance Criteria Addressed

| US-066 AC | Requirement |
|---|---|
| **Scenario 1** | `patient_portal_link.json` template renders hospital logo, `{{first_name}}` greeting, portal link button, discharge date, footer |
| **Scenario 2** | All 6 template JSON files are syntactically valid and upload without errors |
| **Scenario 3** | Templates tracked in Git; CI/CD uploads via `upload_sendgrid_templates.py` (TASK-003) |
| **Scenario 4** | `medication_reminder.json` renders `{{drug_name}}`, `{{dose}}`, `{{frequency}}`, `{{instructions}}`, care team contact section |

---

## Implementation Steps

### 1. Scaffold directory

```bash
mkdir -p notifications/templates
```

### 2. Template file structure (all 6 files)

Each file follows this JSON envelope:

```json
{
  "name": "<template_name>",
  "generation": "dynamic",
  "versions": [
    {
      "name": "v1",
      "subject": "<subject line>",
      "html_content": "<full HTML string>",
      "plain_content": "<plain text fallback>",
      "active": 1
    }
  ]
}
```

---

### 3. Create `notifications/templates/patient_portal_link.json`

```json
{
  "name": "patient_portal_link",
  "generation": "dynamic",
  "versions": [
    {
      "name": "v1",
      "subject": "Your SmartHandoff Patient Portal is Ready",
      "html_content": "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Your Patient Portal</title></head><body style=\"margin:0;padding:0;background-color:#f4f7fb;font-family:Arial,sans-serif;\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td align=\"center\" style=\"padding:32px 16px;\"><table width=\"600\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);\"><tr><td align=\"center\" style=\"background:#1a5276;padding:24px;\"><img src=\"{{hospital_logo_url}}\" alt=\"{{hospital_name}}\" width=\"160\" style=\"display:block;\"></td></tr><tr><td style=\"padding:32px 40px;\"><h1 style=\"color:#1a5276;font-size:22px;margin-top:0;\">Hello, {{first_name}}</h1><p style=\"color:#444;font-size:16px;line-height:1.6;\">Your discharge is being prepared and your patient portal is ready. Use the button below to access your personalised care instructions, medications, and follow-up appointments.</p>{{#if discharge_date}}<p style=\"color:#444;font-size:16px;\"><strong>Estimated discharge date:</strong> {{discharge_date}}</p>{{/if}}<div style=\"text-align:center;margin:32px 0;\"><a href=\"{{portal_link}}\" style=\"background:#1a5276;color:#ffffff;text-decoration:none;padding:14px 36px;border-radius:6px;font-size:16px;font-weight:bold;display:inline-block;\">Access My Portal</a></div><p style=\"color:#888;font-size:13px;\">This link expires in 72 hours. If you have trouble accessing your portal, please contact us.</p></td></tr><tr><td style=\"background:#f4f7fb;padding:20px 40px;border-top:1px solid #e0e0e0;\"><p style=\"color:#888;font-size:12px;margin:0;\">{{hospital_name}} | {{hospital_phone}}<br>If you did not expect this email, please disregard or contact us immediately.</p></td></tr></table></td></tr></table></body></html>",
      "plain_content": "Hello {{first_name}},\n\nYour patient portal is ready. Please visit the following link to access your care instructions:\n\n{{portal_link}}\n\n{{#if discharge_date}}Estimated discharge date: {{discharge_date}}\n\n{{/if}}This link expires in 72 hours.\n\n{{hospital_name}}\n{{hospital_phone}}",
      "active": 1
    }
  ]
}
```

---

### 4. Create `notifications/templates/appointment_reminder.json`

```json
{
  "name": "appointment_reminder",
  "generation": "dynamic",
  "versions": [
    {
      "name": "v1",
      "subject": "Reminder: Your Upcoming Appointment",
      "html_content": "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Appointment Reminder</title></head><body style=\"margin:0;padding:0;background-color:#f4f7fb;font-family:Arial,sans-serif;\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td align=\"center\" style=\"padding:32px 16px;\"><table width=\"600\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);\"><tr><td align=\"center\" style=\"background:#1a5276;padding:24px;\"><img src=\"{{hospital_logo_url}}\" alt=\"Hospital Logo\" width=\"160\" style=\"display:block;\"></td></tr><tr><td style=\"padding:32px 40px;\"><h1 style=\"color:#1a5276;font-size:22px;margin-top:0;\">Hello, {{first_name}}</h1><p style=\"color:#444;font-size:16px;line-height:1.6;\">This is a reminder about your upcoming appointment.</p><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f4f7fb;border-radius:6px;padding:20px;margin:16px 0;\"><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Date &amp; Time:</strong><span style=\"color:#444;margin-left:8px;\">{{appointment_date}}</span></td></tr><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Provider:</strong><span style=\"color:#444;margin-left:8px;\">{{provider_name}}</span></td></tr><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Clinic:</strong><span style=\"color:#444;margin-left:8px;\">{{clinic_name}}</span></td></tr><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Address:</strong><span style=\"color:#444;margin-left:8px;\">{{clinic_address}}</span></td></tr><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Phone:</strong><span style=\"color:#444;margin-left:8px;\">{{clinic_phone}}</span></td></tr></table><p style=\"color:#444;font-size:14px;\">Please arrive 15 minutes before your appointment. If you need to reschedule, contact the clinic directly.</p></td></tr><tr><td style=\"background:#f4f7fb;padding:20px 40px;border-top:1px solid #e0e0e0;\"><p style=\"color:#888;font-size:12px;margin:0;\">You are receiving this because you are a registered patient. To opt out of reminders, contact your care team.</p></td></tr></table></td></tr></table></body></html>",
      "plain_content": "Hello {{first_name}},\n\nThis is a reminder about your upcoming appointment.\n\nDate & Time: {{appointment_date}}\nProvider: {{provider_name}}\nClinic: {{clinic_name}}\nAddress: {{clinic_address}}\nPhone: {{clinic_phone}}\n\nPlease arrive 15 minutes early. To reschedule, contact the clinic directly.",
      "active": 1
    }
  ]
}
```

---

### 5. Create `notifications/templates/medication_reminder.json`

```json
{
  "name": "medication_reminder",
  "generation": "dynamic",
  "versions": [
    {
      "name": "v1",
      "subject": "Your Medication Reminder",
      "html_content": "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Medication Reminder</title></head><body style=\"margin:0;padding:0;background-color:#f4f7fb;font-family:Arial,sans-serif;\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td align=\"center\" style=\"padding:32px 16px;\"><table width=\"600\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);\"><tr><td align=\"center\" style=\"background:#1a5276;padding:24px;\"><img src=\"{{hospital_logo_url}}\" alt=\"Hospital Logo\" width=\"160\" style=\"display:block;\"></td></tr><tr><td style=\"padding:32px 40px;\"><h1 style=\"color:#1a5276;font-size:22px;margin-top:0;\">Hello, {{first_name}}</h1><p style=\"color:#444;font-size:16px;line-height:1.6;\">This is a reminder about your prescribed medication.</p><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#f4f7fb;border-radius:6px;padding:20px;margin:16px 0;\"><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Medication:</strong><span style=\"color:#444;margin-left:8px;\">{{drug_name}}</span></td></tr><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Dose:</strong><span style=\"color:#444;margin-left:8px;\">{{dose}}</span></td></tr><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Frequency:</strong><span style=\"color:#444;margin-left:8px;\">{{frequency}}</span></td></tr>{{#if instructions}}<tr><td style=\"padding:8px 16px;\"><strong style=\"color:#1a5276;\">Special Instructions:</strong><span style=\"color:#444;margin-left:8px;\">{{instructions}}</span></td></tr>{{/if}}</table><div style=\"background:#e8f4fd;border-left:4px solid #1a5276;padding:16px 20px;border-radius:4px;margin-top:16px;\"><p style=\"color:#1a5276;font-size:14px;margin:0;\"><strong>Questions about your medication?</strong><br>Contact your care team at <a href=\"tel:{{care_team_phone}}\" style=\"color:#1a5276;\">{{care_team_phone}}</a>.</p></div></td></tr><tr><td style=\"background:#f4f7fb;padding:20px 40px;border-top:1px solid #e0e0e0;\"><p style=\"color:#888;font-size:12px;margin:0;\">Do not adjust your medication without consulting your care team. To opt out of reminders, contact your care team.</p></td></tr></table></td></tr></table></body></html>",
      "plain_content": "Hello {{first_name}},\n\nThis is a reminder about your prescribed medication.\n\nMedication: {{drug_name}}\nDose: {{dose}}\nFrequency: {{frequency}}\n{{#if instructions}}Special Instructions: {{instructions}}\n{{/if}}\nContact your care team if you have questions: {{care_team_phone}}\n\nDo not adjust your medication without consulting your care team.",
      "active": 1
    }
  ]
}
```

---

### 6. Create `notifications/templates/care_team_escalation.json`

```json
{
  "name": "care_team_escalation",
  "generation": "dynamic",
  "versions": [
    {
      "name": "v1",
      "subject": "[{{urgency_level}}] Care Team Escalation — Encounter {{encounter_id}}",
      "html_content": "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Care Team Escalation</title></head><body style=\"margin:0;padding:0;background-color:#f4f7fb;font-family:Arial,sans-serif;\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td align=\"center\" style=\"padding:32px 16px;\"><table width=\"600\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);\"><tr><td style=\"background:#c0392b;padding:20px 40px;\"><h1 style=\"color:#ffffff;font-size:20px;margin:0;\">&#9888; {{urgency_level}} Escalation Alert</h1></td></tr><tr><td style=\"padding:32px 40px;\"><p style=\"color:#444;font-size:15px;line-height:1.6;\"><strong>Encounter ID:</strong> {{encounter_id}}</p><p style=\"color:#444;font-size:15px;\"><strong>Unit:</strong> {{unit_name}}</p><p style=\"color:#444;font-size:15px;\"><strong>Escalated at:</strong> {{escalated_at}}</p><div style=\"background:#fdf2f2;border-left:4px solid #c0392b;padding:16px 20px;border-radius:4px;margin:16px 0;\"><p style=\"color:#c0392b;font-size:14px;margin:0;\"><strong>Reason for Escalation:</strong><br>{{escalation_reason}}</p></div><div style=\"text-align:center;margin:24px 0;\"><a href=\"{{dashboard_link}}\" style=\"background:#1a5276;color:#ffffff;text-decoration:none;padding:12px 32px;border-radius:6px;font-size:15px;font-weight:bold;display:inline-block;\">View in SmartHandoff Dashboard</a></div></td></tr><tr><td style=\"background:#f4f7fb;padding:16px 40px;border-top:1px solid #e0e0e0;\"><p style=\"color:#888;font-size:12px;margin:0;\">This is an automated alert from SmartHandoff. Please do not reply to this email.</p></td></tr></table></td></tr></table></body></html>",
      "plain_content": "CARE TEAM ESCALATION — {{urgency_level}}\n\nEncounter ID: {{encounter_id}}\nUnit: {{unit_name}}\nEscalated at: {{escalated_at}}\n\nReason: {{escalation_reason}}\n\nView in dashboard: {{dashboard_link}}\n\nThis is an automated alert from SmartHandoff.",
      "active": 1
    }
  ]
}
```

---

### 7. Create `notifications/templates/ed_boarding_alert.json`

```json
{
  "name": "ed_boarding_alert",
  "generation": "dynamic",
  "versions": [
    {
      "name": "v1",
      "subject": "[ED Boarding Alert] Encounter {{encounter_id}} — {{boarding_hours}}h Boarding",
      "html_content": "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>ED Boarding Alert</title></head><body style=\"margin:0;padding:0;background-color:#f4f7fb;font-family:Arial,sans-serif;\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td align=\"center\" style=\"padding:32px 16px;\"><table width=\"600\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);\"><tr><td style=\"background:#e67e22;padding:20px 40px;\"><h1 style=\"color:#ffffff;font-size:20px;margin:0;\">&#128700; ED Boarding Alert</h1></td></tr><tr><td style=\"padding:32px 40px;\"><p style=\"color:#444;font-size:15px;\"><strong>Encounter ID:</strong> {{encounter_id}}</p><p style=\"color:#444;font-size:15px;\"><strong>Unit:</strong> {{unit_name}}</p><p style=\"color:#444;font-size:15px;\"><strong>Alert triggered at:</strong> {{alert_triggered_at}}</p><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#fff8e1;border-radius:6px;padding:16px;margin:16px 0;\"><tr><td style=\"padding:8px 16px;\"><strong style=\"color:#e67e22;\">Boarding Duration:</strong><span style=\"color:#444;margin-left:8px;\">{{boarding_hours}} hours</span></td></tr>{{#if predicted_discharge_hours}}<tr><td style=\"padding:8px 16px;\"><strong style=\"color:#e67e22;\">Predicted Discharge In:</strong><span style=\"color:#444;margin-left:8px;\">{{predicted_discharge_hours}} hours</span></td></tr>{{/if}}</table><div style=\"text-align:center;margin:24px 0;\"><a href=\"{{dashboard_link}}\" style=\"background:#1a5276;color:#ffffff;text-decoration:none;padding:12px 32px;border-radius:6px;font-size:15px;font-weight:bold;display:inline-block;\">View Bed Board</a></div></td></tr><tr><td style=\"background:#f4f7fb;padding:16px 40px;border-top:1px solid #e0e0e0;\"><p style=\"color:#888;font-size:12px;margin:0;\">Automated alert from SmartHandoff Bed Management Agent. Do not reply.</p></td></tr></table></td></tr></table></body></html>",
      "plain_content": "ED BOARDING ALERT\n\nEncounter ID: {{encounter_id}}\nUnit: {{unit_name}}\nAlert triggered at: {{alert_triggered_at}}\nBoarding Duration: {{boarding_hours}} hours\n{{#if predicted_discharge_hours}}Predicted Discharge In: {{predicted_discharge_hours}} hours\n{{/if}}\nView Bed Board: {{dashboard_link}}\n\nAutomated alert from SmartHandoff Bed Management Agent.",
      "active": 1
    }
  ]
}
```

---

### 8. Create `notifications/templates/housekeeping_notification.json`

```json
{
  "name": "housekeeping_notification",
  "generation": "dynamic",
  "versions": [
    {
      "name": "v1",
      "subject": "[{{priority}}] Bed Ready for Cleaning — {{bed_identifier}}",
      "html_content": "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Housekeeping Notification</title></head><body style=\"margin:0;padding:0;background-color:#f4f7fb;font-family:Arial,sans-serif;\"><table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\"><tr><td align=\"center\" style=\"padding:32px 16px;\"><table width=\"600\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);\"><tr><td style=\"background:#1a7a4a;padding:20px 40px;\"><h1 style=\"color:#ffffff;font-size:20px;margin:0;\">&#129529; Bed Ready for Terminal Cleaning</h1></td></tr><tr><td style=\"padding:32px 40px;\"><p style=\"color:#444;font-size:15px;\"><strong>Encounter ID:</strong> {{encounter_id}}</p><p style=\"color:#444;font-size:15px;\"><strong>Bed:</strong> {{bed_identifier}}</p><p style=\"color:#444;font-size:15px;\"><strong>Unit:</strong> {{unit_name}}</p><p style=\"color:#444;font-size:15px;\"><strong>Discharge confirmed at:</strong> {{discharge_confirmed_at}}</p><div style=\"background:{{#if (eq priority 'URGENT')}}#fdf2f2{{else}}#f0fdf4{{/if}};border-left:4px solid {{#if (eq priority 'URGENT')}}#c0392b{{else}}#1a7a4a{{/if}};padding:16px 20px;border-radius:4px;margin:16px 0;\"><p style=\"font-size:16px;font-weight:bold;margin:0;color:{{#if (eq priority 'URGENT')}}#c0392b{{else}}#1a7a4a{{/if}};\">Priority: {{priority}}</p></div></td></tr><tr><td style=\"background:#f4f7fb;padding:16px 40px;border-top:1px solid #e0e0e0;\"><p style=\"color:#888;font-size:12px;margin:0;\">Automated notification from SmartHandoff. Do not reply.</p></td></tr></table></td></tr></table></body></html>",
      "plain_content": "BED READY FOR TERMINAL CLEANING\n\nEncounter ID: {{encounter_id}}\nBed: {{bed_identifier}}\nUnit: {{unit_name}}\nDischarge confirmed at: {{discharge_confirmed_at}}\nPriority: {{priority}}\n\nAutomated notification from SmartHandoff.",
      "active": 1
    }
  ]
}
```

---

## Validation Checklist

- [ ] All 6 JSON files parse as valid JSON (run `python -m json.tool <file>`)
- [ ] Handlebars tokens in each JSON file match field names in the corresponding TASK-001 Pydantic schema
- [ ] `{{first_name}}` used in patient-facing templates (portal link, appointment, medication)
- [ ] No `{{last_name}}`, `{{mrn}}`, `{{dob}}` tokens appear in any template file
- [ ] Staff templates use `{{encounter_id}}` (not patient name)
- [ ] `{{#if discharge_date}}` conditional in `patient_portal_link.json` is correctly closed with `{{/if}}`
- [ ] `{{#if instructions}}` conditional in `medication_reminder.json` is correctly closed with `{{/if}}`
- [ ] `{{#if predicted_discharge_hours}}` conditional in `ed_boarding_alert.json` is correctly closed
- [ ] All 6 files have `"active": 1` in `versions[0]`
- [ ] `"generation": "dynamic"` is set in all 6 files

---

## Files Created

| File | Template Type |
|------|--------------|
| `notifications/templates/patient_portal_link.json` | Patient-facing |
| `notifications/templates/appointment_reminder.json` | Patient-facing |
| `notifications/templates/medication_reminder.json` | Patient-facing |
| `notifications/templates/care_team_escalation.json` | Staff-facing |
| `notifications/templates/ed_boarding_alert.json` | Staff-facing |
| `notifications/templates/housekeeping_notification.json` | Staff-facing |

---

## Dependencies

| Dependency | Direction | Notes |
|---|---|---|
| TASK-001 | Upstream | Handlebars tokens must match Pydantic field names |
| TASK-003 | Downstream | Upload script reads these JSON files to POST to SendGrid API |
