---
task_id: task_001
story_id: us_003
epic: EP-TECH
title: Cloud Monitoring Dashboard — Per-Service Metrics for All 10 Cloud Run Services
layer: Observability / IaC
effort_hours: 2
sequence: 1
status: Draft
---

# TASK-001: Cloud Monitoring Dashboard — Per-Service Metrics for All 10 Cloud Run Services

> **Story:** EP-TECH/US-003 | **Layer:** Observability / IaC | **Effort:** 2 hours | **Seq:** 1 of 4

## Objective

Create a Terraform-managed Cloud Monitoring custom dashboard that shows request count, error rate, p50/p95/p99 latency, CPU utilisation, memory utilisation, and instance count for all 10 SmartHandoff Cloud Run services — satisfying AC-1.

## Implementation Steps

### 1. Dashboard Resource (`modules/monitoring/dashboard.tf`)

```hcl
resource "google_monitoring_dashboard" "smarthandoff" {
  project        = var.project_id
  dashboard_json = templatefile(
    "${path.module}/templates/dashboard.json.tpl",
    {
      project_id  = var.project_id
      environment = var.environment
      services    = local.cloud_run_services
    }
  )
}

locals {
  cloud_run_services = [
    "api-gateway", "hl7-listener", "coordinator-agent", "docs-agent",
    "medrecon-agent", "bed-mgmt-agent", "followup-agent", "comms-agent",
    "ml-inference", "notification-svc"
  ]
}
```

### 2. Dashboard JSON Template (`modules/monitoring/templates/dashboard.json.tpl`)

The dashboard uses a row-per-service layout with six metric tiles per row:

```json
{
  "displayName": "SmartHandoff Service Health — ${environment}",
  "mosaicLayout": {
    "columns": 12,
    "tiles": [
      %{ for idx, svc in services ~}
      {
        "width": 2, "height": 2,
        "xPos": 0, "yPos": ${idx * 2},
        "widget": {
          "title": "${svc} — Request Rate",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${svc}-${environment}\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_RATE",
                    "crossSeriesReducer": "REDUCE_SUM"
                  }
                }
              },
              "plotType": "LINE"
            }],
            "yAxis": { "label": "req/s", "scale": "LINEAR" }
          }
        }
      },
      {
        "width": 2, "height": 2,
        "xPos": 2, "yPos": ${idx * 2},
        "widget": {
          "title": "${svc} — Error Rate",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${svc}-${environment}\" metric.labels.response_code_class=\"5xx\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_RATE"
                  }
                }
              },
              "plotType": "LINE"
            }],
            "yAxis": { "label": "errors/s", "scale": "LINEAR" }
          }
        }
      },
      {
        "width": 2, "height": 2,
        "xPos": 4, "yPos": ${idx * 2},
        "widget": {
          "title": "${svc} — p50/p95/p99 Latency",
          "xyChart": {
            "dataSets": [
              %{ for pct in ["50", "95", "99"] ~}
              {
                "timeSeriesQuery": {
                  "timeSeriesFilter": {
                    "filter": "metric.type=\"run.googleapis.com/request_latencies\" resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${svc}-${environment}\"",
                    "aggregation": {
                      "alignmentPeriod": "60s",
                      "perSeriesAligner": "ALIGN_PERCENTILE_${pct}"
                    }
                  }
                },
                "legendTemplate": "p${pct}",
                "plotType": "LINE"
              }%{ if pct != "99" },%{ endif }
              %{ endfor ~}
            ],
            "yAxis": { "label": "ms", "scale": "LINEAR" }
          }
        }
      },
      {
        "width": 2, "height": 2,
        "xPos": 6, "yPos": ${idx * 2},
        "widget": {
          "title": "${svc} — CPU Utilisation",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"run.googleapis.com/container/cpu/utilizations\" resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${svc}-${environment}\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_PERCENTILE_99",
                    "crossSeriesReducer": "REDUCE_MAX"
                  }
                }
              },
              "plotType": "LINE"
            }],
            "yAxis": { "label": "CPU %", "scale": "LINEAR" }
          }
        }
      },
      {
        "width": 2, "height": 2,
        "xPos": 8, "yPos": ${idx * 2},
        "widget": {
          "title": "${svc} — Memory Utilisation",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"run.googleapis.com/container/memory/utilizations\" resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${svc}-${environment}\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_PERCENTILE_99",
                    "crossSeriesReducer": "REDUCE_MAX"
                  }
                }
              },
              "plotType": "LINE"
            }],
            "yAxis": { "label": "Memory %", "scale": "LINEAR" }
          }
        }
      },
      {
        "width": 2, "height": 2,
        "xPos": 10, "yPos": ${idx * 2},
        "widget": {
          "title": "${svc} — Instance Count",
          "xyChart": {
            "dataSets": [{
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"run.googleapis.com/container/instance_count\" resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${svc}-${environment}\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "perSeriesAligner": "ALIGN_MAX",
                    "crossSeriesReducer": "REDUCE_SUM"
                  }
                }
              },
              "plotType": "STACKED_BAR"
            }],
            "yAxis": { "label": "instances", "scale": "LINEAR" }
          }
        }
      }%{ if svc != last(services) },%{ endif }
      %{ endfor ~}
    ]
  }
}
```

### 3. Dashboard Output

```hcl
output "dashboard_url" {
  value = "https://console.cloud.google.com/monitoring/dashboards/custom/${google_monitoring_dashboard.smarthandoff.id}?project=${var.project_id}"
}
```

### 4. Shortcut — Import from gcloud (Alternative Approach)

If the JSON template approach is complex to maintain, create the dashboard interactively in Cloud Console and export to Terraform:

```bash
# 1. Create dashboard in Cloud Console → Monitoring → Dashboards
# 2. Get the dashboard ID from the URL
DASHBOARD_ID="projects/smarthandoff-dev/dashboards/XXXXXXXXX"

# 3. Export to JSON
gcloud monitoring dashboards describe "$DASHBOARD_ID" --format=json > dashboard.json

# 4. Import into Terraform state
terraform import google_monitoring_dashboard.smarthandoff "$DASHBOARD_ID"

# 5. Generate Terraform resource from state
terraform show -json | jq '.values.root_module.resources[] | select(.type=="google_monitoring_dashboard")'
```

## Acceptance Criteria

- [ ] **AC-1:** Cloud Console → Monitoring → Dashboards shows "SmartHandoff Service Health — {env}" with 10 service rows × 6 metric panels = 60 total panels
- [ ] Each service row shows: request rate (req/s), error rate (errors/s), latency (p50/p95/p99 ms), CPU (%), memory (%), instance count — all sourced from `run.googleapis.com/*` metrics
- [ ] Dashboard renders with live data after 1+ minute of traffic to any Cloud Run service
- [ ] `terraform plan` after initial apply shows "0 to add, 0 to change, 0 to destroy" — confirms idempotency
- [ ] Dashboard accessible via the output URL: `terraform output dashboard_url`

## Files to Create

```
infra/terraform/modules/monitoring/dashboard.tf
infra/terraform/modules/monitoring/templates/dashboard.json.tpl
```

## Notes

- Terraform `templatefile()` with a Terraform for-loop generates the 60 panel JSON at plan time — no hardcoded service names needed
- `ALIGN_PERCENTILE_50/95/99` aligner directly produces p50/p95/p99 from Cloud Run's histogram latency metric without additional post-processing
- The `"mosaicLayout"` dashboard type is preferred over `"gridLayout"` for precise tile positioning
- Dashboard JSON can be large (>50KB for 10 services × 6 panels); Terraform handles this fine but `terraform plan` output will be verbose
