variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region for regional buckets"
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "kms_key_ring_id" {
  type        = string
  description = "KMS key ring ID from cloud_sql module (reused for Cloud Storage CMEK)"
}

variable "hl7_listener_sa" {
  type        = string
  description = "HL7 Listener Cloud Run service account email (objectCreator on HL7 archive)"
}

variable "api_gateway_sa" {
  type        = string
  description = "API Gateway Cloud Run service account email (objectCreator on audit export)"
}

variable "agent_service_accounts" {
  type        = map(string)
  description = "Map of agent service name → service account email (objectViewer on ML models)"
}
