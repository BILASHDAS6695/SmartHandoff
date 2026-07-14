output "service_urls" {
  description = "Map of service name → Cloud Run service URI"
  value       = { for k, v in google_cloud_run_v2_service.services : k => v.uri }
}

output "service_accounts" {
  description = "Map of service name → service account email"
  value       = { for k, v in google_service_account.cloud_run_sa : k => v.email }
}

output "api_gateway_url" {
  description = "URI of the public-facing API Gateway Cloud Run service"
  value       = google_cloud_run_v2_service.services["api-gateway"].uri
}

output "project_number" {
  description = "Numeric project number — used by Pub/Sub DLQ IAM binding"
  value       = data.google_project.project.number
}

data "google_project" "project" {
  project_id = var.project_id
}
