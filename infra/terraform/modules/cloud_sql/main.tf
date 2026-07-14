data "google_project" "project" {
  project_id = var.project_id
}

# ── Cloud KMS — CMEK for Cloud SQL ──────────────────────────────────────────
resource "google_kms_key_ring" "sql_keyring" {
  name     = "smarthandoff-sql-${var.environment}"
  location = var.region
  project  = var.project_id
}

resource "google_kms_crypto_key" "sql_cmek" {
  name            = "cloud-sql-cmek-${var.environment}"
  key_ring        = google_kms_key_ring.sql_keyring.id
  rotation_period = "7776000s" # 90-day automatic rotation
  purpose         = "ENCRYPT_DECRYPT"

  lifecycle {
    prevent_destroy = true # Never accidentally destroy the key — data would be unrecoverable
  }
}

# Grant the Cloud SQL service agent permission to use the CMEK key
resource "google_kms_crypto_key_iam_member" "sql_cmek_access" {
  crypto_key_id = google_kms_crypto_key.sql_cmek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-cloud-sql.iam.gserviceaccount.com"
}

# ── Cloud SQL Primary Instance (HA) ───────────────────────────────────────
resource "google_sql_database_instance" "primary" {
  name             = "smarthandoff-pg-${var.environment}"
  database_version = "POSTGRES_15"
  region           = var.region
  project          = var.project_id

  encryption_key_name = google_kms_crypto_key.sql_cmek.id

  # Ensure the CMEK IAM binding exists before Cloud SQL tries to use the key.
  # The private services access peering (networking module) is enforced via
  # module depends_on in the environment root, not here.
  depends_on = [google_kms_crypto_key_iam_member.sql_cmek_access]

  settings {
    # Prod: 4 vCPU / 16 GB. Non-prod: 2 vCPU / 8 GB
    tier              = var.environment == "prod" ? "db-custom-4-16384" : "db-custom-2-8192"
    availability_type = "REGIONAL" # Multi-AZ HA — failover within 60s (NFR-022)
    disk_type         = "PD_SSD"
    disk_size         = 100
    disk_autoresize       = true
    disk_autoresize_limit = 500

    ip_configuration {
      ipv4_enabled                                  = false # Private IP only (SEC-005, AC-3)
      private_network                               = var.vpc_id
      enable_private_path_for_google_cloud_services = true
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true # Continuous WAL — RPO <15 min (NFR-023)

      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }

      transaction_log_retention_days = 7
      start_time                     = "02:00" # Daily snapshot at 02:00 UTC
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 2 # 02:00 UTC
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

  # Protect production from accidental terraform destroy
  deletion_protection = var.environment == "prod"
}

# ── Read Replica ────────────────────────────────────────────────────────────
resource "google_sql_database_instance" "read_replica" {
  name                 = "smarthandoff-pg-replica-${var.environment}"
  database_version     = "POSTGRES_15"
  region               = var.region
  project              = var.project_id
  master_instance_name = google_sql_database_instance.primary.name

  encryption_key_name = google_kms_crypto_key.sql_cmek.id

  replica_configuration {
    failover_target = false # Read replica, not HA failover replica
  }

  settings {
    tier              = var.environment == "prod" ? "db-custom-4-16384" : "db-custom-2-8192"
    availability_type = "ZONAL" # Zonal is sufficient for a read replica
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.vpc_id
    }
  }
}

# ── Application database and credentials ─────────────────────────────────────
resource "google_sql_database" "app_db" {
  name     = "smarthandoff"
  instance = google_sql_database_instance.primary.name
  project  = var.project_id
}

resource "random_password" "db_password" {
  length      = 32
  special     = true
  min_special = 2
  min_numeric = 2
  min_upper   = 2
}

resource "google_sql_user" "app_user" {
  name     = "smarthandoff_app"
  instance = google_sql_database_instance.primary.name
  password = random_password.db_password.result
  project  = var.project_id
}

# ── Store DB password in Secret Manager ────────────────────────────────────
resource "google_secret_manager_secret" "db_password" {
  secret_id = "smarthandoff-db-password-${var.environment}"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
    module      = "cloud_sql"
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db_password.result
}
