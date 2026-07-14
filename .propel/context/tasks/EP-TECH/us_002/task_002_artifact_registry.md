---
task_id: task_002
story_id: us_002
epic: EP-TECH
title: Artifact Registry — Repository Setup and Image Naming Convention
layer: Artifact Management
effort_hours: 1
sequence: 2
status: Draft
---

# TASK-002: Artifact Registry — Repository Setup and Image Naming Convention

> **Story:** EP-TECH/US-002 | **Layer:** Artifact Management | **Effort:** 1 hour | **Seq:** 2 of 7

## Objective

Configure GCP Artifact Registry to store Docker images for all 10 SmartHandoff services, establish a consistent image naming convention, and enable automatic vulnerability scanning — so that every image build produces a scanned, versioned artefact ready for Cloud Deploy.

## Implementation Steps

### 1. Terraform — Artifact Registry Repositories (`modules/artifact_registry/main.tf`)

```hcl
resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "smarthandoff-${var.environment}"
  description   = "SmartHandoff Docker images (${var.environment})"
  format        = "DOCKER"
  project       = var.project_id

  # Enable automatic vulnerability scanning on push
  # (enabled at project level via Cloud Build trigger — see Task 003)

  cleanup_policies {
    id     = "keep-minimum-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5  # Keep last 5 tags per image
    }
  }

  cleanup_policies {
    id     = "delete-untagged-after-7-days"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s"  # 7 days
    }
  }

  docker_config {
    immutable_tags = false  # Allow `latest` to be overwritten
  }
}

# Grant Cloud Build service account push access
resource "google_artifact_registry_repository_iam_member" "cloudbuild_writer" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.docker.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# Grant Cloud Run service accounts pull access (all 10 services)
resource "google_artifact_registry_repository_iam_member" "cloudrun_readers" {
  for_each = var.cloud_run_service_accounts

  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.docker.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value}"
}

output "registry_hostname" {
  value = "${var.region}-docker.pkg.dev"
}
output "registry_base_path" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/smarthandoff-${var.environment}"
}
```

### 2. Image Naming Convention

All images follow this pattern:

```
{REGION}-docker.pkg.dev/{PROJECT_ID}/smarthandoff-{ENV}/{SERVICE_NAME}:{TAG}
```

| Variable | Example |
|----------|---------|
| `REGION` | `us-central1` |
| `PROJECT_ID` | `smarthandoff-staging` |
| `ENV` | `staging` |
| `SERVICE_NAME` | `api-gateway`, `docs-agent`, `hl7-listener`, etc. |
| `TAG` | `git-{SHORT_SHA}` (primary), `latest` (secondary) |

**Example full image path:**
```
us-central1-docker.pkg.dev/smarthandoff-staging/smarthandoff-staging/api-gateway:git-a3f9b12
```

**Tagging strategy:**
- Primary tag: `git-${SHORT_SHA}` — immutable, traceable to exact commit
- Secondary tag: `latest` — updated on every successful main branch build
- Do NOT use mutable tags like `v1.0` for production deployments

### 3. Service → Dockerfile Mapping (`services.yaml` in repo root)

```yaml
# services.yaml — defines which Dockerfile template each service uses
services:
  api-gateway:
    dockerfile: docker/python-service/Dockerfile
    context: services/api-gateway
  hl7-listener:
    dockerfile: docker/python-service/Dockerfile
    context: services/hl7-listener
  coordinator-agent:
    dockerfile: docker/agent-service/Dockerfile
    context: services/coordinator-agent
  docs-agent:
    dockerfile: docker/agent-service/Dockerfile
    context: services/docs-agent
  medrecon-agent:
    dockerfile: docker/agent-service/Dockerfile
    context: services/medrecon-agent
  bed-mgmt-agent:
    dockerfile: docker/agent-service/Dockerfile
    context: services/bed-mgmt-agent
  followup-agent:
    dockerfile: docker/agent-service/Dockerfile
    context: services/followup-agent
  comms-agent:
    dockerfile: docker/agent-service/Dockerfile
    context: services/comms-agent
  ml-inference:
    dockerfile: docker/python-service/Dockerfile
    context: services/ml-inference
  notification-svc:
    dockerfile: docker/python-service/Dockerfile
    context: services/notification-svc
  angular-pwa:
    dockerfile: docker/angular-pwa/Dockerfile
    context: frontend
```

### 4. Configure Artifact Registry Vulnerability Scanning

Vulnerability scanning is enabled at the project/registry level via the Container Scanning API:

```hcl
resource "google_project_service" "container_scanning" {
  service            = "containerscanning.googleapis.com"
  project            = var.project_id
  disable_on_destroy = false
}
```

With this API enabled, every image pushed to Artifact Registry is automatically scanned. Results are available via:
- GCP Console → Artifact Registry → {image} → Security tab
- Cloud Build API: `gcloud artifacts docker images list-vulnerabilities`
- In Cloud Build pipeline (Task 003): `gcloud artifacts docker images describe {image} --show-package-vulnerability`

## Acceptance Criteria

- [ ] `gcloud artifacts repositories list --project={PROJECT} --location=us-central1` shows `smarthandoff-{env}` repository with format `DOCKER`
- [ ] Cleanup policy active: `gcloud artifacts repositories describe smarthandoff-dev --location=us-central1 --format=json | jq '.cleanupPolicies'` shows both policies defined
- [ ] Cloud Build service account has `artifactregistry.writer` role on repository
- [ ] Container scanning API enabled: `gcloud services list --project={PROJECT} --filter=containerscanning` shows ENABLED
- [ ] Test push: `docker push us-central1-docker.pkg.dev/{PROJECT}/smarthandoff-dev/api-gateway:test` succeeds from Cloud Build; image appears in registry with vulnerability scan status
- [ ] Cloud Run service accounts have `artifactregistry.reader` role: `gcloud artifacts repositories get-iam-policy smarthandoff-dev --location=us-central1` shows each service account's reader binding

## Files to Create

```
infra/terraform/modules/artifact_registry/main.tf
infra/terraform/modules/artifact_registry/variables.tf
infra/terraform/modules/artifact_registry/outputs.tf
services.yaml
```

## Notes

- Cleanup policy `keep-minimum-versions: 5` prevents unbounded registry growth; old images are purged automatically
- `immutable_tags = false` is needed so `latest` can be overwritten — production deployments should always reference `git-{SHA}` tags, never `latest`
- Container scanning results take 2–5 minutes after push to appear — Cloud Build pipeline must poll or use `--async` and check results separately (Task 003)
