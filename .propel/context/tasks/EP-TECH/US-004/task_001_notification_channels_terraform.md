---
id: TASK-001
title: "Implement Notification Channels in `monitoring` Terraform Module"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: []
---

# TASK-001: Implement Notification Channels in `monitoring` Terraform Module

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

The `infra/terraform/modules/monitoring/main.tf` is currently a stub with the comment:

> *"Full implementation: EP-TECH/us_001/task_009_monitoring_alerts.md"*
> *"EP-TECH/us_003/task_001–004"*

`monitoring/outputs.tf` and `monitoring/variables.tf` exist. This task delivers the **notification channel** Terraform resources required by the DoD item: *"Alert notification channels configured (email + PagerDuty integration)"*. Notification channels are a prerequisite for TASK-002 (alert policies), which reference them via output IDs.

---

## Acceptance Criteria Addressed

| US-004 AC | Requirement |
|---|---|
| **Scenario 1** | PagerDuty/email notification fires within 2 minutes when P1 alert triggers |

---

## Implementation Steps

### 1. Add `pagerduty_integration_key` Variable to `monitoring/variables.tf`

The existing `variables.tf` already declares `oncall_email`. Add the PagerDuty service integration key variable:

```hcl
variable "pagerduty_integration_key" {
  type        = string
  description = "PagerDuty Events API v2 integration key for P1/P2 alert routing."
  sensitive   = true
}
```

### 2. Author `infra/terraform/modules/monitoring/main.tf` — Notification Channels

Replace the stub comment with two `google_monitoring_notification_channel` resources: one for email and one for PagerDuty.

```hcl
# ── Email notification channel ──────────────────────────────────────────────
resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "SmartHandoff On-Call Email (${var.environment})"
  type         = "email"

  labels = {
    email_address = var.oncall_email
  }

  user_labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

# ── PagerDuty notification channel ──────────────────────────────────────────
resource "google_monitoring_notification_channel" "pagerduty" {
  project      = var.project_id
  display_name = "SmartHandoff PagerDuty (${var.environment})"
  type         = "pagerduty"

  sensitive_labels {
    service_key = var.pagerduty_integration_key
  }

  user_labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}
```

### 3. Populate `infra/terraform/modules/monitoring/outputs.tf`

Export the channel IDs so TASK-002 alert policies can reference them without hardcoding:

```hcl
output "email_notification_channel_id" {
  description = "Resource name of the email notification channel."
  value       = google_monitoring_notification_channel.email.name
}

output "pagerduty_notification_channel_id" {
  description = "Resource name of the PagerDuty notification channel."
  value       = google_monitoring_notification_channel.pagerduty.name
  sensitive   = true
}
```

### 4. Wire `pagerduty_integration_key` in Environment `main.tf` Files

Each environment (`dev`, `staging`, `prod`) passes the PagerDuty key to the monitoring module. The value is sourced from Secret Manager rather than `terraform.tfvars` to prevent committing secrets.

Add to each `environments/<env>/main.tf` monitoring module block:

```hcl
module "monitoring" {
  source                    = "../../modules/monitoring"
  project_id                = var.project_id
  environment               = var.environment
  api_domain                = var.api_domain
  oncall_email              = var.oncall_email
  pagerduty_integration_key = data.google_secret_manager_secret_version.pagerduty_key.secret_data
}

data "google_secret_manager_secret_version" "pagerduty_key" {
  project = var.project_id
  secret  = "smarthandoff-pagerduty-integration-key-${var.environment}"
}
```

> **Security note:** The PagerDuty integration key is marked `sensitive = true` in the variable declaration and is never written to `terraform.tfvars` or state in plaintext — it is retrieved directly from Secret Manager at plan/apply time via the `data` source.

---

## Files Changed

| File | Action |
|---|---|
| `infra/terraform/modules/monitoring/main.tf` | Author (replaces stub) |
| `infra/terraform/modules/monitoring/variables.tf` | Add `pagerduty_integration_key` |
| `infra/terraform/modules/monitoring/outputs.tf` | Populate channel ID outputs |
| `infra/terraform/environments/dev/main.tf` | Wire monitoring module with PagerDuty key |
| `infra/terraform/environments/staging/main.tf` | Wire monitoring module with PagerDuty key |
| `infra/terraform/environments/prod/main.tf` | Wire monitoring module with PagerDuty key |

---

## Definition of Done

- [ ] `terraform validate` passes in `environments/dev`
- [ ] `terraform plan` shows two new `google_monitoring_notification_channel` resources
- [ ] PagerDuty key sourced from Secret Manager — not present in any `.tfvars` file
- [ ] Outputs for channel IDs exported and verified with `terraform output`
