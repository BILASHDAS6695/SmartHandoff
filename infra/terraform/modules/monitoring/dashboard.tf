# monitoring/dashboard.tf
# SmartHandoff Operations Dashboard — 4-tile mosaic layout.
# Implemented by: EP-TECH / US-004 / TASK-004
#
# Tiles:
#   1. Service Health — stacked bar of request count by response class
#   2. ADT Event Throughput — Pub/Sub adt-events topic publish rate
#   3. Agent Latency p95 — p95 request duration with P2 SLA threshold line
#   4. Error Rates — 5xx responses per service

resource "google_monitoring_dashboard" "smarthandoff" {
  project = var.project_id

  dashboard_json = jsonencode({
    displayName = "SmartHandoff — Operations (${var.environment})"
    mosaicLayout = {
      columns = 12
      tiles = [
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
                    filter = "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND resource.labels.project_id=\"${var.project_id}\""
                    aggregation = {
                      alignmentPeriod    = "60s"
                      perSeriesAligner   = "ALIGN_RATE"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["resource.labels.service_name", "metric.labels.response_code_class"]
                    }
                  }
                }
                plotType       = "STACKED_BAR"
                legendTemplate = "$${labels.service_name} — $${labels.response_code_class}"
              }]
              timeshiftDuration = "0s"
              yAxis             = { label = "Requests / s", scale = "LINEAR" }
            }
          }
        },
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
                    filter = "metric.type=\"pubsub.googleapis.com/topic/send_message_operation_count\" AND resource.type=\"pubsub_topic\" AND resource.labels.topic_id=\"smarthandoff-adt-events-${var.environment}\" AND resource.labels.project_id=\"${var.project_id}\""
                    aggregation = {
                      alignmentPeriod  = "60s"
                      perSeriesAligner = "ALIGN_RATE"
                    }
                  }
                }
                plotType       = "LINE"
                legendTemplate = "ADT Events Published / s"
              }]
              yAxis = { label = "Events / s", scale = "LINEAR" }
            }
          }
        },
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
                    filter = "metric.type=\"run.googleapis.com/request_latencies\" AND resource.type=\"cloud_run_revision\" AND resource.labels.project_id=\"${var.project_id}\""
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
                value      = 5000
                color      = "RED"
                direction  = "ABOVE"
                targetAxis = "Y1"
                label      = "P2 SLA Threshold (5 s)"
              }]
              yAxis = { label = "Latency (ms)", scale = "LINEAR" }
            }
          }
        },
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
                    filter = "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND metric.labels.response_code_class=\"5xx\" AND resource.labels.project_id=\"${var.project_id}\""
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
              yAxis = { label = "5xx Errors / s", scale = "LINEAR" }
            }
          }
        }
      ]
    }
  })
}
