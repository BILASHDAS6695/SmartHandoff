---
id: TASK-002
title: "Author per-service `cloudbuild.yaml` — Docker Build and Artifact Registry Push"
user_story: US-003
epic: EP-TECH
sprint: 1
layer: CI/CD
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001]
---

# TASK-002: Author per-service `cloudbuild.yaml` — Docker Build and Artifact Registry Push

> **Story:** US-003 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** CI/CD | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

Each SmartHandoff service needs its own `cloudbuild.yaml` that:

1. Invokes the shared lint + unit test steps from TASK-001.
2. Builds a Docker image from the service `Dockerfile`.
3. Pushes the image to the Artifact Registry repository (not Docker Hub, as required by the technical notes for network isolation).
4. Tags the image with the Git commit SHA for immutable traceability.

This task creates a **canonical template** `cloudbuild.yaml` that is copied into each service directory and adjusted with the correct `_SERVICE_NAME` substitution. It satisfies Scenario 1's container build and Artifact Registry push stages.

---

## Acceptance Criteria Addressed

| US-003 AC | Requirement |
|---|---|
| **Scenario 1** | Pipeline executes: … → container build → Artifact Registry push → … |
| **Scenario 4** | No plaintext secrets in any log line — Docker build args must not embed credential values |

---

## Implementation Steps

### 1. Identify the 10 Services

The following services each require a `cloudbuild.yaml`. This list is derived from the Cloud Run service definitions in `infra/terraform/modules/cloud_run/main.tf`:

| Service | Directory | Runtime |
|---|---|---|
| `api-gateway` | `services/api-gateway/` | Node.js |
| `hl7-listener` | `services/hl7-listener/` | Python |
| `coordinator-agent` | `services/coordinator-agent/` | Python |
| `docs-agent` | `services/docs-agent/` | Python |
| `medrecon-agent` | `services/medrecon-agent/` | Python |
| `comms-agent` | `services/comms-agent/` | Python |
| `ml-inference` | `services/ml-inference/` | Python |
| `notification-svc` | `services/notification-svc/` | Node.js |
| `audit-svc` | `services/audit-svc/` | Python |
| `portal-bff` | `services/portal-bff/` | Node.js |

### 2. Canonical `cloudbuild.yaml` Template

Create `.cloudbuild/cloudbuild-template.yaml` as the canonical reference:

```yaml
# Per-service Cloud Build pipeline — SmartHandoff
# Copy to services/<service-name>/cloudbuild.yaml and update _SERVICE_NAME.
substitutions:
  _SERVICE_NAME: 'REPLACE_ME'       # e.g., api-gateway
  _ENVIRONMENT: 'dev'               # Overridden by the Cloud Build trigger
  _REGION: 'us-central1'
  _PROJECT_ID: 'REPLACE_ME'         # Overridden by the Cloud Build trigger substitution
  _IMAGE_TAG: '${COMMIT_SHA}'       # Built-in Cloud Build substitution

steps:
  # --- Stage 1 + 2: Lint and Unit Tests (shared steps via include) ---
  - name: 'gcr.io/cloud-builders/gcloud'
    id: 'invoke-shared-lint-test'
    entrypoint: bash
    args:
      - '-c'
      - |
        gcloud builds submit --no-source \
          --config=../../.cloudbuild/cloudbuild-shared.yaml \
          --substitutions=_SERVICE_DIR=services/${_SERVICE_NAME},_SERVICE_NAME=${_SERVICE_NAME},_ENVIRONMENT=${_ENVIRONMENT}

  # --- Stage 3: Docker Build ---
  - name: 'gcr.io/cloud-builders/docker'
    id: 'docker-build'
    args:
      - 'build'
      - '--tag'
      - '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/smarthandoff-${_ENVIRONMENT}/${_SERVICE_NAME}:${_IMAGE_TAG}'
      - '--tag'
      - '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/smarthandoff-${_ENVIRONMENT}/${_SERVICE_NAME}:latest'
      - '--file'
      - 'Dockerfile'
      - '--build-arg'
      - 'SERVICE_NAME=${_SERVICE_NAME}'
      - '.'
    dir: 'services/${_SERVICE_NAME}'
    waitFor: ['invoke-shared-lint-test']

  # --- Stage 4: Push to Artifact Registry ---
  - name: 'gcr.io/cloud-builders/docker'
    id: 'artifact-registry-push-sha'
    args:
      - 'push'
      - '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/smarthandoff-${_ENVIRONMENT}/${_SERVICE_NAME}:${_IMAGE_TAG}'
    waitFor: ['docker-build']

  - name: 'gcr.io/cloud-builders/docker'
    id: 'artifact-registry-push-latest'
    args:
      - 'push'
      - '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/smarthandoff-${_ENVIRONMENT}/${_SERVICE_NAME}:latest'
    waitFor: ['docker-build']

images:
  - '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/smarthandoff-${_ENVIRONMENT}/${_SERVICE_NAME}:${_IMAGE_TAG}'
  - '${_REGION}-docker.pkg.dev/${_PROJECT_ID}/smarthandoff-${_ENVIRONMENT}/${_SERVICE_NAME}:latest'

options:
  logging: CLOUD_LOGGING_ONLY
  machineType: 'E2_HIGHCPU_8'
  substitution_option: 'ALLOW_LOOSE'

timeout: '900s'   # 15-minute DoD gate — pipeline must complete within this window
```

