# ── Service sizing map ────────────────────────────────────────────────────
locals {
  # Matches Design §9.2 exactly.
  # cpu_idle = false for api-gateway and coordinator-agent (latency-sensitive);
  # all agents use cpu_idle = true to reduce costs during low-traffic periods.
  services = {
    "api-gateway" = {
      min         = 2
      max         = 20
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 100
      cpu_idle    = false
    }
    "hl7-listener" = {
      min         = 1
      max         = 10
      cpu         = "1000m"
      memory      = "512Mi"
      concurrency = 50
      cpu_idle    = false
    }
    "coordinator-agent" = {
      min         = 1
      max         = 10
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 20
      cpu_idle    = false
    }
    "docs-agent" = {
      min         = 1
      max         = 10
      cpu         = "2000m"
      memory      = "4Gi"
      concurrency = 5
      cpu_idle    = true
    }
    "medrecon-agent" = {
      min         = 1
      max         = 10
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 10
      cpu_idle    = true
    }
    "bed-mgmt-agent" = {
      min         = 1
      max         = 5
      cpu         = "1000m"
      memory      = "1Gi"
      concurrency = 20
      cpu_idle    = true
    }
    "followup-agent" = {
      min         = 1
      max         = 10
      cpu         = "1000m"
      memory      = "1Gi"
      concurrency = 20
      cpu_idle    = true
    }
    "comms-agent" = {
      min         = 1
      max         = 10
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 10
      cpu_idle    = true
    }
    "ml-inference" = {
      min         = 1
      max         = 5
      cpu         = "2000m"
      memory      = "2Gi"
      concurrency = 50
      cpu_idle    = true
    }
    "notification-svc" = {
      min         = 1
      max         = 5
      cpu         = "1000m"
      memory      = "512Mi"
      concurrency = 50
      cpu_idle    = true
    }
  }
}

# ── Dedicated service account per Cloud Run service ──────────────────────
resource "google_service_account" "cloud_run_sa" {
  for_each = local.services

  account_id   = "cr-${each.key}-${var.environment}"
  display_name = "Cloud Run SA: ${each.key} (${var.environment})"
  project      = var.project_id
}

# ── Cloud Run v2 services ────────────────────────────────────────────────
resource "google_cloud_run_v2_service" "services" {
  for_each = local.services

  name     = "${each.key}-${var.environment}"
  location = var.region
  project  = var.project_id

  # Only the API Gateway is reachable from the public internet.
  # All other services (agents, HL7 listener, etc.) are internal only.
  ingress = each.key == "api-gateway" ? "INGRESS_TRAFFIC_ALL" : "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.cloud_run_sa[each.key].email

    scaling {
      min_instance_count = each.value.min
      max_instance_count = each.value.max
    }

    max_instance_request_concurrency = each.value.concurrency

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "ALL_TRAFFIC"
    }

    containers {
      # Placeholder image — CI/CD (Cloud Deploy) replaces this on first real deploy.
      # lifecycle.ignore_changes below prevents Terraform from reverting CI/CD updates.
      image = "us-docker.pkg.dev/cloudrun/container/hello"

      resources {
        limits = {
          cpu    = each.value.cpu
          memory = each.value.memory
        }
        cpu_idle          = each.value.cpu_idle
        startup_cpu_boost = true
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds    = 10
        failure_threshold = 3
      }

      startup_probe {
        http_get {
          path = "/ready"
        }
        period_seconds    = 5
        failure_threshold = 12 # 60-second startup window
      }

      # Non-sensitive runtime config; secrets are mounted via Secret Manager bindings
      # added in Task 008 (us_001) once all secrets are defined.
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "REGION"
        value = var.region
      }
    }
  }

  lifecycle {
    # CI/CD (Cloud Deploy) manages the container image after initial provision.
    # Prevent Terraform from reverting image tags set by Cloud Deploy.
    ignore_changes = [template[0].containers[0].image]
  }

  depends_on = [google_service_account.cloud_run_sa]
}
