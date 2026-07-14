# ── Topics ───────────────────────────────────────────────────────────────
resource "google_pubsub_topic" "adt_events" {
  name    = "adt-events-${var.environment}"
  project = var.project_id

  # Message ordering is enforced per-subscription via ordering_key, not at the topic level.
  message_retention_duration = "604800s" # 7-day replay window for audit / re-processing
}

resource "google_pubsub_topic" "adt_events_dlq" {
  name                       = "adt-events-dlq-${var.environment}"
  project                    = var.project_id
  message_retention_duration = "604800s"
}

resource "google_pubsub_topic" "notification_requests" {
  name                       = "notification-requests-${var.environment}"
  project                    = var.project_id
  message_retention_duration = "86400s" # 24-hour retention sufficient for notifications
}

resource "google_pubsub_topic" "notification_dlq" {
  name    = "notification-requests-dlq-${var.environment}"
  project = var.project_id
}

# ── Per-agent subscriptions ────────────────────────────────────────────────
locals {
  # Maps subscription name → agent service name (used to look up the SA in iam.tf)
  agent_subscriptions = {
    "coordinator-sub" = "coordinator-agent"
    "docs-agent-sub"  = "docs-agent"
    "medrecon-sub"    = "medrecon-agent"
    "bed-mgmt-sub"    = "bed-mgmt-agent"
    "followup-sub"    = "followup-agent"
    "comms-sub"       = "comms-agent"
  }
}

resource "google_pubsub_subscription" "agent_subs" {
  for_each = local.agent_subscriptions

  name    = "${each.key}-${var.environment}"
  topic   = google_pubsub_topic.adt_events.id
  project = var.project_id

  # Ordering enforced per-message via ordering_key set by the HL7 Listener publisher.
  enable_message_ordering = true

  ack_deadline_seconds       = 60 # Agents have 60 s to process and ack
  message_retention_duration = "604800s"
  retain_acked_messages      = false

  expiration_policy {
    ttl = "" # Never expire the subscription itself
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.adt_events_dlq.id
    max_delivery_attempts = 5 # TR-015: DLQ after 5 failures (6 total attempts)
  }
  # Note: flow_control (max_outstanding_messages = 100, max_outstanding_bytes = 100MB)
  # is configured on the Pub/Sub client SDK side, not in Terraform.
  # See services/shared/pubsub_client.py for the subscriber flow control settings.
}

# ── Notification subscription ───────────────────────────────────────────────
resource "google_pubsub_subscription" "notification_sub" {
  name    = "notification-sub-${var.environment}"
  topic   = google_pubsub_topic.notification_requests.id
  project = var.project_id

  ack_deadline_seconds       = 30
  message_retention_duration = "86400s"

  expiration_policy {
    ttl = ""
  }

  retry_policy {
    minimum_backoff = "5s"
    maximum_backoff = "60s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.notification_dlq.id
    max_delivery_attempts = 5
  }
}
