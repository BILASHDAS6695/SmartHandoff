variable "project_id" {
  type        = string
  description = "GCP project ID for production (e.g. smarthandoff-prod)"
}

variable "region" {
  type        = string
  description = "GCP region for all resources"
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Deployment environment identifier"
  default     = "prod"

  validation {
    condition     = var.environment == "prod"
    error_message = "This environment root is prod-only."
  }
}

variable "api_domain" {
  type        = string
  description = "Fully-qualified API domain"
}

variable "portal_domain" {
  type        = string
  description = "Fully-qualified patient portal domain"
}

variable "oncall_email" {
  type        = string
  description = "Email address for P1/P2 alert notifications"
}

variable "slack_alert_channel" {
  type        = string
  description = "Slack channel name for alert notifications"
  default     = "#smarthandoff-alerts"
}

variable "github_owner" {
  type        = string
  description = "GitHub organisation or user that owns the SmartHandoff repository"
}

variable "github_repo" {
  type        = string
  description = "GitHub repository name"
  default     = "SmartHandoff"
}

variable "org_id" {
  type        = string
  description = "GCP organisation ID — used for Cloud SCC SARIF upload in CI/CD pipeline"
}

variable "cloudbuild_sa_email" {
  type        = string
  description = "Cloud Build service account email — used to run pipeline and rollback trigger builds"
}

variable "compliance_officer_emails" {
  type        = list(string)
  description = "Email addresses of compliance officers granted read access to the PHI audit log GCS bucket"
  default     = []
}

