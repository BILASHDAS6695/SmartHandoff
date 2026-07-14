---
task_id: task_006
story_id: us_001
epic: EP-TECH
title: Cloud Storage Buckets — HL7 Archive, Audit WORM, ML Models, Angular CDN
layer: Storage
effort_hours: 1.5
sequence: 6
status: Implemented
---

# TASK-006: Cloud Storage Buckets — HL7 Archive, Audit WORM, ML Models, Angular CDN

> **Story:** EP-TECH/US-001 | **Layer:** Storage | **Effort:** 1.5 hours | **Seq:** 6 of 11

## Objective

Provision the four Cloud Storage buckets required by SmartHandoff: HL7 raw message archive (HIPAA CMEK + 7-year retention lock), audit log WORM export bucket (6-year retention lock), ML model artifacts, and Angular PWA static assets (CDN-served).

## Implementation Steps

### 1. CMEK for Storage (`modules/storage/main.tf`)

```hcl
# KMS key for Cloud Storage HIPAA buckets
resource "google_kms_crypto_key" "storage_cmek" {
  name            = "cloud-storage-cmek-${var.environment}"
  key_ring        = var.kms_key_ring_id
  rotation_period = "7776000s"  # 90-day rotation
  purpose         = "ENCRYPT_DECRYPT"
}
```

### 2. HL7 Archive Bucket (HIPAA — 7-year retention)

```hcl
resource "google_storage_bucket" "hl7_archive" {
  name          = "smarthandoff-hl7-archive-${var.project_id}-${var.environment}"
  location      = var.region
  project       = var.project_id
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  versioning { enabled = true }
  public_access_prevention = "enforced"

  encryption { default_kms_key_name = google_kms_crypto_key.storage_cmek.id }

  # 7-year retention lock (BR-022) — LOCKED after apply
  retention_policy {
    is_locked        = true
    retention_period = 220752000  # 7 years in seconds
  }

  lifecycle_rule {
    action   { type = "SetStorageClass"; storage_class = "NEARLINE" }
    condition { age = 90 }  # Move to Nearline after 90 days
  }

  lifecycle_rule {
    action   { type = "SetStorageClass"; storage_class = "COLDLINE" }
    condition { age = 365 }  # Move to Coldline after 1 year
  }
}
```

### 3. Audit WORM Bucket (6-year retention lock)

```hcl
resource "google_storage_bucket" "audit_export" {
  name          = "smarthandoff-audit-export-${var.project_id}-${var.environment}"
  location      = var.region
  project       = var.project_id
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  versioning { enabled = true }
  public_access_prevention = "enforced"

  encryption { default_kms_key_name = google_kms_crypto_key.storage_cmek.id }

  # 6-year immutable retention (BR-023)
  retention_policy {
    is_locked        = true
    retention_period = 189216000  # 6 years in seconds
  }

  lifecycle_rule {
    action   { type = "SetStorageClass"; storage_class = "COLDLINE" }
    condition { age = 180 }  # Move audit exports to Coldline after 6 months
  }
}
```

### 4. ML Model Artifacts Bucket

```hcl
resource "google_storage_bucket" "ml_models" {
  name          = "smarthandoff-ml-models-${var.project_id}-${var.environment}"
  location      = var.region
  project       = var.project_id
  storage_class = "STANDARD"

  uniform_bucket_level_access = true
  versioning { enabled = true }
  public_access_prevention = "enforced"

  # No retention lock — models are overwritten on retrain
  # Keep last 3 model versions via lifecycle
  lifecycle_rule {
    action    { type = "Delete" }
    condition {
      num_newer_versions = 3
      with_state         = "ARCHIVED"
    }
  }
}
```

### 5. Angular PWA Static Assets Bucket (CDN-served)

```hcl
resource "google_storage_bucket" "angular_pwa" {
  name          = "smarthandoff-pwa-${var.project_id}-${var.environment}"
  location      = "US"  # Multi-regional for CDN performance
  project       = var.project_id
  storage_class = "STANDARD"

  uniform_bucket_level_access = false  # Requires fine-grained for CDN allUsers read

  website {
    main_page_suffix = "index.html"
    not_found_page   = "index.html"  # SPA routing — return index.html for all paths
  }

  cors {
    origin          = ["https://*.smarthandoff.health"]
    method          = ["GET", "HEAD"]
    response_header = ["*"]
    max_age_seconds = 3600
  }
}

# Allow CDN to read Angular assets (public read)
resource "google_storage_bucket_iam_member" "pwa_public_read" {
  bucket = google_storage_bucket.angular_pwa.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}
```

### 6. IAM for Buckets

```hcl
# HL7 Listener service account: write to HL7 archive
resource "google_storage_bucket_iam_member" "hl7_archive_writer" {
  bucket = google_storage_bucket.hl7_archive.name
  role   = "roles/storage.objectCreator"  # Creator only — no delete
  member = "serviceAccount:${var.hl7_listener_sa}"
}

# Agent service accounts: read ML models at startup
resource "google_storage_bucket_iam_member" "ml_model_readers" {
  for_each = var.agent_service_accounts

  bucket = google_storage_bucket.ml_models.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${each.value}"
}

# API service account: write audit exports
resource "google_storage_bucket_iam_member" "audit_export_writer" {
  bucket = google_storage_bucket.audit_export.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${var.api_gateway_sa}"
}
```

### 7. Outputs

```hcl
output "hl7_archive_bucket"   { value = google_storage_bucket.hl7_archive.name }
output "audit_export_bucket"  { value = google_storage_bucket.audit_export.name }
output "ml_models_bucket"     { value = google_storage_bucket.ml_models.name }
output "angular_pwa_bucket"   { value = google_storage_bucket.angular_pwa.name }
output "pwa_bucket_url"       { value = google_storage_bucket.angular_pwa.url }
```

## Acceptance Criteria

- [ ] 4 buckets created: HL7 archive, audit export, ML models, Angular PWA
- [ ] HL7 archive: `gcloud storage buckets describe gs://smarthandoff-hl7-archive-...` shows `retentionPolicy.isLocked: true` and `retentionPolicy.retentionPeriod: "220752000"`
- [ ] Audit export: retention locked at 6 years; CMEK encryption confirmed
- [ ] ML models: versioning enabled; no retention lock
- [ ] Angular PWA: `website.mainPageSuffix: index.html`; `allUsers` has `objectViewer` role
- [ ] HL7 archive: HL7 Listener SA has `objectCreator` only (no `objectAdmin` — cannot delete)
- [ ] All HIPAA buckets: `publicAccessPrevention: enforced`

## Files to Create

```
infra/terraform/modules/storage/main.tf
infra/terraform/modules/storage/variables.tf
infra/terraform/modules/storage/outputs.tf
infra/terraform/modules/storage/iam.tf
infra/terraform/modules/storage/README.md
```

## Notes

- **Retention lock is irreversible** — once `is_locked = true` is applied to a bucket, it cannot be removed. Only apply to production; use `is_locked = false` for dev/staging to allow bucket deletion during testing
- `allUsers objectViewer` on Angular PWA bucket is intentional — Angular assets are public (non-PHI); API endpoints are protected by JWT
- Bucket names must be globally unique — using `{project_id}` in the name ensures uniqueness
- CMEK key for storage can reuse the key ring created in Task 004 (pass `kms_key_ring_id` as input variable)
