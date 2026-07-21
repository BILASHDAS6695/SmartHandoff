variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "region" {
  type        = string
  description = "GCP region for secret replication"
}

variable "kms_key_id" {
  type        = string
  description = "Cloud KMS crypto key ID used to CMEK-encrypt Secret Manager secrets (from cloud_sql module)"
}

variable "service_accounts" {
  type        = map(string)
  description = "Map of service name → service account email (from cloud_run module)"
}
