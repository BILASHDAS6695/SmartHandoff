variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  description = "GCP region for the Serverless NEG"
  default     = "us-central1"
}

variable "environment" {
  type        = string
  description = "Deployment environment: dev | staging | prod"
}

variable "api_gateway_service_name" {
  type        = string
  description = "Cloud Run service name for the API Gateway (e.g. api-gateway-dev)"
}

variable "pwa_bucket_name" {
  type        = string
  description = "Name of the Angular PWA Cloud Storage bucket (from storage module output)"
}

variable "api_domain" {
  type        = string
  description = "Fully-qualified API domain for managed SSL certificate (e.g. api.dev.smarthandoff.health)"
}
