# monitoring module
# Provisions canary error-rate alert policies, Pub/Sub rollback channels,
# and Cloud Build rollback triggers for all 10 SmartHandoff services.
# Implemented by: EP-TECH / US-003 / TASK-005

locals {
  # CI/CD services that have canary deployments monitored for error rate spikes
  cicd_services = toset([
    "api-gateway", "hl7-listener", "coordinator-agent", "docs-agent",
    "medrecon-agent", "comms-agent", "ml-inference", "notification-svc",
    "audit-svc", "portal-bff",
  ])
}

# ── Pub/Sub topics for canary rollback notifications ─────────────────────────
resource "google_pubsub_topic" "canary_rollback" {
  for_each = local.cicd_services
  name     = "smarthandoff-canary-rollback-${each.key}-${var.environment}"
  project  = var.project_id

  labels = {
    environment = var.environment
    managed_by  = "terraform"
    purpose     = "canary-rollback"
  }
}

# Grant the Cloud Monitoring service agent permission to publish to these topics
resource "google_pubsub_topic_iam_member" "monitoring_publisher" {
  for_each = local.cicd_services
  topic    = google_pubsub_topic.canary_rollback[each.key].name
  project  = var.project_id
  role     = "roles/pubsub.publisher"
  member   = "serviceAccount:service-${var.project_number}@gcp-sa-monitoring-notification.iam.gserviceaccount.com"
}

# ── Cloud Monitoring notification channels (Pub/Sub) ─────────────────────────
resource "google_monitoring_notification_channel" "canary_rollback_pubsub" {
  for_each     = local.cicd_services
  display_name = "canary-rollback-pubsub-${each.key}-${var.environment}"
  type         = "pubsub"
  project      = var.project_id

  labels = {
    topic = google_pubsub_topic.canary_rollback[each.key].id
  }
}

# Email notification channel for all alert types
resource "google_monitoring_notification_channel" "oncall_email" {
  display_name = "SmartHandoff On-Call Email (${var.environment})"
  type         = "email"
  project      = var.project_id

  labels = {
    email_address = var.oncall_email
  }
}

# ── Canary error-rate alert policy (per service) ─────────────────────────────
# Fires when 5xx error rate > 1% on any revision of the service within 5 minutes.
# Notifies: Pub/Sub (→ cicd-alert-handler → Cloud Build rollback) + email.
resource "google_monitoring_alert_policy" "canary_error_rate" {
  for_each     = local.cicd_services
  display_name = "smarthandoff-${each.key}-canary-error-rate-${var.environment}"
  project      = var.project_id
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "5xx error rate > 1% on ${each.key}-${var.environment} (5-min window)"

    condition_threshold {
      filter = <<-EOT
        resource.type = "cloud_run_revision"
        AND resource.labels.service_name = "${each.key}-${var.environment}"
        AND metric.type = "run.googleapis.com/request_count"
        AND metric.labels.response_code_class = "5xx"
      EOT

      aggregations {
        alignment_period     = "300s"          # 5-minute observation window
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.labels.revision_name"]
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 0.01   # 1% error rate threshold
      duration        = "0s"   # Fire immediately when threshold is crossed

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.canary_rollback_pubsub[each.key].id,
    google_monitoring_notification_channel.oncall_email.id,
  ]

  alert_strategy {
    auto_close = "1800s"   # Auto-resolve after 30 minutes if error rate drops
  }

  documentation {
    content   = "Canary error rate exceeded 1% for `${each.key}-${var.environment}`. Automated rollback triggered via Pub/Sub → cicd-alert-handler → Cloud Build rollback job. Check Cloud Run logs for root cause."
    mime_type = "text/markdown"
  }
}

# ── Cloud Build rollback triggers (per service) ───────────────────────────────
# Triggered by the cicd-alert-handler Cloud Run service via the Cloud Build API.
# Uses cloudbuild-rollback.yaml to restore 100% traffic to the previous stable revision.
resource "google_cloudbuild_trigger" "rollback" {
  for_each    = local.cicd_services
  name        = "smarthandoff-${each.key}-rollback-${var.environment}"
  description = "Automated canary rollback for ${each.key} (${var.environment})"
  project     = var.project_id
  location    = "global"

  # Rollback is triggered programmatically (not by a branch push) —
  # use webhook trigger type so it can be invoked via the Cloud Build API
  webhook_config {
    secret = google_secret_manager_secret_version.rollback_webhook_secret[each.key].id
  }

  filename = ".cloudbuild/cloudbuild-rollback.yaml"

  substitutions = {
    _SERVICE_NAME = each.key
    _ENVIRONMENT  = var.environment
    _REGION       = var.region
    _PROJECT_ID   = var.project_id
  }

  service_account = "projects/${var.project_id}/serviceAccounts/${var.cloudbuild_sa_email}"
}

# Webhook secrets for rollback triggers (one per service)
resource "google_secret_manager_secret" "rollback_webhook_secret" {
  for_each  = local.cicd_services
  secret_id = "cloudbuild-rollback-webhook-${each.key}-${var.environment}"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
    purpose     = "cloudbuild-webhook"
  }
}

resource "google_secret_manager_secret_version" "rollback_webhook_secret" {
  for_each    = local.cicd_services
  secret      = google_secret_manager_secret.rollback_webhook_secret[each.key].id
  secret_data = "PLACEHOLDER_CHANGE_BEFORE_DEPLOY"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

