output "canary_rollback_topic_ids" {
  description = "Map of service name → Pub/Sub topic ID for canary rollback notifications"
  value       = { for k, v in google_pubsub_topic.canary_rollback : k => v.id }
}

output "canary_error_rate_policy_ids" {
  description = "Map of service name → Cloud Monitoring alert policy name"
  value       = { for k, v in google_monitoring_alert_policy.canary_error_rate : k => v.name }
}

output "rollback_trigger_names" {
  description = "Map of service name → Cloud Build rollback trigger name"
  value       = { for k, v in google_cloudbuild_trigger.rollback : k => v.name }
}

output "email_notification_channel_id" {
  description = "Resource name of the email notification channel (oncall)"
  value       = google_monitoring_notification_channel.email.name
}

output "pagerduty_notification_channel_id" {
  description = "Resource name of the PagerDuty notification channel (empty string if not configured)"
  value       = var.pagerduty_integration_key != "" ? google_monitoring_notification_channel.pagerduty[0].name : ""
  sensitive   = true
}

output "p1_error_rate_alert_policy_id" {
  description = "Resource name of the P1 error rate alert policy"
  value       = google_monitoring_alert_policy.p1_error_rate.name
}

output "p2_latency_alert_policy_id" {
  description = "Resource name of the P2 latency p95 alert policy"
  value       = google_monitoring_alert_policy.p2_latency_p95.name
}

output "p3_dlq_alert_policy_id" {
  description = "Resource name of the P3 DLQ alert policy"
  value       = google_monitoring_alert_policy.p3_dlq_messages.name
}

output "uptime_check_ids" {
  description = "Map of service name → uptime check ID"
  value       = { for k, v in google_monitoring_uptime_check_config.service_health : k => v.uptime_check_id }
}

output "audit_log_bucket_name" {
  description = "Name of the GCS bucket receiving full audit logs (including PHI)"
  value       = google_storage_bucket.audit_logs.name
}

output "dashboard_url" {
  description = "Cloud Console URL for the SmartHandoff operations dashboard"
  value       = "https://console.cloud.google.com/monitoring/dashboards/custom/${google_monitoring_dashboard.smarthandoff.id}?project=${var.project_id}"
}

output "audit_log_sink_writer_identity" {
  description = "Service account identity used by the log sink to write to the audit bucket"
  value       = google_logging_project_sink.audit_sink.writer_identity
}
