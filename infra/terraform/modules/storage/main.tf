# ── Storage CMEK key (reuses Cloud SQL KMS key ring) ───────────────────────
resource "google_kms_crypto_key" "storage_cmek" {
  name            = "cloud-storage-cmek-${var.environment}"
  key_ring        = var.kms_key_ring_id
  rotation_period = "7776000s" # 90-day automatic rotation
  purpose         = "ENCRYPT_DECRYPT"

  lifecycle {
    prevent_destroy = true
  }
}

# Grant the Cloud Storage service agent access to the CMEK key
data "google_project" "project" {
  project_id = var.project_id
}

resource "google_kms_crypto_key_iam_member" "storage_cmek_access" {
  crypto_key_id = google_kms_crypto_key.storage_cmek.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.project.number}@gs-project-accounts.iam.gserviceaccount.com"
}

# ── HL7 Archive Bucket (HIPAA — 7-year retention) ────────────────────────
resource "google_storage_bucket" "hl7_archive" {
  name          = "smarthandoff-hl7-archive-${var.project_id}-${var.environment}"
  location      = var.region
  project       = var.project_id
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced" # HIPAA: no public access

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.storage_cmek.id
  }

  # 7-year retention — locked in prod only (irreversible; use false for dev/staging)
  retention_policy {
    is_locked        = var.environment == "prod"
    retention_period = 220752000 # 7 years in seconds (BR-022)
  }

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age = 90 # Move to Nearline after 90 days
    }
  }

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
    condition {
      age = 365 # Move to Coldline after 1 year
    }
  }

  depends_on = [google_kms_crypto_key_iam_member.storage_cmek_access]
}

# ── Audit WORM Bucket (6-year retention) ─────────────────────────────────
resource "google_storage_bucket" "audit_export" {
  name          = "smarthandoff-audit-export-${var.project_id}-${var.environment}"
  location      = var.region
  project       = var.project_id
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.storage_cmek.id
  }

  # 6-year retention — locked in prod only (BR-023)
  retention_policy {
    is_locked        = var.environment == "prod"
    retention_period = 189216000 # 6 years in seconds
  }

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
    condition {
      age = 180 # Audit exports to Coldline after 6 months
    }
  }

  depends_on = [google_kms_crypto_key_iam_member.storage_cmek_access]
}

# ── ML Model Artifacts Bucket ──────────────────────────────────────────────
resource "google_storage_bucket" "ml_models" {
  name          = "smarthandoff-ml-models-${var.project_id}-${var.environment}"
  location      = var.region
  project       = var.project_id
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true # Enables model version history
  }

  # Keep last 3 model versions; delete older archived versions automatically
  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      num_newer_versions = 3
      with_state         = "ARCHIVED"
    }
  }
}

# ── Angular PWA Static Assets Bucket (CDN-served) ─────────────────────────
resource "google_storage_bucket" "angular_pwa" {
  name          = "smarthandoff-pwa-${var.project_id}-${var.environment}"
  location      = "US" # Multi-regional for Cloud CDN global performance
  project       = var.project_id
  storage_class = "STANDARD"

  # Bucket-level IAM is used for the CDN allUsers grant —
  # uniform_bucket_level_access = true works with bucket IAM bindings.
  uniform_bucket_level_access = true

  website {
    main_page_suffix = "index.html"
    not_found_page   = "index.html" # Angular SPA: all paths return index.html
  }

  cors {
    origin          = ["https://*.smarthandoff.health"]
    method          = ["GET", "HEAD"]
    response_header = ["*"]
    max_age_seconds = 3600
  }
}
