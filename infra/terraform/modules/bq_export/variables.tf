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
  description = "GCP region (e.g., us-central1)"
}

variable "container_image" {
  type        = string
  description = "Full container image URI for the bq-export Cloud Run job (e.g., gcr.io/project/bq-export:sha)"
}

variable "cloud_sql_connection_name" {
  type        = string
  description = "Cloud SQL instance connection name (project:region:instance)"
}

variable "db_name" {
  type        = string
  description = "PostgreSQL database name"
}

variable "db_user" {
  type        = string
  description = "PostgreSQL user name (non-sensitive; password from Secret Manager)"
}

variable "db_password_secret_id" {
  type        = string
  description = "Secret Manager secret ID for the database password"
}

variable "deidentification_salt_secret_id" {
  type        = string
  description = "Secret Manager secret ID for the monthly-rotated de-identification salt"
}
