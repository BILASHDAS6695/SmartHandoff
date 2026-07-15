variable "project_id" {
  type        = string
  description = "GCP project ID for this environment (e.g. smarthandoff-staging)"
}

variable "region" {
  type        = string
  description = "GCP region for all resources"
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Deployment environment identifier: dev | staging | prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod"
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
