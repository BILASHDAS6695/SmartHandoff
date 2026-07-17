---
id: TASK-004
title: "Terraform — Cloud Run Job, Cloud Scheduler Trigger & Secret Mounts"
user_story: US-062
epic: EP-012
sprint: 2
layer: IaC
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [TASK-003, US-001, DR-017]
---

# TASK-004: Terraform — Cloud Run Job, Cloud Scheduler Trigger & Secret Mounts

> **Story:** US-062 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** IaC | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

The export job container is built (TASK-001–003). This task provisions the GCP infrastructure required to run it on schedule:

- A `google_cloud_run_v2_job` resource for the nightly export container
- Secret Manager mounts for `db-password` and `deidentification-salt` (no plaintext env vars)
- A dedicated Cloud Run service account with least-privilege IAM bindings
- A `google_cloud_scheduler_job` configured for `0 2 * * *` UTC to invoke the Cloud Run job
- BigQuery dataset and IAM binding grants (`roles/bigquery.dataEditor`) scoped to `smarthandoff` dataset only

**Design references:**
- design.md §4.1 — Terraform 1.7+; GCP IaC; Cloud Run; Cloud Scheduler
- design.md ADR-002 — Cloud Run for stateless job compute
- US-062 DoD — Cloud Scheduler trigger `0 2 * * *` UTC
- design.md §8 — Least-privilege service accounts; Secret Manager mounts

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Cloud Scheduler triggers the Cloud Run job at 02:00 UTC |
| Scenario 4 | Cloud Run job failure (non-zero exit) surfaces as a failed job execution — monitored in TASK-005 |

---

## Implementation Steps

### 1. Add `bq_export` submodule under `infra/terraform/modules/`

```bash
mkdir -p infra/terraform/modules/bq_export
touch infra/terraform/modules/bq_export/main.tf
touch infra/terraform/modules/bq_export/variables.tf
touch infra/terraform/modules/bq_export/outputs.tf
touch infra/terraform/modules/bq_export/README.md
```

### 2. Implement `infra/terraform/modules/bq_export/main.tf`

```hcl
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
```

### 3. Implement `infra/terraform/modules/bq_export/variables.tf`

```hcl
variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "region" {
  type        = string
  description = "GCP region (e.g., us-central1)"
}

variable "container_image" {
  type        = string
  description = "Full container image URI for the bq-export Cloud Run job (e.g., gcr.io/project/bq-export:sha)"
}

variable "cloud_sql_connection_name" {
  type        = string
  description = "Cloud SQL instance connection name (project:region:instance)"
}

variable "db_name" {
  type        = string
  description = "PostgreSQL database name"
}

variable "db_user" {
  type        = string
  description = "PostgreSQL user name (non-sensitive; password from Secret Manager)"
}

variable "db_password_secret_id" {
  type        = string
  description = "Secret Manager secret ID for the database password"
}

variable "deidentification_salt_secret_id" {
  type        = string
  description = "Secret Manager secret ID for the monthly-rotated de-identification salt"
}
```

### 4. Implement `infra/terraform/modules/bq_export/outputs.tf`

```hcl
output "cloud_run_job_name" {
  description = "Name of the Cloud Run job resource"
  value       = google_cloud_run_v2_job.bq_export.name
}

output "bq_export_sa_email" {
  description = "Email of the BigQuery export Cloud Run job service account"
  value       = google_service_account.bq_export.email
}

output "bigquery_dataset_id" {
  description = "BigQuery dataset ID for the de-identified analytics dataset"
  value       = google_bigquery_dataset.smarthandoff.dataset_id
}

output "scheduler_job_name" {
  description = "Name of the Cloud Scheduler job that triggers the nightly export"
  value       = google_cloud_scheduler_job.bq_export_nightly.name
}
```

### 5. Wire the module into environment `main.tf` files

Add the following module call to `infra/terraform/environments/dev/main.tf` (and equivalently to `staging/main.tf` and `prod/main.tf`):

```hcl
module "bq_export" {
  source = "../../modules/bq_export"

  project_id                      = var.project_id
  environment                     = var.environment
  region                          = var.region
  container_image                 = var.bq_export_container_image
  cloud_sql_connection_name       = module.cloud_sql.connection_name
  db_name                         = var.db_name
  db_user                         = var.db_user
  db_password_secret_id           = module.cloud_sql.db_password_secret_id
  deidentification_salt_secret_id = var.deidentification_salt_secret_id
}
```

Add corresponding variables to `infra/terraform/environments/dev/variables.tf`:

```hcl
variable "bq_export_container_image" {
  type        = string
  description = "Full URI for the bq-export Cloud Run job container image"
}

variable "deidentification_salt_secret_id" {
  type        = string
  description = "Secret Manager ID for the monthly de-identification salt"
}
```

---

## Definition of Done

- [ ] `infra/terraform/modules/bq_export/` directory created with `main.tf`, `variables.tf`, `outputs.tf`, `README.md`
- [ ] `google_cloud_run_v2_job` resource mounts `db-password` and `deidentification-salt` as Secret Manager volumes — no plaintext secrets in env vars
- [ ] `google_cloud_scheduler_job` schedule is `"0 2 * * *"` with `time_zone = "UTC"` and 3 retry attempts
- [ ] `google_service_account.bq_export` IAM scoped to: `roles/cloudsql.client`, `roles/secretmanager.secretAccessor` (two secrets only), `roles/bigquery.dataEditor` (dataset-level), `roles/bigquery.jobUser`
- [ ] `google_bigquery_dataset` created with `delete_contents_on_destroy = false`
- [ ] Module wired into all three environment `main.tf` files
- [ ] `terraform validate` passes for all three environments
- [ ] `terraform plan` reviewed — no unintended changes to existing resources

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-003 | Task | Container image must be built and pushed before Cloud Run job references it |
| `cloud_sql` module | Module output | `connection_name`, `db_password_secret_id` consumed by `bq_export` module |
| US-001 | Story | BigQuery API (`bigquery.googleapis.com`) enabled via `environments/*/apis.tf` |

---

## Files Modified

| File | Action |
|---|---|
| `infra/terraform/modules/bq_export/main.tf` | Create — Cloud Run job, Scheduler, IAM, BigQuery dataset |
| `infra/terraform/modules/bq_export/variables.tf` | Create — module input variables |
| `infra/terraform/modules/bq_export/outputs.tf` | Create — module outputs |
| `infra/terraform/modules/bq_export/README.md` | Create — module documentation |
| `infra/terraform/environments/dev/main.tf` | Update — add `bq_export` module call |
| `infra/terraform/environments/dev/variables.tf` | Update — add `bq_export_container_image`, `deidentification_salt_secret_id` |
| `infra/terraform/environments/staging/main.tf` | Update — add `bq_export` module call |
| `infra/terraform/environments/staging/variables.tf` | Update — add variables |
| `infra/terraform/environments/prod/main.tf` | Update — add `bq_export` module call |
| `infra/terraform/environments/prod/variables.tf` | Update — add variables |
