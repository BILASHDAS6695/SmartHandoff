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

variable "secret_names" {
  type        = map(string)
  description = "Map of logical secret name → Secret Manager secret_id (short name). Passed from the secrets module output. Defaults to {} so cloud_run can be applied before the secrets module on first bootstrapping apply."
  default     = {}
}
