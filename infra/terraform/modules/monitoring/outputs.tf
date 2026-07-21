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
