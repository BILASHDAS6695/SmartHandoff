---
id: TASK-005
title: "Implement PHI Redaction Log Exclusion Filter and Secure Audit Log Sink (Terraform)"
user_story: US-004
epic: EP-TECH
sprint: 1
layer: IaC
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001]
---

# TASK-005: Implement PHI Redaction Log Exclusion Filter and Secure Audit Log Sink (Terraform)

> **Story:** US-004 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** IaC | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-004 Acceptance Criterion 4 (Scenario 4) requires that PHI fields (patient name, MRN) are replaced with `[REDACTED]` in standard Cloud Logging exports, while a **secure sink** retains the original values with restricted IAM access for audit purposes.

The Technical Notes specify: *"PHI redaction: use Cloud Logging exclusion filters + log sink with Dataflow transform for secure audit copy"*.

This task provisions the Terraform infrastructure layer:

1. A **log exclusion filter** that prevents logs matching PHI JSON field keys from flowing into the default `_Default` log bucket (visible to general ops).
2. A **secure Cloud Storage sink** that captures all logs (including PHI-containing logs) into a dedicated GCS bucket accessible only to compliance/audit roles.
3. IAM bindings restricting access to the secure audit bucket.

> **Note:** The application-layer PHI redaction middleware (TASK-007) complements this IaC layer. The Terraform layer provides defence-in-depth for logs that bypass application-level redaction.

---

## Acceptance Criteria Addressed

| US-004 AC | Requirement |
|---|---|
| **Scenario 4** | Cloud Logging export shows PHI fields replaced with `[REDACTED]`; raw logs in secure sink retain original values with restricted IAM access |

---

## Implementation Steps

### 1. Create `monitoring/logging.tf`

Create a new file `infra/terraform/modules/monitoring/logging.tf` to isolate logging infrastructure:

```hcl
# ── Secure audit log GCS bucket ──────────────────────────────────────────────
resource "google_storage_bucket" "audit_logs" {
  project                     = var.project_id
  name                        = "smarthandoff-audit-logs-${var.environment}-${var.project_id}"
  location                    = "US"
  uniform_bucket_level_access = true
  force_destroy               = false

  retention_policy {
    is_locked        = true
    retention_period = 2555  # 7 years — HIPAA audit retention requirement
  }

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action { type = "SetStorageClass" storage_class = "COLDLINE" }
    condition { age = 90 }
  }

  labels = {
    environment     = var.environment
    data_class      = "phi-audit"
    managed_by      = "terraform"
    hipaa_compliant = "true"
  }
}

# ── Log sink — route ALL logs to secure audit bucket ────────────────────────
resource "google_logging_project_sink" "audit_sink" {
  project                = var.project_id
  name                   = "smarthandoff-audit-sink-${var.environment}"
  destination            = "storage.googleapis.com/${google_storage_bucket.audit_logs.name}"
  filter                 = ""  # Capture all log entries for compliance completeness
  unique_writer_identity = true

  depends_on = [google_storage_bucket.audit_logs]
}

# ── Grant the log sink service account write access to the audit bucket ──────
resource "google_storage_bucket_iam_member" "audit_sink_writer" {
  bucket = google_storage_bucket.audit_logs.name
  role   = "roles/storage.objectCreator"
  member = google_logging_project_sink.audit_sink.writer_identity
}

# ── Restrict audit bucket read access to compliance officers only ────────────
resource "google_storage_bucket_iam_member" "compliance_reader" {
  for_each = toset(var.compliance_officer_emails)

  bucket = google_storage_bucket.audit_logs.name
  role   = "roles/storage.objectViewer"
  member = "user:${each.value}"
}

# ── Log exclusion — prevent PHI fields from flowing into the _Default bucket ─
# This exclusion targets structured JSON logs containing known PHI field keys.
# The application-layer middleware (TASK-007) redacts these fields before logging;
# this exclusion is a defence-in-depth backstop for any log entries that escape
# application-level redaction.
resource "google_logging_project_exclusion" "phi_field_exclusion" {
  project     = var.project_id
  name        = "smarthandoff-phi-field-exclusion-${var.environment}"
  description = "Exclude log entries containing unredacted PHI field keys from the _Default log bucket. Defence-in-depth backstop alongside application-layer redaction middleware."

  # Exclude structured logs where ANY of the following PHI JSON payload keys
  # are present and non-empty. These match the field names used in the
  # SQLAlchemy ORM models and are the fields most likely to leak PHI.
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
```

### 2. Add `compliance_officer_emails` Variable to `monitoring/variables.tf`

```hcl
variable "compliance_officer_emails" {
  type        = list(string)
  description = "Email addresses of compliance officers granted read access to the PHI audit log bucket."
  default     = []
}
```

### 3. Export Audit Infrastructure Details in `monitoring/outputs.tf`

Append:

```hcl
output "audit_log_bucket_name" {
  description = "Name of the GCS bucket holding PHI audit logs."
  value       = google_storage_bucket.audit_logs.name
}

output "audit_log_sink_writer_identity" {
  description = "Service account identity used by the log sink to write to the audit bucket."
  value       = google_logging_project_sink.audit_sink.writer_identity
}
```

### 4. Wire `compliance_officer_emails` in Environment `main.tf` Files

Add to each environment's monitoring module block:

```hcl
module "monitoring" {
  # ...existing arguments from TASK-001...
  compliance_officer_emails = var.compliance_officer_emails
}
```

Add the variable declaration to each `environments/<env>/variables.tf`:

```hcl
variable "compliance_officer_emails" {
  type        = list(string)
  description = "List of compliance officer email addresses for PHI audit log access."
  default     = []
}
```

---

## Files Changed

| File | Action |
|---|---|
| `infra/terraform/modules/monitoring/logging.tf` | Create — audit bucket, log sink, IAM, exclusion filter |
| `infra/terraform/modules/monitoring/variables.tf` | Add `compliance_officer_emails` |
| `infra/terraform/modules/monitoring/outputs.tf` | Append audit bucket and sink writer outputs |
| `infra/terraform/environments/dev/main.tf` | Wire `compliance_officer_emails` |
| `infra/terraform/environments/dev/variables.tf` | Add `compliance_officer_emails` variable |
| `infra/terraform/environments/staging/main.tf` | Wire `compliance_officer_emails` |
| `infra/terraform/environments/staging/variables.tf` | Add `compliance_officer_emails` variable |
| `infra/terraform/environments/prod/main.tf` | Wire `compliance_officer_emails` |
| `infra/terraform/environments/prod/variables.tf` | Add `compliance_officer_emails` variable |

---

## Definition of Done

- [ ] `terraform validate` passes with `logging.tf`
- [ ] `terraform plan` shows GCS audit bucket, log sink, IAM binding, and log exclusion resources
- [ ] Audit bucket has `retention_policy.is_locked = true` and 7-year retention configured
- [ ] Log exclusion filter only excludes logs with unredacted PHI field keys — general ops logs remain visible in `_Default`
- [ ] `compliance_officer_emails` IAM binding applied; no other principals have `objectViewer` on the audit bucket
- [ ] `terraform output audit_log_bucket_name` returns expected bucket name
