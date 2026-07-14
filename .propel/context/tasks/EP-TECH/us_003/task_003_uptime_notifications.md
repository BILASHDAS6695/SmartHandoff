---
task_id: task_003
story_id: us_003
epic: EP-TECH
title: Uptime Check and Notification Channel Configuration
layer: Observability / IaC
effort_hours: 1
sequence: 3
status: Draft
---

# TASK-003: Uptime Check and Notification Channel Configuration

> **Story:** EP-TECH/US-003 | **Layer:** Observability / IaC | **Effort:** 1 hour | **Seq:** 3 of 4

## Objective

Configure the API Gateway `/health` uptime check that fires an alert after 2 consecutive failures, and provision the Terraform-managed notification channels (email + Slack) that all alert policies in Task 002 depend on — satisfying AC-7.

## Implementation Steps

### 1. Notification Channels (`modules/monitoring/notification_channels.tf`)

```hcl
# ── Email on-call channel ────────────────────────────────────────────
resource "google_monitoring_notification_channel" "email_oncall" {
  display_name = "SmartHandoff On-Call Email (${var.environment})"
  type         = "email"
  project      = var.project_id
  enabled      = true

  labels = {
    email_address = var.oncall_email
  }

  # Verification: channel will be in UNVERIFIED state until confirmed
  # via email link. For automated testing, use force_send_fields.
}

# ── Slack channel ────────────────────────────────────────────────────
resource "google_monitoring_notification_channel" "slack" {
  display_name = "SmartHandoff Slack #alerts (${var.environment})"
  type         = "slack"
  project      = var.project_id
  enabled      = true

  labels = {
    channel_name = var.slack_alert_channel  # e.g. "#smarthandoff-alerts-dev"
  }

  sensitive_labels {
    auth_token = data.google_secret_manager_secret_version.slack_auth_token.secret_data
  }
}

data "google_secret_manager_secret_version" "slack_auth_token" {
  secret  = "smarthandoff-slack-webhook-url-${var.environment}"
  project = var.project_id
}

output "email_oncall_channel_id" {
  value = google_monitoring_notification_channel.email_oncall.id
}

output "slack_channel_id" {
  value = google_monitoring_notification_channel.slack.id
}
```

### 2. Uptime Check (`modules/monitoring/uptime.tf`)

```hcl
# ── API Gateway /health uptime check ────────────────────────────────
resource "google_monitoring_uptime_check_config" "api_gateway_health" {
  display_name = "API Gateway /health — ${var.environment}"
  project      = var.project_id
  timeout      = "10s"
  period       = "60s"  # Check every 60 seconds

  http_check {
    path           = "/health"
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"

    # Expect HTTP 200 response
    accepted_response_status_codes {
      status_class = "STATUS_CLASS_2XX"
    }

    # Validate response body contains expected JSON
    content_matchers {
      content = "\"status\""
      matcher = "CONTAINS_STRING"
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = var.api_domain  # e.g. api.staging.smarthandoff.health
    }
  }

  # Check from 3 global regions for geographic redundancy
  selected_regions = ["USA", "EUROPE", "ASIA_PACIFIC"]
}

# ── Uptime alert: fires after 2 consecutive failures (AC-7) ─────────
resource "google_monitoring_alert_policy" "p1_api_uptime" {
  display_name = "P1: API Gateway Health Check Failing — ${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  severity     = "CRITICAL"
  enabled      = true

  conditions {
    display_name = "Uptime check failing from 2+ consecutive check regions"

    condition_threshold {
      filter = <<-EOT
        metric.type = "monitoring.googleapis.com/uptime_check/check_passed"
        AND metric.labels.check_id = "${google_monitoring_uptime_check_config.api_gateway_health.uptime_check_id}"
      EOT
      comparison      = "COMPARISON_LT"
      threshold_value = 1   # check_passed = 1 means passing; 0 = failing
      duration        = "120s"  # 2 consecutive failures (checks every 60s = 2 × 60s = 120s)

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"  # Count of failing checks
        group_by_fields      = ["resource.labels.checker_location"]
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email_oncall.id,
    google_monitoring_notification_channel.slack.id,
  ]

  documentation {
    content   = "API Gateway health check is failing from multiple regions. Service may be down or the load balancer is misconfigured. Check: `gcloud run services describe api-gateway-${var.environment} --region=us-central1`"
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close              = "1800s"
    notification_rate_limit { period = "300s" }
  }
}
```

