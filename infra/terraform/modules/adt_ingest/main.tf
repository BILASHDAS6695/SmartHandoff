# ─────────────────────────────────────────────────────────────────────────────
# SmartHandoff — ADT Ingest from FHIR — Cloud Run Job + Scheduler
#
# Provisions:
#   - google_service_account: dedicated SA for the ADT ingest job
#   - google_cloud_run_v2_job: scheduled job that polls FHIR and broadcasts ADT
#   - google_cloud_scheduler_job: cron trigger (default every 1 minute)
#
# Design refs:
#   US-022 / US-048 — Real-time dashboard ADT events
#   ADR-002         — Cloud Run stateless jobs for batch processing
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

resource "google_service_account" "adt_ingest" {
  project      = var.project_id
  account_id   = "sa-adt-ingest-${var.environment}"
  display_name = "SmartHandoff ADT Ingest Job SA (${var.environment})"
  description  = "Least-privilege SA for the FHIR ADT ingest Cloud Run job"
}

# Cloud SQL Client — if the job needs DB access for encounter enrichment
resource "google_project_iam_member" "adt_ingest_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.adt_ingest.email}"
}

# Secret Accessor — FHIR credentials, DB password, SignalR connection string
resource "google_secret_manager_secret_iam_member" "fhir_base_url" {
  project   = var.project_id
  secret_id = var.fhir_base_url_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.adt_ingest.email}"
}

resource "google_secret_manager_secret_iam_member" "fhir_client_id" {
  project   = var.project_id
  secret_id = var.fhir_client_id_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.adt_ingest.email}"
}

resource "google_secret_manager_secret_iam_member" "fhir_client_secret" {
  project   = var.project_id
  secret_id = var.fhir_client_secret_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.adt_ingest.email}"
}

resource "google_secret_manager_secret_iam_member" "db_password" {
  project   = var.project_id
  secret_id = var.db_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.adt_ingest.email}"
}

resource "google_secret_manager_secret_iam_member" "signalr_connection_string" {
  project   = var.project_id
  secret_id = var.signalr_connection_string_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.adt_ingest.email}"
}

# ── Cloud Run Job ─────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_job" "adt_ingest" {
  project  = var.project_id
  name     = "adt-ingest-${var.environment}"
  location = var.region

  template {
    template {
      service_account = google_service_account.adt_ingest.email

      # Cloud SQL connector
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.cloud_sql_connection_name]
        }
      }

      containers {
        image = var.container_image

        command = ["python", "-m", "app.jobs.run_adt_ingest"]

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
          name  = "AZURE_SIGNALR_HUB_NAME"
          value = "dashboard"
        }

        # Secret mounts
        volume_mounts {
          name       = "fhir-base-url"
          mount_path = "/secrets/fhir-base-url"
        }
        volume_mounts {
          name       = "fhir-client-id"
          mount_path = "/secrets/fhir-client-id"
        }
        volume_mounts {
          name       = "fhir-client-secret"
          mount_path = "/secrets/fhir-client-secret"
        }
        volume_mounts {
          name       = "db-password"
          mount_path = "/secrets/db-password"
        }
        volume_mounts {
          name       = "signalr-connection-string"
          mount_path = "/secrets/signalr-connection-string"
        }
      }

      # Secret volumes
      volumes {
        name = "fhir-base-url"
        secret {
          secret       = var.fhir_base_url_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "fhir-base-url"
          }
        }
      }

      volumes {
        name = "fhir-client-id"
        secret {
          secret       = var.fhir_client_id_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "fhir-client-id"
          }
        }
      }

      volumes {
        name = "fhir-client-secret"
        secret {
          secret       = var.fhir_client_secret_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "fhir-client-secret"
          }
        }
      }

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
        name = "signalr-connection-string"
        secret {
          secret       = var.signalr_connection_string_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "signalr-connection-string"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      timeout = "300s"
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
    ]
  }

  depends_on = [
    google_project_iam_member.adt_ingest_sql_client,
  ]
}

# ── Cloud Scheduler ───────────────────────────────────────────────────────────

resource "google_service_account" "scheduler_invoker" {
  project      = var.project_id
  account_id   = "sa-scheduler-adt-ingest-${var.environment}"
  display_name = "Cloud Scheduler → ADT Ingest Job Invoker SA (${var.environment})"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.adt_ingest.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "adt_ingest" {
  project     = var.project_id
  region      = var.region
  name        = "adt-ingest-${var.environment}"
  description = "Triggers the FHIR ADT ingest Cloud Run job every ${var.schedule}"
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
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.adt_ingest.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }
}
