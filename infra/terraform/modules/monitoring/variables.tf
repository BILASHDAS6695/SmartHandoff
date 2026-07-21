variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "project_number" {
  type        = string
  description = "Numeric GCP project number — used for Cloud Monitoring service agent IAM binding"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "region" {
  type        = string
  description = "GCP region (used for Cloud Build rollback trigger substitutions)"
  default     = "us-central1"
}

variable "api_domain" {
  type        = string
  description = "Fully-qualified API domain (used by uptime check monitors)"
}

variable "oncall_email" {
  type        = string
  description = "Email address for alert notifications"
}

variable "slack_alert_channel" {
  type        = string
  description = "Slack channel name for alert notifications"
  default     = "#smarthandoff-alerts"
}

variable "cloudbuild_sa_email" {
  type        = string
  description = "Cloud Build service account email — used to run rollback trigger builds"
}

variable "pagerduty_integration_key" {
  type        = string
  description = "PagerDuty Events API v2 service integration key for P1/P2 alert routing. Sourced from Secret Manager — do not pass a plain-text value."
  sensitive   = true
  default     = ""

  validation {
    # Reject an empty key in staging and prod environments; dev may omit it.
    condition     = !(contains(["staging", "prod"], var.environment) && var.pagerduty_integration_key == "")
    error_message = "pagerduty_integration_key must not be empty in staging or prod environments. Ensure the Secret Manager secret 'smarthandoff-pagerduty-integration-key-<env>' exists and has an active version."
  }
}

variable "compliance_officer_emails" {
  type        = list(string)
  description = "Email addresses of compliance officers granted read access to the PHI audit log bucket"
  default     = []
}
