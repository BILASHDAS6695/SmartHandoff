variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region for subnet and VPC connector"
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}
