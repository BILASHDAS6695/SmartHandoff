output "adt_events_topic_id" {
  description = "Pub/Sub topic ID for ADT events (input to HL7 Listener publisher)"
  value       = google_pubsub_topic.adt_events.id
}

output "adt_events_topic_name" {
  description = "Short name of the adt-events topic"
  value       = google_pubsub_topic.adt_events.name
}

output "adt_events_dlq_topic_id" {
  description = "Dead Letter Queue topic ID for failed ADT event messages"
  value       = google_pubsub_topic.adt_events_dlq.id
}

output "notification_requests_topic_id" {
  description = "Pub/Sub topic ID for notification dispatch requests"
  value       = google_pubsub_topic.notification_requests.id
}

output "notification_requests_topic_name" {
  description = "Short name of the notification-requests topic"
  value       = google_pubsub_topic.notification_requests.name
}

output "agent_subscription_ids" {
  description = "Map of subscription name \u2192 subscription ID for all agent subscriptions"
  value       = { for k, v in google_pubsub_subscription.agent_subs : k => v.id }
}

output "notification_subscription_id" {
  description = "Subscription ID for the notification service consumer"
  value       = google_pubsub_subscription.notification_sub.id
}
