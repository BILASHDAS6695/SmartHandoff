# monitoring/logging.tf
# HIPAA-compliant audit log sink and PHI field exclusion.
# Implemented by: EP-TECH / US-004 / TASK-005
#
# Resources:
#   - GCS audit log bucket (7-year locked retention, COLDLINE at 90 days)
#   - Log sink routing ALL project logs to the audit bucket
#   - IAM: log sink writer + per-officer reader grants
#   - Log exclusion: prevent unredacted PHI keys from reaching _Default bucket

# ── Audit log GCS bucket ─────────────────────────────────────────────────────
# Bucket name must be globally unique; use project-scoped naming convention.
resource "google_storage_bucket" "audit_logs" {
  project       = var.project_id
  name          = "smarthandoff-audit-logs-${var.environment}-${var.project_id}"
  location      = var.region
  storage_class = "STANDARD"

  # Prevent accidental deletion — data must be retained per HIPAA minimum 7 years
  force_destroy = false

  # Locked retention policy: once set, cannot be reduced without bucket deletion
  retention_policy {
    is_locked        = true
    retention_period = 220752000 # 7 years in seconds (7 × 365.25 × 24 × 3600)
  }

  versioning {
    enabled = true
  }

  # Move objects to COLDLINE storage after 90 days to reduce cost while
  # keeping the 7-year retention requirement satisfied.
  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
    condition {
      age = 90
    }
  }

  uniform_bucket_level_access = true

  labels = {
    environment     = var.environment
    data_class      = "phi-audit"
    managed_by      = "terraform"
    hipaa_compliant = "true"
  }
}

# ── Log sink — route ALL project logs to the secure audit bucket ─────────────
# filter = "" captures every log entry for compliance completeness.
# The PHI exclusion (below) prevents raw PHI from reaching the _Default bucket
# but does NOT exclude it from this sink — auditors need the full record.
resource "google_logging_project_sink" "audit_sink" {
  project                = var.project_id
  name                   = "smarthandoff-audit-sink-${var.environment}"
  destination            = "storage.googleapis.com/${google_storage_bucket.audit_logs.name}"
  filter                 = "" # All log entries
  unique_writer_identity = true

  depends_on = [google_storage_bucket.audit_logs]
}

# ── Grant the log sink service account write access to the audit bucket ──────
resource "google_storage_bucket_iam_member" "audit_sink_writer" {
  bucket = google_storage_bucket.audit_logs.name
  role   = "roles/storage.objectCreator"
  member = google_logging_project_sink.audit_sink.writer_identity
}

# ── Restrict audit bucket READ access to authorised compliance officers only ─
resource "google_storage_bucket_iam_member" "compliance_reader" {
  for_each = toset(var.compliance_officer_emails)

  bucket = google_storage_bucket.audit_logs.name
  role   = "roles/storage.objectViewer"
  member = "user:${each.value}"
}

# ── Log exclusion — backstop against unredacted PHI in the _Default bucket ───
# Application-layer PhiRedactionFilter (TASK-007) is the primary control.
# This exclusion is defence-in-depth: if any unredacted PHI escapes the
# application middleware it will be excluded from the _Default sink (which
# is visible to all project viewers) and will only land in the locked audit bucket.
resource "google_logging_project_exclusion" "phi_field_exclusion" {
  project     = var.project_id
  name        = "smarthandoff-phi-field-exclusion-${var.environment}"
  description = "Exclude Cloud Run logs containing known PHI JSON payload keys from the _Default log bucket. Defence-in-depth backstop alongside application-layer PhiRedactionFilter middleware."

  filter = <<-EOT
    resource.type="cloud_run_revision"
    AND (
      jsonPayload.patient_name!="" OR
      jsonPayload.first_name!="" OR
      jsonPayload.last_name!="" OR
      jsonPayload.mrn!="" OR
      jsonPayload.date_of_birth!="" OR
      jsonPayload.phone_number!="" OR
      jsonPayload.email_address!=""
    )
  EOT
}
