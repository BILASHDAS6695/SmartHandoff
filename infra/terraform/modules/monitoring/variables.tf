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
