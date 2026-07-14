---
id: TASK-003
title: "Implement Uptime Checks for All 10 Services in `monitoring` Terraform Module"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001]
---

# TASK-003: Implement Uptime Checks for All 10 Services in `monitoring` Terraform Module

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-004 Acceptance Criterion 3 (Scenario 3) requires uptime checks on all 10 service `/health` endpoints at a 60-second check interval. When a service returns non-2xx for 2 consecutive checks, an uptime alert must fire and the affected service must appear as "failing" on the Cloud Monitoring dashboard.

All 10 services are Cloud Run services deployed behind Cloud Armor + Load Balancer with the domain pattern `<service>.api_domain`. This task uses a `for_each` over a local service map to avoid duplicating 10 identical resource blocks (DRY principle).

### Services to Monitor

| Service Name | Cloud Run Service Slug | Health Path |
|---|---|---|
| API Gateway | `api-gateway` | `/health` |
| HL7 Listener | `hl7-listener` | `/health` |
| Transition Coordinator Agent | `coordinator-agent` | `/health` |
| Documentation Agent | `docs-agent` | `/health` |
| Medication Reconciliation Agent | `medrecon-agent` | `/health` |
| Bed Management Agent | `bed-management-agent` | `/health` |
| Follow-up Care Agent | `followup-care-agent` | `/health` |
| Patient Communication Agent | `patient-comms-agent` | `/health` |
| ML Inference Service | `ml-inference` | `/health` |
| Notification Service | `notification-svc` | `/health` |

---

## Acceptance Criteria Addressed

| US-004 AC | Requirement |
|---|---|
| **Scenario 3** | Uptime check detects non-2xx `/health` response for 2 consecutive checks (60s interval) and fires uptime alert |

---

## Implementation Steps

### 1. Add Service Map Local and Uptime Check Resources to `monitoring/main.tf`

Append the following after the alert policy resources from TASK-002:

```hcl
# ── Uptime check service map ─────────────────────────────────────────────────
locals {
  monitored_services = {
    "api-gateway"          = "api-gateway"
    "hl7-listener"         = "hl7-listener"
    "coordinator-agent"    = "coordinator-agent"
    "docs-agent"           = "docs-agent"
    "medrecon-agent"       = "medrecon-agent"
    "bed-management-agent" = "bed-management-agent"
    "followup-care-agent"  = "followup-care-agent"
    "patient-comms-agent"  = "patient-comms-agent"
    "ml-inference"         = "ml-inference"
    "notification-svc"     = "notification-svc"
  }
}

# ── Uptime checks — one per service ─────────────────────────────────────────
resource "google_monitoring_uptime_check_config" "service_health" {
  for_each     = local.monitored_services
  project      = var.project_id
  display_name = "SmartHandoff ${each.key} /health (${var.environment})"
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true

    accepted_response_status_codes {
      status_class = "STATUS_CLASS_2XX"
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = "${each.value}.${var.api_domain}"
    }
  }

  user_labels = {
    service     = each.key
    environment = var.environment
    managed_by  = "terraform"
  }
}
```

### 2. Add Uptime Failure Alert Policy to `monitoring/main.tf`

An uptime check without an associated alert policy does not page anyone. Add a single alert policy that fires when **any** uptime check fails 2 consecutive times:

```hcl
resource "google_monitoring_alert_policy" "uptime_failure" {
  project      = var.project_id
  display_name = "[P1] SmartHandoff — Uptime Check Failure (${var.environment})"
  combiner     = "OR"

  dynamic "conditions" {
    for_each = google_monitoring_uptime_check_config.service_health

    content {
      display_name = "${conditions.value.display_name} — consecutive failures"

      condition_threshold {
        filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id=\"${conditions.value.uptime_check_id}\""
        duration        = "120s"
        comparison      = "COMPARISON_LT"
        threshold_value = 1

        aggregations {
          alignment_period     = "60s"
          per_series_aligner   = "ALIGN_NEXT_OLDER"
          cross_series_reducer = "REDUCE_COUNT_FALSE"
          group_by_fields      = ["resource.labels.host"]
        }
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email.name,
    google_monitoring_notification_channel.pagerduty.name,
  ]

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }

  user_labels = {
    severity    = "p1"
    environment = var.environment
    managed_by  = "terraform"
  }

  documentation {
    content   = "P1 — A SmartHandoff service /health endpoint has returned non-2xx for 2 consecutive uptime checks. Verify Cloud Run service is running and not in a crash-loop. Runbook: https://wiki.internal/runbooks/smarthandoff-uptime-failure"
    mime_type = "text/markdown"
  }
}
```

### 3. Export Uptime Check IDs in `monitoring/outputs.tf`

Append to existing outputs:

```hcl
output "uptime_check_ids" {
  description = "Map of service name to uptime check ID for all monitored services."
  value       = { for k, v in google_monitoring_uptime_check_config.service_health : k => v.uptime_check_id }
}
```

---

## Files Changed

| File | Action |
|---|---|
| `infra/terraform/modules/monitoring/main.tf` | Append `locals`, uptime check resource, and uptime alert policy |
| `infra/terraform/modules/monitoring/outputs.tf` | Append uptime check IDs output |

---

## Definition of Done

- [ ] `terraform validate` passes with 10 uptime check resources and 1 uptime alert policy
- [ ] `terraform plan` shows 10 `google_monitoring_uptime_check_config` resources (one per service)
- [ ] Each uptime check targets `<service>.<api_domain>` with HTTPS, 60-second period, 10-second timeout
- [ ] Uptime alert policy references both email and PagerDuty channels
- [ ] `terraform output uptime_check_ids` displays a map with all 10 service entries