### 3. Artifact Registry Repository Naming Convention

Images are pushed to:

```
<region>-docker.pkg.dev/<project_id>/smarthandoff-<environment>/<service_name>:<commit_sha>
```

This keeps images in a per-environment repository (`smarthandoff-dev`, `smarthandoff-staging`, `smarthandoff-prod`) preventing cross-environment image promotion accidents.

Verify the Artifact Registry repository was created by the Terraform IaC (US-001 dependency). If the `google_artifact_registry_repository` resource is not present, add it to `infra/terraform/environments/<env>/main.tf`:

```hcl
resource "google_artifact_registry_repository" "container_images" {
  location      = var.region
  repository_id = "smarthandoff-${var.environment}"
  format        = "DOCKER"
  project       = var.project_id

  labels = {
    environment = var.environment
    managed-by  = "terraform"
  }
}
```

### 4. Docker Build Security Constraints

The following constraints **must** be applied to every `docker build` invocation:

- **No `--build-arg` for secrets**: Database passwords, API keys, and tokens must not be passed as Docker build arguments. If a `Dockerfile` currently uses `ARG SECRET_KEY`, refactor it to source the value at container startup from Secret Manager.
- **No `RUN apt-get` with hardcoded package versions that pin to vulnerable releases**: Use pinned digest images (e.g., `FROM python:3.11-slim@sha256:...`) in all Dockerfiles.
- Scan results from TASK-003 gate the push — a failed scan must abort the pipeline before `artifact-registry-push-sha` runs.

### 5. Copy Template to All Service Directories

```bash
for svc in api-gateway hl7-listener coordinator-agent docs-agent medrecon-agent \
           comms-agent ml-inference notification-svc audit-svc portal-bff; do
  cp .cloudbuild/cloudbuild-template.yaml services/$svc/cloudbuild.yaml
  sed -i "s/REPLACE_ME/$svc/g" services/$svc/cloudbuild.yaml
done
```

Verify each file has the correct `_SERVICE_NAME` substitution before committing.

---

## Files Produced

| File | Action |
|---|---|
| `.cloudbuild/cloudbuild-template.yaml` | Create |
| `services/<service>/cloudbuild.yaml` (×10) | Create from template |
| `infra/terraform/environments/<env>/main.tf` | Update — add `google_artifact_registry_repository` if absent |

---

## Definition of Done Checklist

- [ ] Canonical template created at `.cloudbuild/cloudbuild-template.yaml`
- [ ] 10 per-service `cloudbuild.yaml` files created with correct `_SERVICE_NAME`
- [ ] `timeout: '900s'` set — enforces the <15-minute DoD gate
- [ ] Artifact Registry repositories confirmed in Terraform (dev, staging, prod)
- [ ] No `--build-arg` passes secret values; Dockerfile ARG usage audited
- [ ] `docker build` tags both `:${COMMIT_SHA}` and `:latest`
