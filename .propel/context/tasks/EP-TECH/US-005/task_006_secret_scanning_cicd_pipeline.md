---
id: TASK-006
title: "Add Secret Scanning Steps to Cloud Build CI/CD Pipeline"
user_story: US-005
epic: EP-TECH
sprint: 1
layer: CI/CD
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-005]
---

# TASK-006: Add Secret Scanning Steps to Cloud Build CI/CD Pipeline

> **Story:** US-005 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** CI/CD | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-005 Scenario 2 requires that production container images contain zero secrets. The DoD requires a *"secret scanning step added to CI/CD pipeline (scans both source code and built image)"*. 

The CI/CD pipeline is Google Cloud Build (defined in US-003 tasks). This task adds two security gates to `cloudbuild-shared.yaml`:

1. **Stage: source-secret-scan** — `gitleaks` scans the workspace source code before container build. This catches any secret accidentally added to tracked files that bypassed the pre-commit hook.
2. **Stage: image-secret-scan** — `trufflehog` scans the built container image after the Docker build step. This catches secrets baked into image layers (e.g., via `COPY` of an `.env` file or a misconfigured build arg).

Both stages are added as mandatory gates — pipeline fails if either detects a finding.

---

## Acceptance Criteria Addressed

| US-005 AC | Requirement |
|---|---|
| **Scenario 2** | Zero secrets found in production container image layers by `trufflehog` or `gitleaks` |
| **DoD** | Secret scanning step added to CI/CD pipeline (scans both source code and built image) |

---

## Implementation Steps

### 1. Add source secret scan step to `cloudbuild-shared.yaml`

Insert the following step **after the lint stage and before the unit test stage**. It runs gitleaks on the Cloud Build workspace (`/workspace`), which contains the checked-out source tree.

```yaml
  # --- Stage: Source Secret Scan (gitleaks) ---
  - name: 'zricethezav/gitleaks:v8.18.4'
    id: 'source-secret-scan'
    entrypoint: 'gitleaks'
    args:
      - 'detect'
      - '--source=/workspace'
      - '--config=/workspace/.gitleaks.toml'
      - '--redact'
      - '--verbose'
      - '--no-git'
    waitFor: ['lint-python', 'lint-js']
```

**Key flags:**
- `--no-git`: scans the filesystem, not git history — appropriate for Cloud Build which does a shallow clone.
- `--redact`: masks detected secret values in Cloud Build logs (satisfies US-003 Scenario 4).
- `--config`: uses the project-specific allowlist from TASK-005 to suppress false positives on example files.

### 2. Add container image secret scan step to the per-service `cloudbuild.yaml` template

The container image scan step must run **after** the `docker build` step, using `trufflehog` in filesystem mode against the unpacked image. Add this step to the per-service `cloudbuild.yaml` after the Docker build step (US-003 TASK-002):

```yaml
  # --- Stage: Container Image Secret Scan (trufflehog) ---
  - name: 'trufflesecurity/trufflehog:latest'
    id: 'image-secret-scan'
    entrypoint: 'trufflehog'
    args:
      - 'docker'
      - '--image=gcr.io/$PROJECT_ID/${_SERVICE_NAME}:${SHORT_SHA}'
      - '--only-verified'
      - '--fail'
    waitFor: ['docker-build']
```

**Key flags:**
- `docker` subcommand: scans all layers of a built Docker image directly.
- `--only-verified`: reduces false-positive noise by only reporting secrets that have been verified as active — appropriate for a blocking gate.
- `--fail`: exits with a non-zero code if any verified secret is found, failing the Cloud Build step.

### 3. Confirm Cloud Build service account has Artifact Registry read permission

The image scan step pulls the image from Artifact Registry. Confirm the Cloud Build service account (`{PROJECT_NUMBER}@cloudbuild.gserviceaccount.com`) has `roles/artifactregistry.reader`. This binding should already exist from US-003 TASK-002; if not, add it to the relevant IAM module.

### 4. Add scan step to shared YAML stage ordering comment

Update the `cloudbuild-shared.yaml` header comment to reflect the updated stage order:

```yaml
# Pipeline stage order:
# lint → source-secret-scan → unit-tests → container-build
# → image-secret-scan → vulnerability-scan → canary-deploy → full-promotion
```

---

## Files Modified / Created

| File | Action |
|---|---|
| `cloudbuild-shared.yaml` | Add `source-secret-scan` step (gitleaks) after lint stage |
| `cloudbuild.yaml` (per-service template) | Add `image-secret-scan` step (trufflehog) after docker build |

---

## Verification

```bash
# Trigger a Cloud Build run on a branch without secrets — should pass
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_SERVICE_NAME=api-gateway,_SERVICE_DIR=services/api-gateway \
  --project=smarthandoff-dev

# Inject a fake secret into the source tree and trigger — should fail at source-secret-scan
echo 'TWILIO_AUTH_TOKEN=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' > services/api-gateway/src/leaked.py
gcloud builds submit ...
# Expected: Step source-secret-scan FAILED: gitleaks detected 1 finding
# Cleanup: rm services/api-gateway/src/leaked.py
```
