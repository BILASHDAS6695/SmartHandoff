---
id: TASK-004
title: "Implement Cloud Monitoring Dashboard as `google_monitoring_dashboard` Terraform Resource"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-002, TASK-003]
---

# TASK-004: Implement Cloud Monitoring Dashboard as `google_monitoring_dashboard` Terraform Resource

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-004 DoD requires: *"Cloud Monitoring dashboards created: service health, ADT throughput, agent latency, error rates"*. The Technical Notes specify: *"Dashboard JSON exported as Terraform `google_monitoring_dashboard` resource"*.

This task authors the dashboard JSON inline in a Terraform `google_monitoring_dashboard` resource with four widget panels corresponding to the four required views. Each widget uses the `timeSeriesQuery` format pointing at Cloud Monitoring metrics for Cloud Run services and Pub/Sub subscriptions.

---

## Acceptance Criteria Addressed

| US-004 AC | Requirement |
|---|---|
| **Scenario 1** | Cloud Monitoring dashboard shows the active P1 alert |
| **Scenario 3** | Affected service shows as "failing" on the Cloud Monitoring dashboard |

---

## Implementation Steps

### 1. Author `monitoring/dashboard.tf`

Create a separate file `infra/terraform/modules/monitoring/dashboard.tf` to keep the dashboard JSON isolated from the alert/uptime resources in `main.tf`. The dashboard contains four tile widgets:

| Widget | Metric | Visualisation |
|---|---|---|
| Service Health | `run.googleapis.com/request_count` by `response_code_class` | Stacked bar |
| ADT Throughput | `pubsub.googleapis.com/topic/send_message_operation_count` for `adt-events` | Line chart |
| Agent Latency (p95) | `run.googleapis.com/request_latencies` percentile 95 | Line chart |
| Error Rates | `run.googleapis.com/request_count` filtered to `5xx` | Line chart |

```hcl
resource "google_monitoring_dashboard" "smarthandoff" {
  project        = var.project_id
  dashboard_json = jsonencode({
    displayName = "SmartHandoff — Operations (${var.environment})"
    mosaicLayout = {
      columns = 12
      tiles = [

        # ── Tile 1: Service Health (request count by response class) ──────────
        {
          xPos   = 0
          yPos   = 0
          width  = 6
          height = 4
          widget = {
            title = "Service Health — Request Count by Response Class"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = join(" AND ", [
                      "metric.type=\"run.googleapis.com/request_count\"",
                      "resource.type=\"cloud_run_revision\"",
                      "resource.labels.project_id=\"${var.project_id}\""
                    ])
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = [
                        "resource.labels.service_name",
                        "metric.labels.response_code_class"
                      ]
                    }
                  }
                }
                plotType   = "STACKED_BAR"
                legendTemplate = "$${labels.service_name} — $${labels.response_code_class}"
              }]
              timeshiftDuration = "0s"
              yAxis = { label = "Requests / s" scale = "LINEAR" }
            }
          }
        },

        # ── Tile 2: ADT Throughput (Pub/Sub adt-events topic) ─────────────────
        {
          xPos   = 6
          yPos   = 0
          width  = 6
          height = 4
          widget = {
            title = "ADT Event Throughput — Pub/Sub adt-events"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = join(" AND ", [
                      "metric.type=\"pubsub.googleapis.com/topic/send_message_operation_count\"",
                      "resource.type=\"pubsub_topic\"",
                      "resource.labels.topic_id=\"smarthandoff-adt-events-${var.environment}\"",
                      "resource.labels.project_id=\"${var.project_id}\""
                    ])
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType       = "LINE"
                legendTemplate = "ADT Events Published / s"
              }]
              yAxis = { label = "Events / s" scale = "LINEAR" }
            }
          }
        },

        # ── Tile 3: Agent Latency p95 ──────────────────────────────────────────
        {
          xPos   = 0
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Agent Latency — p95 Request Duration (ms)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = join(" AND ", [
                      "metric.type=\"run.googleapis.com/request_latencies\"",
                      "resource.type=\"cloud_run_revision\"",
                      "resource.labels.project_id=\"${var.project_id}\""
                    ])
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_DELTA"
                      crossSeriesReducer = "REDUCE_PERCENTILE_95"
                      groupByFields      = ["resource.labels.service_name"]
                    }
                  }
                }
                plotType       = "LINE"
                legendTemplate = "$${labels.service_name} p95"
              }]
              thresholds = [{
                value             = 5000
                color             = "RED"
                direction         = "ABOVE"
                targetAxis        = "Y1"
                label             = "P2 SLA Threshold (5 s)"
              }]
              yAxis = { label = "Latency (ms)" scale = "LINEAR" }
            }
          }
        },

        # ── Tile 4: Error Rates ────────────────────────────────────────────────
        {
          xPos   = 6
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Error Rates — 5xx Responses per Service"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = join(" AND ", [
                      "metric.type=\"run.googleapis.com/request_count\"",
                      "resource.type=\"cloud_run_revision\"",
                      "metric.labels.response_code_class=\"5xx\"",
                      "resource.labels.project_id=\"${var.project_id}\""
                    ])
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["resource.labels.service_name"]
                    }
                  }
                }
                plotType       = "LINE"
                legendTemplate = "$${labels.service_name} 5xx / s"
              }]
              yAxis = { label = "5xx Errors / s" scale = "LINEAR" }
            }
          }
        }

      ]
    }
  })
}
```

### 2. Export Dashboard URL in `monitoring/outputs.tf`

Append:

```hcl
output "dashboard_url" {
  description = "Cloud Console URL for the SmartHandoff operations dashboard."
  value       = "https://console.cloud.google.com/monitoring/dashboards/custom/${google_monitoring_dashboard.smarthandoff.id}?project=${var.project_id}"
}
```

---

## Files Changed

| File | Action |
|---|---|
| `infra/terraform/modules/monitoring/dashboard.tf` | Create new file with `google_monitoring_dashboard` resource |
| `infra/terraform/modules/monitoring/outputs.tf` | Append `dashboard_url` output |

---

## Definition of Done

- [ ] `terraform validate` passes with the new `dashboard.tf` file
- [ ] `terraform plan` shows one `google_monitoring_dashboard` resource
- [ ] `terraform apply` creates the dashboard and `terraform output dashboard_url` returns a valid console URL
- [ ] Dashboard displays all four widget panels when opened in Cloud Console
- [ ] P2 latency threshold line (5000 ms) is visible on the Agent Latency tile
