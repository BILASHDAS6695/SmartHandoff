# pubsub module

Provisions all Pub/Sub topics, per-agent subscriptions with Dead Letter Queues,
the notification-requests topic, and the corresponding IAM bindings.

## Topics

| Topic | Retention | Purpose |
|-------|-----------|---------|
| `adt-events-{env}` | 7 days | ADT events from HL7 Listener → agents |
| `adt-events-dlq-{env}` | 7 days | Dead letters from failed agent deliveries |
| `notification-requests-{env}` | 24 hours | Notification dispatch requests from agents |
| `notification-requests-dlq-{env}` | — | Dead letters from failed notification delivery |

## Subscriptions

| Subscription | Topic | Ordering | DLQ After | Consumer SA |
|-------------|-------|----------|-----------|-------------|
| `coordinator-sub-{env}` | adt-events | ✓ | 5 attempts | `coordinator-agent` SA |
| `docs-agent-sub-{env}` | adt-events | ✓ | 5 attempts | `docs-agent` SA |
| `medrecon-sub-{env}` | adt-events | ✓ | 5 attempts | `medrecon-agent` SA |
| `bed-mgmt-sub-{env}` | adt-events | ✓ | 5 attempts | `bed-mgmt-agent` SA |
| `followup-sub-{env}` | adt-events | ✓ | 5 attempts | `followup-agent` SA |
| `comms-sub-{env}` | adt-events | ✓ | 5 attempts | `comms-agent` SA |
| `notification-sub-{env}` | notification-requests | ✗ | 5 attempts | `notification-svc` SA |

## Inputs

| Name | Type | Description |
|------|------|-------------|
| `project_id` | `string` | GCP project ID |
| `environment` | `string` | `dev` \| `staging` \| `prod` |
| `project_number` | `string` | Numeric project number (for Pub/Sub service agent IAM) |
| `hl7_listener_sa` | `string` | HL7 Listener service account email |
| `agent_service_accounts` | `map(string)` | Map of agent name → service account email (from cloud_run module) |

## Outputs

| Name | Description |
|------|-------------|
| `adt_events_topic_id` | adt-events topic ID (env var for HL7 Listener) |
| `adt_events_topic_name` | adt-events topic short name |
| `adt_events_dlq_topic_id` | DLQ topic ID |
| `notification_requests_topic_id` | notification-requests topic ID |
| `notification_requests_topic_name` | notification-requests topic short name |
| `agent_subscription_ids` | Map of subscription name → ID |
| `notification_subscription_id` | Notification service subscription ID |

## Critical IAM Note

The Pub/Sub **service agent** (`service-{PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com`)
must have `roles/pubsub.publisher` on the DLQ topics. Without this binding, dead-letter routing
silently fails and messages are dropped after `max_delivery_attempts`. This is provisioned in
`iam.tf` as `pubsub_dlq_publisher` and `pubsub_notification_dlq_publisher`.

## Flow Control

Client-side flow control (`max_outstanding_messages = 100`, `max_outstanding_bytes = 100MB`)
is configured in the Python SDK subscriber, not in Terraform. See `services/shared/pubsub_client.py`.