### 3. Variables for This Module

```hcl
# Add to modules/monitoring/variables.tf
variable "oncall_email" {
  type        = string
  description = "On-call engineer email address for P1/P2 alert notifications"
}

variable "slack_alert_channel" {
  type        = string
  description = "Slack channel name for alerts (e.g. #smarthandoff-alerts-dev)"
  default     = "#smarthandoff-alerts"
}

variable "api_domain" {
  type        = string
  description = "Fully qualified API domain for uptime check (e.g. api.staging.smarthandoff.health)"
}
```

### 4. Wire Notification Channel IDs into Alert Policies

The alert policies in Task 002 reference channel IDs via variables. Update the environment root module to wire them:

```hcl
# environments/dev/main.tf — add to monitoring module call
module "monitoring" {
  source      = "../../modules/monitoring"
  project_id  = var.project_id
  environment = var.environment
  api_domain  = var.api_domain
  oncall_email       = var.oncall_email
  slack_alert_channel = "#smarthandoff-alerts-dev"
  # These are outputs from the same monitoring module:
  email_oncall_channel_id = module.monitoring.email_oncall_channel_id
  slack_channel_id        = module.monitoring.slack_channel_id
}
```

> Note: Since the channels and policies are in the same module, reference them directly as local resource attributes (`google_monitoring_notification_channel.email_oncall.id`) rather than via variables — simpler and avoids circular dependency.

### 5. Manual Notification Channel Verification

After `terraform apply`, verify each channel is functional:

```bash
# Test email channel — send a test notification
gcloud alpha monitoring channels verify \
  $(terraform output -raw email_oncall_channel_id) \
  --project=smarthandoff-dev

# For Slack: the channel requires OAuth bot token verification
# Check Slack channel receives test message in #smarthandoff-alerts-dev
```

> **Important:** Email notification channels start in `UNVERIFIED` state and must be confirmed via an email sent to `oncall_email` before they can receive alerts. Include this step in the Day 1 bootstrap checklist.

## Acceptance Criteria

- [ ] **AC-7:** `gcloud monitoring uptime-checks list --project={PROJECT}` shows `api-gateway-health-{env}` with status ACTIVE and period 60s
- [ ] **AC-7:** 2 consecutive health check failures trigger alert: stop API Gateway service → wait 3 minutes → verify P1 alert email/Slack received; restart service → alert auto-closes
- [ ] Email notification channel exists and is VERIFIED (confirmed via bootstrap email click): `gcloud monitoring channels describe {channel_id} --format=json | jq '.verificationStatus'` returns `"VERIFIED"`
- [ ] Slack channel receives test notification: `gcloud alpha monitoring channels verify {slack_channel_id}` — confirm Slack message in #smarthandoff-alerts channel
- [ ] Uptime check runs from 3 regions (`USA`, `EUROPE`, `ASIA_PACIFIC`) — confirmed in Cloud Console → Monitoring → Uptime Checks

## Files to Create

```
infra/terraform/modules/monitoring/notification_channels.tf
infra/terraform/modules/monitoring/uptime.tf
```

## Notes

- Email channels require human verification (inbox click) after `terraform apply` — this is a Google requirement and cannot be automated; add it to `BOOTSTRAP.md`
- Slack monitoring integration requires a Slack bot token (OAuth token), NOT the webhook URL used in Task 007 of US-002 — they are different credentials
- Uptime checks from 3 regions prevent false positives from single-region network issues; the alert condition requires 2+ consecutive failures to fire
- `COMPARISON_LT threshold_value = 1` for uptime means: alert when `check_passed < 1` i.e. when the check fails (0 = failed, 1 = passed)
