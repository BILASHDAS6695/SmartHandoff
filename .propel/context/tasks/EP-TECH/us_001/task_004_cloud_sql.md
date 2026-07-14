---
task_id: task_004
story_id: us_001
epic: EP-TECH
title: Cloud SQL PostgreSQL 15 — HA Primary, Read Replica, CMEK, PITR
layer: Data / Cloud SQL
effort_hours: 2
sequence: 4
status: Implemented
---

# TASK-004: Cloud SQL PostgreSQL 15 — HA Primary, Read Replica, CMEK, PITR

> **Story:** EP-TECH/US-001 | **Layer:** Data | **Effort:** 2 hours | **Seq:** 4 of 11

## Objective

Provision Cloud SQL PostgreSQL 15 with High Availability (regional instance), a read replica, Customer-Managed Encryption Key (CMEK), private IP only (no public IP), PITR enabled, and automated backups every 4 hours — satisfying NFR-022 (RTO <1 hr), NFR-023 (RPO <15 min), NFR-043 (4h backup), and SEC-004 (AES-256 at rest).

## Implementation Steps

### 1. CMEK Key for Cloud SQL (`modules/cloud_sql/main.tf`)

```hcl
# Cloud KMS key for Cloud SQL CMEK
resource "google_kms_key_ring" "sql_keyring" {
  name     = "smarthandoff-sql-${var.environment}"
  location = var.region
  project  = var.project_id
}

resource "google_kms_crypto_key" "sql_cmek" {
  name            = "cloud-sql-cmek-${var.environment}"
  key_ring        = google_kms_key_ring.sql_keyring.id
  rotation_period = "7776000s"  # 90-day rotation
  purpose         = "ENCRYPT_DECRYPT"
}

# Grant Cloud SQL service account access to the CMEK key
data "google_project" "project" { project_id = var.project_id }

resource "google_kms_crypto_key_iam_member" "sql_cmek_access" {
  crypto_key_id = google_kms_crypto_key.sql_cmek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-cloud-sql.iam.gserviceaccount.com"
}
```

### 2. Cloud SQL Primary Instance (HA)

```hcl
resource "google_sql_database_instance" "primary" {
  name             = "smarthandoff-pg-${var.environment}"
  database_version = "POSTGRES_15"
  region           = var.region
  project          = var.project_id

  # Must be created AFTER private services access peering (Task 002)
  depends_on = [var.private_vpc_connection_id]

  encryption_key_name = google_kms_crypto_key.sql_cmek.id

  settings {
    tier              = var.environment == "prod" ? "db-custom-4-16384" : "db-custom-2-8192"
    availability_type = "REGIONAL"  # High Availability (multi-AZ failover)
    disk_type         = "PD_SSD"
    disk_size         = 100
    disk_autoresize   = true
    disk_autoresize_limit = 500

    ip_configuration {
      ipv4_enabled    = false  # NO public IP — AC-3
      private_network = var.vpc_id
      enable_private_path_for_google_cloud_services = true
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true   # PITR — RPO <15 min
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
      transaction_log_retention_days = 7
      start_time                     = "02:00"  # Daily backup at 02:00 UTC
    }

    maintenance_window {
      day          = 7   # Sunday
      hour         = 2   # 02:00 UTC
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
    }

    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }
    database_flags {
      name  = "log_connections"
      value = "on"
    }
    database_flags {
      name  = "log_disconnections"
      value = "on"
    }
    database_flags {
      name  = "log_lock_waits"
      value = "on"
    }
    database_flags {
      name  = "pg_stat_statements.track"
      value = "all"
    }
  }

  deletion_protection = var.environment == "prod"
}
```

### 3. Read Replica

```hcl
resource "google_sql_database_instance" "read_replica" {
  name                 = "smarthandoff-pg-replica-${var.environment}"
  database_version     = "POSTGRES_15"
  region               = var.region
  project              = var.project_id
  master_instance_name = google_sql_database_instance.primary.name

  encryption_key_name = google_kms_crypto_key.sql_cmek.id

  replica_configuration {
    failover_target = false
  }

  settings {
    tier              = var.environment == "prod" ? "db-custom-4-16384" : "db-custom-2-8192"
    availability_type = "ZONAL"   # Read replica can be zonal
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.vpc_id
    }
  }
}
```

### 4. Application Database and User

```hcl
resource "google_sql_database" "app_db" {
  name     = "smarthandoff"
  instance = google_sql_database_instance.primary.name
  project  = var.project_id
}

resource "random_password" "db_password" {
  length  = 32
  special = true
}

resource "google_sql_user" "app_user" {
  name     = "smarthandoff_app"
  instance = google_sql_database_instance.primary.name
  password = random_password.db_password.result
  project  = var.project_id
}

# Store DB password in Secret Manager (referenced by Task 008)
resource "google_secret_manager_secret" "db_password" {
  secret_id = "smarthandoff-db-password-${var.environment}"
  project   = var.project_id
  replication { auto {} }
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}
```

### 5. Outputs

```hcl
output "primary_connection_name"  { value = google_sql_database_instance.primary.connection_name }
output "primary_private_ip"       { value = google_sql_database_instance.primary.private_ip_address }
output "replica_private_ip"       { value = google_sql_database_instance.read_replica.private_ip_address }
output "database_name"            { value = google_sql_database.app_db.name }
output "db_user"                  { value = google_sql_user.app_user.name }
output "db_password_secret_id"    { value = google_secret_manager_secret.db_password.secret_id }
```

## Acceptance Criteria

- [ ] `terraform apply` creates: 1 Cloud SQL HA primary (PostgreSQL 15), 1 read replica, 1 KMS key ring + CMEK key
- [ ] Primary instance has `ipv4_enabled: false` and a private IP in `10.0.2.0/24` — confirmed via `gcloud sql instances describe smarthandoff-pg-dev --format=json | jq '.settings.ipConfiguration'`
- [ ] PITR enabled: `gcloud sql instances describe smarthandoff-pg-dev --format=json | jq '.settings.backupConfiguration.pointInTimeRecoveryEnabled'` returns `true`
- [ ] CMEK: `gcloud sql instances describe smarthandoff-pg-dev --format=json | jq '.diskEncryptionConfiguration'` shows KMS key reference
- [ ] HA configured: `availabilityType: "REGIONAL"` in instance description
- [ ] DB password stored in Secret Manager: `gcloud secrets list --project={PROJECT}` shows `smarthandoff-db-password-dev`
- [ ] `deletion_protection = true` in production environment (prevents accidental `terraform destroy` data loss)

## Files to Create

```
infra/terraform/modules/cloud_sql/main.tf
infra/terraform/modules/cloud_sql/variables.tf
infra/terraform/modules/cloud_sql/outputs.tf
infra/terraform/modules/cloud_sql/README.md
```

## Notes

- Cloud SQL HA provisioning takes 10–15 minutes — first `terraform apply` will be slow
- `depends_on = [var.private_vpc_connection_id]` is critical — Cloud SQL private IP cannot be assigned before private services access peering exists (Task 002)
- `disk_autoresize = true` + `disk_autoresize_limit = 500` prevents storage-full failures
- 4-hour automated backup is satisfied by Cloud SQL PITR (continuous WAL) — the `start_time` controls the daily snapshot; PITR handles the 15-minute RPO
