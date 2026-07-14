variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region for Cloud Run service deployments"
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector ID (output of networking module)"
}
