---
task_id: task_005
story_id: us_001
epic: EP-TECH
title: GCP Pub/Sub — Topics, Subscriptions, and Dead Letter Queues
layer: Messaging
effort_hours: 1.5
sequence: 5
status: Implemented
---

# TASK-005: GCP Pub/Sub — Topics, Subscriptions, and Dead Letter Queues

> **Story:** EP-TECH/US-001 | **Layer:** Messaging | **Effort:** 1.5 hours | **Seq:** 5 of 11

## Objective

Provision the `pubsub` Terraform module that creates the `adt-events` main topic, per-agent subscriptions with ordering enabled, Dead Letter Queues for each subscription, and the `notification-requests` topic used by the Notification Service.

## Implementation Steps

### 1. Topics (`modules/pubsub/main.tf`)

```hcl
# Main ADT events topic
resource "google_pubsub_topic" "adt_events" {
  name    = "adt-events-${var.environment}"
  project = var.project_id

  message_ordering = false  # Ordering enforced via subscription ordering_key, not topic-level

  message_retention_duration = "604800s"  # 7 days retention
}

# Dead Letter Topic for failed agent messages
resource "google_pubsub_topic" "adt_events_dlq" {
  name    = "adt-events-dlq-${var.environment}"
  project = var.project_id
  message_retention_duration = "604800s"
}

# Notification requests topic
resource "google_pubsub_topic" "notification_requests" {
  name    = "notification-requests-${var.environment}"
  project = var.project_id
  message_retention_duration = "86400s"  # 24 hours
}

resource "google_pubsub_topic" "notification_dlq" {
  name    = "notification-requests-dlq-${var.environment}"
  project = var.project_id
}
```

### 2. Per-Agent Subscriptions with DLQ

```hcl
locals {
  agent_subscriptions = {
    "coordinator-sub"  = "coordinator-agent"
    "docs-agent-sub"   = "docs-agent"
    "medrecon-sub"     = "medrecon-agent"
    "bed-mgmt-sub"     = "bed-mgmt-agent"
    "followup-sub"     = "followup-agent"
    "comms-sub"        = "comms-agent"
  }
}

resource "google_pubsub_subscription" "agent_subs" {
  for_each = local.agent_subscriptions

  name    = "${each.key}-${var.environment}"
  topic   = google_pubsub_topic.adt_events.id
  project = var.project_id

  enable_message_ordering = true

  ack_deadline_seconds       = 60   # 60s for agent processing
  message_retention_duration = "604800s"
  retain_acked_messages      = false

  expiration_policy { ttl = "" }  # Never expire

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.adt_events_dlq.id
    max_delivery_attempts = 5  # DLQ after 5 failures — TR-015
  }

  # Flow control to prevent agent overload
  flow_control {
    max_outstanding_messages = 100
    max_outstanding_bytes    = 104857600  # 100MB
  }
}
```

### 3. Notification Subscription

```hcl
resource "google_pubsub_subscription" "notification_sub" {
  name    = "notification-sub-${var.environment}"
  topic   = google_pubsub_topic.notification_requests.id
  project = var.project_id

  ack_deadline_seconds       = 30
  message_retention_duration = "86400s"

  retry_policy {
    minimum_backoff = "5s"
    maximum_backoff = "60s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.notification_dlq.id
    max_delivery_attempts = 5
  }
}
```

### 4. IAM — Cloud Run Service Accounts Can Publish/Subscribe

```hcl
# HL7 Listener service account can publish to adt-events
resource "google_pubsub_topic_iam_member" "hl7_publisher" {
  topic   = google_pubsub_topic.adt_events.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.hl7_listener_sa}"
  project = var.project_id
}

# Each agent service account subscribes to its own subscription
resource "google_pubsub_subscription_iam_member" "agent_subscribers" {
  for_each = local.agent_subscriptions

  subscription = google_pubsub_subscription.agent_subs[each.key].name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${var.agent_service_accounts[each.value]}"
  project      = var.project_id
}

# Pub/Sub service account needs DLQ publisher permission
resource "google_pubsub_topic_iam_member" "pubsub_dlq_publisher" {
  topic   = google_pubsub_topic.adt_events_dlq.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  project = var.project_id
}

# Agents can publish to notification-requests
resource "google_pubsub_topic_iam_member" "agents_notification_publisher" {
  topic   = google_pubsub_topic.notification_requests.name
  role    = "roles/pubsub.publisher"
  member  = "allServiceAccounts"  # Scope further per agent SA in production
  project = var.project_id
}
```

### 5. Outputs

```hcl
output "adt_events_topic_id"            { value = google_pubsub_topic.adt_events.id }
output "adt_events_dlq_topic_id"        { value = google_pubsub_topic.adt_events_dlq.id }
output "notification_requests_topic_id" { value = google_pubsub_topic.notification_requests.id }
output "agent_subscription_ids"         { value = { for k, v in google_pubsub_subscription.agent_subs : k => v.id } }
```

## Acceptance Criteria

- [ ] `terraform apply` creates: 4 topics (adt-events, adt-events-dlq, notification-requests, notification-dlq) + 7 subscriptions (6 agent + 1 notification)
- [ ] Each agent subscription has `deadLetterPolicy.maxDeliveryAttempts: 5` — confirmed via `gcloud pubsub subscriptions describe coordinator-sub-dev --format=json | jq '.deadLetterPolicy'`
- [ ] `enable_message_ordering: true` on all agent subscriptions
- [ ] Pub/Sub DLQ publisher IAM binding exists for Pub/Sub service account on DLQ topic
- [ ] HL7 Listener service account has `pubsub.publisher` role on `adt-events` topic
- [ ] Integration test (Task 011 CI): publish a test message to `adt-events-dev` → verify delivery to `coordinator-sub-dev` → ACK → zero undelivered messages

## Files to Create

```
infra/terraform/modules/pubsub/main.tf
infra/terraform/modules/pubsub/variables.tf
infra/terraform/modules/pubsub/outputs.tf
infra/terraform/modules/pubsub/iam.tf
infra/terraform/modules/pubsub/README.md
```

## Notes

- `max_delivery_attempts = 5` on DLQ policy means a message will be attempted 1 + 5 = 6 times total before going to DLQ
- Pub/Sub DLQ requires the Pub/Sub service agent (not application SA) to have publisher access on the DLQ topic — this is a common misconfiguration
- `flow_control.max_outstanding_messages = 100` prevents agents from being overwhelmed during event bursts
- `message_retention_duration = "604800s"` (7 days) allows replay of any ADT event within 7 days for audit or re-processing
