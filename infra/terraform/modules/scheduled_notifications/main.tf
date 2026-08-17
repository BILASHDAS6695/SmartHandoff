# ─────────────────────────────────────────────────────────────────────────────
# SmartHandoff — Scheduled Notification Dispatcher — Cloud Run Job + Scheduler
#
# Provisions:
#   - google_service_account: dedicated SA for the dispatcher job
#   - google_cloud_run_v2_job: scheduled job that polls scheduled_notification
#   - google_cloud_scheduler_job: cron trigger (default every 1 minute)
#
# Design refs:
#   US-041 / US-067 — scheduled patient notifications and opt-out
#   ADR-002         — Cloud Run stateless jobs for batch processing
#   TR-011          — Cloud Scheduler cron triggers
# ─────────────────────────────────────────────────────────────────────────────

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# ── Service Account ───────────────────────────────────────────────────────────

resource "google_service_account" "scheduled_notifications" {
  project      = var.project_id
  account_id   = "sa-scheduled-notif-${var.environment}"
  display_name = "SmartHandoff Scheduled Notification Dispatcher SA (${var.environment})"
  description  = "Least-privilege SA for the scheduled notification dispatcher Cloud Run job"
}

# Cloud SQL Client — DB access for polling scheduled_notification
resource "google_project_iam_member" "scheduled_notifications_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

# Pub/Sub Publisher — publishes to notification-requests topic
resource "google_project_iam_member" "scheduled_notifications_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

# Secret Accessor — DB password, PHI encryption key, Twilio/SendGrid credentials
resource "google_secret_manager_secret_iam_member" "db_password" {
  project   = var.project_id
  secret_id = var.db_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

resource "google_secret_manager_secret_iam_member" "phi_encryption_key" {
  project   = var.project_id
  secret_id = var.phi_encryption_key_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

resource "google_secret_manager_secret_iam_member" "twilio_account_sid" {
  project   = var.project_id
  secret_id = var.twilio_account_sid_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

resource "google_secret_manager_secret_iam_member" "twilio_auth_token" {
  project   = var.project_id
  secret_id = var.twilio_auth_token_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

resource "google_secret_manager_secret_iam_member" "twilio_phone_number" {
  project   = var.project_id
  secret_id = var.twilio_phone_number_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

resource "google_secret_manager_secret_iam_member" "twilio_verify_service_sid" {
  project   = var.project_id
  secret_id = var.twilio_verify_service_sid_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

resource "google_secret_manager_secret_iam_member" "sendgrid_api_key" {
  project   = var.project_id
  secret_id = var.sendgrid_api_key_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

resource "google_secret_manager_secret_iam_member" "sendgrid_from_email" {
  project   = var.project_id
  secret_id = var.sendgrid_from_email_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scheduled_notifications.email}"
}

# ── Cloud Run Job ─────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_job" "scheduled_notifications" {
  project  = var.project_id
  name     = "scheduled-notifications-${var.environment}"
  location = var.region

  template {
    template {
      service_account = google_service_account.scheduled_notifications.email

      # Cloud SQL connector
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.cloud_sql_connection_name]
        }
      }

      containers {
        image = var.container_image

        command = ["python", "-m", "app.jobs.dispatch_scheduled_notifications"]

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "DB_NAME"
          value = var.db_name
        }
        env {
          name  = "DB_USER"
          value = var.db_user
        }
        env {
          name  = "DB_HOST"
          value = "/cloudsql/${var.cloud_sql_connection_name}"
        }
        env {
          name  = "NOTIFICATION_TOPIC_ID"
          value = "notification-requests"
        }

        # Secret mounts — secrets never exposed as plaintext env vars
        volume_mounts {
          name       = "db-password"
          mount_path = "/secrets/db-password"
        }
        volume_mounts {
          name       = "phi-encryption-key"
          mount_path = "/secrets/phi-encryption-key"
        }
        volume_mounts {
          name       = "twilio-account-sid"
          mount_path = "/secrets/twilio-account-sid"
        }
        volume_mounts {
          name       = "twilio-auth-token"
          mount_path = "/secrets/twilio-auth-token"
        }
        volume_mounts {
          name       = "twilio-phone-number"
          mount_path = "/secrets/twilio-phone-number"
        }
        volume_mounts {
          name       = "twilio-verify-service-sid"
          mount_path = "/secrets/twilio-verify-service-sid"
        }
        volume_mounts {
          name       = "sendgrid-api-key"
          mount_path = "/secrets/sendgrid-api-key"
        }
        volume_mounts {
          name       = "sendgrid-from-email"
          mount_path = "/secrets/sendgrid-from-email"
        }

        # Cloud SQL connector mount
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }

      # Secret volumes
      volumes {
        name = "db-password"
        secret {
          secret       = var.db_password_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "db-password"
          }
        }
      }

      volumes {
        name = "phi-encryption-key"
        secret {
          secret       = var.phi_encryption_key_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "phi-encryption-key"
          }
        }
      }

      volumes {
        name = "twilio-account-sid"
        secret {
          secret       = var.twilio_account_sid_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "twilio-account-sid"
          }
        }
      }

      volumes {
        name = "twilio-auth-token"
        secret {
          secret       = var.twilio_auth_token_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "twilio-auth-token"
          }
        }
      }

      volumes {
        name = "twilio-phone-number"
        secret {
          secret       = var.twilio_phone_number_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "twilio-phone-number"
          }
        }
      }

      volumes {
        name = "twilio-verify-service-sid"
        secret {
          secret       = var.twilio_verify_service_sid_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "twilio-verify-service-sid"
          }
        }
      }

      volumes {
        name = "sendgrid-api-key"
        secret {
          secret       = var.sendgrid_api_key_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "sendgrid-api-key"
          }
        }
      }

      volumes {
        name = "sendgrid-from-email"
        secret {
          secret       = var.sendgrid_from_email_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "sendgrid-from-email"
          }
        }
      }

      timeout = "${var.timeout_seconds}s"
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
  }

  depends_on = [
    google_project_iam_member.scheduled_notifications_sql_client,
    google_project_iam_member.scheduled_notifications_pubsub_publisher,
  ]
}

# ── Cloud Scheduler ───────────────────────────────────────────────────────────

resource "google_service_account" "scheduler_invoker" {
  project      = var.project_id
  account_id   = "sa-scheduler-notif-${var.environment}"
  display_name = "Cloud Scheduler → Scheduled Notifications Job Invoker SA (${var.environment})"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.scheduled_notifications.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "scheduled_notifications" {
  project     = var.project_id
  region      = var.region
  name        = "scheduled-notifications-${var.environment}"
  description = "Triggers the scheduled notification dispatcher Cloud Run job every ${var.schedule}"
  schedule    = var.schedule
  time_zone   = "UTC"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "60s"
    max_doublings        = 3
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.scheduled_notifications.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }
}
