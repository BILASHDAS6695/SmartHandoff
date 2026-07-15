variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "project_number" {
  type        = string
  description = "Numeric GCP project number (from cloud_run module output or data.google_project)"
}

variable "hl7_listener_sa" {
  type        = string
  description = "Email of the HL7 Listener Cloud Run service account (publisher on adt-events)"
}

variable "agent_service_accounts" {
  type        = map(string)
  description = "Map of agent service name \u2192 service account email (from cloud_run module output)"
}
