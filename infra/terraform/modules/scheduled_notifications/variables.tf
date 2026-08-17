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
  description = "Container image for the scheduled notification dispatcher Cloud Run job"
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

variable "phi_encryption_key_secret_id" {
  description = "Secret Manager secret ID for the PHI encryption key"
  type        = string
}

variable "twilio_account_sid_secret_id" {
  description = "Secret Manager secret ID for Twilio Account SID"
  type        = string
}

variable "twilio_auth_token_secret_id" {
  description = "Secret Manager secret ID for Twilio Auth Token"
  type        = string
}

variable "twilio_phone_number_secret_id" {
  description = "Secret Manager secret ID for Twilio phone number"
  type        = string
}

variable "twilio_verify_service_sid_secret_id" {
  description = "Secret Manager secret ID for Twilio Verify Service SID"
  type        = string
}

variable "sendgrid_api_key_secret_id" {
  description = "Secret Manager secret ID for SendGrid API key"
  type        = string
}

variable "sendgrid_from_email_secret_id" {
  description = "Secret Manager secret ID for SendGrid from email"
  type        = string
}

variable "schedule" {
  description = "Cloud Scheduler cron expression"
  type        = string
  default     = "*/1 * * * *"
}

variable "timeout_seconds" {
  description = "Cloud Run job timeout in seconds"
  type        = number
  default     = 300
}
