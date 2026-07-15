variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region for Cloud SQL instances"
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "vpc_id" {
  type        = string
  description = "VPC network self-link for Cloud SQL private IP (from networking module)"
}
