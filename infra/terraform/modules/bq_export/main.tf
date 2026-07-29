# ─────────────────────────────────────────────────────────────────────────────
# SmartHandoff — BigQuery Nightly Export — Cloud Run Job + Scheduler
#
# Provisions:
#   - google_service_account: dedicated SA for the export job (least privilege)
#   - google_bigquery_dataset: smarthandoff dataset (if not already existing)
#   - google_bigquery_dataset_iam_member: dataEditor on dataset only
#   - google_cloud_run_v2_job: nightly export Cloud Run job
#   - google_cloud_scheduler_job: cron trigger 0 2 * * * UTC
#
# Design refs:
#   design.md §4.1 — Terraform 1.7+; Cloud Run; Cloud Scheduler
#   US-062 DoD — Cloud Scheduler 0 2 * * * UTC; Secret Manager mounts
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

resource "google_service_account" "bq_export" {
  project      = var.project_id
  account_id   = "sa-bq-export-${var.environment}"
  display_name = "SmartHandoff BigQuery Export Job SA (${var.environment})"
  description  = "Least-privilege SA for the nightly de-identified encounter export job"
}

# Cloud SQL Client — connect to Cloud SQL read replica via Cloud SQL Proxy
resource "google_project_iam_member" "bq_export_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.bq_export.email}"
}

# Secret Accessor — db-password and deidentification-salt only
resource "google_secret_manager_secret_iam_member" "db_password" {
  project   = var.project_id
  secret_id = var.db_password_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bq_export.email}"
}

resource "google_secret_manager_secret_iam_member" "deidentification_salt" {
  project   = var.project_id
  secret_id = var.deidentification_salt_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bq_export.email}"
}

# ── BigQuery Dataset ──────────────────────────────────────────────────────────

resource "google_bigquery_dataset" "smarthandoff" {
  project    = var.project_id
  dataset_id = "smarthandoff"
  location   = var.region

  description = "SmartHandoff analytics dataset — de-identified encounter data (HIPAA Safe Harbor)"

  # Prevent accidental deletion of the analytics dataset
  delete_contents_on_destroy = false
}

resource "google_bigquery_dataset_iam_member" "bq_export_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.smarthandoff.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.bq_export.email}"
}

# BigQuery Job User — required to execute load jobs
resource "google_project_iam_member" "bq_export_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.bq_export.email}"
}

# ── Cloud Run Job ─────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_job" "bq_export" {
  project  = var.project_id
  name     = "bq-export-${var.environment}"
  location = var.region

  template {
    template {
      service_account = google_service_account.bq_export.email

      # Cloud SQL connector — mounts Cloud SQL socket for psycopg2 connection
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [var.cloud_sql_connection_name]
        }
      }

      containers {
        image = var.container_image

        # Non-sensitive runtime config via env vars
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

        # Secret mounts — secrets never exposed as plaintext env vars
        volume_mounts {
          name       = "db-password"
          mount_path = "/secrets/db-password"
        }
        volume_mounts {
          name       = "deidentification-salt"
          mount_path = "/secrets/deidentification-salt"
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
        name = "deidentification-salt"
        secret {
          secret       = var.deidentification_salt_secret_id
          default_mode = 0444
          items {
            version = "latest"
            path    = "deidentification-salt"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      timeout = "600s"  # 10-minute timeout; export should complete in <2min normally
    }
  }

  lifecycle {
    ignore_changes = [
      # Allow CI/CD to update container image without Terraform drift
      template[0].template[0].containers[0].image,
    ]
  }
}

# ── Cloud Scheduler ───────────────────────────────────────────────────────────

resource "google_service_account" "scheduler_invoker" {
  project      = var.project_id
  account_id   = "sa-scheduler-bq-export-${var.environment}"
  display_name = "Cloud Scheduler → Cloud Run Job Invoker SA (bq-export, ${var.environment})"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.bq_export.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "bq_export_nightly" {
  project     = var.project_id
  region      = var.region
  name        = "bq-export-nightly-${var.environment}"
  description = "Triggers the nightly BigQuery de-identified encounter export at 02:00 UTC"
  schedule    = "0 2 * * *"
  time_zone   = "UTC"

  # Retry config: 3 attempts with exponential backoff for transient failures
  retry_config {
    retry_count          = 3
    min_backoff_duration = "30s"
    max_backoff_duration = "300s"
    max_doublings        = 3
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.bq_export.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }
}
