# ── HL7 Listener → adt-events (publisher) ────────────────────────────
resource "google_pubsub_topic_iam_member" "hl7_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.adt_events.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.hl7_listener_sa}"
}

# ── Each agent SA subscribes to its own subscription ─────────────────
resource "google_pubsub_subscription_iam_member" "agent_subscribers" {
  for_each = local.agent_subscriptions

  project      = var.project_id
  subscription = google_pubsub_subscription.agent_subs[each.key].name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${var.agent_service_accounts[each.value]}"
}

# ── Pub/Sub service agent → DLQ topic (required for dead-letter routing) ──
# The Pub/Sub service agent (not the app SA) must be able to publish to the DLQ.
# This is a common misconfiguration — without this binding, DLQ delivery silently fails.
resource "google_pubsub_topic_iam_member" "pubsub_dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.adt_events_dlq.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic_iam_member" "pubsub_notification_dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.notification_dlq.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# ── Agent SAs → notification-requests topic (publisher) ──────────────
# Agents publish notification requests (reminders, alerts, OTP dispatch).
# Scoped to only the agent SAs that actually need to publish notifications.
resource "google_pubsub_topic_iam_member" "agent_notification_publishers" {
  for_each = {
    for name, email in var.agent_service_accounts :
    name => email
    if contains([
      "coordinator-agent", "docs-agent", "medrecon-agent",
      "bed-mgmt-agent", "followup-agent", "comms-agent"
    ], name)
  }

  project = var.project_id
  topic   = google_pubsub_topic.notification_requests.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${each.value}"
}

# ── Notification service SA → notification-requests subscription ──────
resource "google_pubsub_subscription_iam_member" "notification_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.notification_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${var.agent_service_accounts["notification-svc"]}"
}
