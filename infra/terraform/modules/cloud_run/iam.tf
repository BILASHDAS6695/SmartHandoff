# ── Load Balancer → API Gateway (public internet access) ─────────────
# Only the API Gateway is exposed publicly; all other services are internal.
resource "google_cloud_run_v2_service_iam_member" "api_gateway_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.services["api-gateway"].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Agent service accounts → API Gateway (service-to-service) ─────────
# Agents POST status updates to the FastAPI SignalR hub endpoint.
resource "google_cloud_run_v2_service_iam_member" "agent_invoke_api" {
  for_each = toset([
    "coordinator-agent",
    "docs-agent",
    "medrecon-agent",
    "bed-mgmt-agent",
    "followup-agent",
    "comms-agent",
    "ml-inference",
    "notification-svc",
  ])

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.services["api-gateway"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cloud_run_sa[each.value].email}"
}

# ── Cloud Build service account → all Cloud Run services ──────────────
# Required so Cloud Deploy can deploy new revisions via Cloud Build.
resource "google_cloud_run_v2_service_iam_member" "cloudbuild_deploy" {
  for_each = local.services

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.services[each.key].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}
