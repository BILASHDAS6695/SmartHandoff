variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run job and scheduler"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "container_image" {
  description = "Container image for the ADT ingest Cloud Run job"
  type        = string
}

variable "cloud_sql_connection_name" {
  description = "Cloud SQL instance connection name"
  type        = string
}

variable "db_name" {
  description = "SmartHandoff database name"
  type        = string
}

variable "db_user" {
  description = "SmartHandoff database user"
  type        = string
}

variable "db_password_secret_id" {
  description = "Secret Manager secret ID for the database password"
  type        = string
}

variable "fhir_base_url_secret_id" {
  description = "Secret Manager secret ID for the FHIR base URL"
  type        = string
}

variable "fhir_client_id_secret_id" {
  description = "Secret Manager secret ID for the FHIR OAuth client ID"
  type        = string
}

variable "fhir_client_secret_secret_id" {
  description = "Secret Manager secret ID for the FHIR OAuth client secret"
  type        = string
}

variable "signalr_connection_string_secret_id" {
  description = "Secret Manager secret ID for the Azure SignalR connection string"
  type        = string
}

variable "schedule" {
  description = "Cloud Scheduler cron expression"
  type        = string
  default     = "*/1 * * * *"
}
