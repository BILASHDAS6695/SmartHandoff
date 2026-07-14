variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region for Cloud Memorystore Redis instance"
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "vpc_id" {
  type        = string
  description = "VPC network self-link for Redis private IP (from networking module)"
}
