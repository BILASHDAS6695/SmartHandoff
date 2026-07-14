---
task_id: task_003
story_id: us_001
epic: EP-TECH
title: Cloud Run Service Definitions — All 10 Services with Correct Sizing
layer: Compute / Cloud Run
effort_hours: 3
sequence: 3
status: Implemented
---

# TASK-003: Cloud Run Service Definitions — All 10 Services with Correct Sizing

> **Story:** EP-TECH/US-001 | **Layer:** Compute | **Effort:** 3 hours | **Seq:** 3 of 11

## Objective

Create the `cloud_run` Terraform module that defines all 10 Cloud Run services with exact CPU, memory, min/max instance counts, VPC connector bindings, and dedicated service accounts — matching Design §9.2 exactly.

## Implementation Steps

### 1. Service Account Per Service

Each Cloud Run service runs with a dedicated service account (least privilege):

```hcl
locals {
  services = {
    "api-gateway"       = { min = 2,  max = 20, cpu = "2000m",  memory = "2Gi",  concurrency = 100 }
    "hl7-listener"      = { min = 1,  max = 10, cpu = "1000m",  memory = "512Mi", concurrency = 50  }
    "coordinator-agent" = { min = 1,  max = 10, cpu = "2000m",  memory = "2Gi",  concurrency = 20  }
    "docs-agent"        = { min = 1,  max = 10, cpu = "2000m",  memory = "4Gi",  concurrency = 5   }
    "medrecon-agent"    = { min = 1,  max = 10, cpu = "2000m",  memory = "2Gi",  concurrency = 10  }
    "bed-mgmt-agent"    = { min = 1,  max = 5,  cpu = "1000m",  memory = "1Gi",  concurrency = 20  }
    "followup-agent"    = { min = 1,  max = 10, cpu = "1000m",  memory = "1Gi",  concurrency = 20  }
    "comms-agent"       = { min = 1,  max = 10, cpu = "2000m",  memory = "2Gi",  concurrency = 10  }
    "ml-inference"      = { min = 1,  max = 5,  cpu = "2000m",  memory = "2Gi",  concurrency = 50  }
    "notification-svc"  = { min = 1,  max = 5,  cpu = "1000m",  memory = "512Mi", concurrency = 50  }
  }
}

resource "google_service_account" "cloud_run_sa" {
  for_each     = local.services
  account_id   = "cr-${each.key}-${var.environment}"
  display_name = "Cloud Run SA: ${each.key} (${var.environment})"
  project      = var.project_id
}
```

### 2. Cloud Run Service Resource (module `modules/cloud_run/main.tf`)

```hcl
resource "google_cloud_run_v2_service" "services" {
  for_each = local.services

  name     = "${each.key}-${var.environment}"
  location = var.region
  project  = var.project_id

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
      # Placeholder image — replaced by CI/CD on first deploy
      image = "us-docker.pkg.dev/cloudrun/container/hello"

      resources {
        limits = {
          cpu    = each.value.cpu
          memory = each.value.memory
        }
        cpu_idle = false  # Keep CPU allocated for latency-sensitive services
        startup_cpu_boost = true
      }

      # Health probes
      liveness_probe {
        http_get { path = "/health" }
        period_seconds    = 10
        failure_threshold = 3
      }

      startup_probe {
        http_get { path = "/ready" }
        period_seconds    = 5
        failure_threshold = 12  # 60s startup window
      }

      # Environment variables — non-sensitive only; secrets via Secret Manager bindings (Task 008)
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
    # Prevent Terraform from reverting image changes made by CI/CD
    ignore_changes = [template[0].containers[0].image]
  }
}
```

### 3. IAM — Allow Load Balancer to Invoke API Gateway

```hcl
resource "google_cloud_run_v2_service_iam_member" "api_gateway_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.services["api-gateway"].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
```

> All other services: internal only — no `allUsers` invoker.

### 4. Inter-Service IAM (Service-to-Service)

```hcl
# Each agent service account can invoke the API Gateway
resource "google_cloud_run_v2_service_iam_member" "agent_invoke_api" {
  for_each = toset([
    "coordinator-agent", "docs-agent", "medrecon-agent",
    "bed-mgmt-agent", "followup-agent", "comms-agent",
    "ml-inference", "notification-svc"
  ])

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.services["api-gateway"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cloud_run_sa[each.value].email}"
}
```

### 5. Outputs (`modules/cloud_run/outputs.tf`)

```hcl
output "service_urls" {
  value = { for k, v in google_cloud_run_v2_service.services : k => v.uri }
}

output "service_accounts" {
  value = { for k, v in google_service_account.cloud_run_sa : k => v.email }
}

output "api_gateway_url" {
  value = google_cloud_run_v2_service.services["api-gateway"].uri
}
```

## Acceptance Criteria

- [ ] `terraform apply` creates exactly 10 Cloud Run services with names matching the services map keys
- [ ] Each service has `min_instance_count` and `max_instance_count` matching Design §9.2 table
- [ ] `docs-agent` service shows `memory: 4Gi`; `api-gateway` shows `min: 2`
- [ ] All services (except `api-gateway`) have `ingress: INGRESS_TRAFFIC_INTERNAL_ONLY` — confirmed via `gcloud run services describe {name} --region=us-central1 --format=json | jq '.spec.template.metadata.annotations["run.googleapis.com/ingress"]'`
- [ ] All services configured with VPC connector binding
- [ ] Each service has a dedicated service account with prefix `cr-{service-name}-{env}`
- [ ] `lifecycle.ignore_changes` on `image` prevents Terraform from reverting CI/CD image deployments
- [ ] `liveness_probe` and `startup_probe` configured on all services

## Files to Create

```
infra/terraform/modules/cloud_run/main.tf
infra/terraform/modules/cloud_run/variables.tf
infra/terraform/modules/cloud_run/outputs.tf
infra/terraform/modules/cloud_run/iam.tf
infra/terraform/modules/cloud_run/README.md
```

## Notes

- Placeholder image `us-docker.pkg.dev/cloudrun/container/hello` used at Terraform provision time — CI/CD replaces this on first real deploy
- `cpu_idle = false` keeps CPU allocated to prevent latency spikes for `api-gateway` and `coordinator-agent`; all other services can use `cpu_idle = true` (cost saving)
- HL7 Listener is internal-only but needs a TCP port 2575 — handled via an internal load balancer or direct Cloud Run TCP ingress (Cloud Run now supports TCP); document this separately in HL7 epic task
