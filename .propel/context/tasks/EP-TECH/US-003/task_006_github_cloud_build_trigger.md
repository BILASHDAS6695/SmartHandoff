---
id: TASK-006
title: "Configure GitHub → Cloud Build Trigger for Push to `main` on All Service Repositories"
user_story: US-003
epic: EP-TECH
sprint: 1
layer: CI/CD
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-006: Configure GitHub → Cloud Build Trigger for Push to `main` on All Service Repositories

> **Story:** US-003 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** CI/CD | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-003 requires that the pipeline fires automatically on every push to `main`. This requires a Cloud Build trigger connected to the GitHub repository via the Cloud Build GitHub App. The DoD explicitly states:

> *"Cloud Build trigger configured for push to `main` on all service repositories"*

This task provisions the Terraform resource for the Cloud Build trigger, connects it to GitHub, and verifies the trigger fires correctly on a test push.

---

## Acceptance Criteria Addressed

| US-003 AC | Requirement |
|---|---|
| **Scenario 1** | `Given` a developer pushes a commit to the `main` branch `When` the GitHub → Cloud Build trigger fires `Then` the pipeline executes stages in order |

---

## Implementation Steps

### 1. Connect GitHub Repository to Cloud Build (One-time Manual Step)

Before Terraform can create triggers, the GitHub App connection must be established manually in the GCP Console (this is a one-time OAuth handshake that cannot be automated via Terraform):

1. Navigate to **Cloud Build → Triggers → Connect repository**.
2. Select **GitHub (Cloud Build GitHub App)**.
3. Authenticate with the GitHub account that owns `${_GITHUB_OWNER}/${_GITHUB_REPO}`.
4. Grant the Cloud Build GitHub App access to the `SmartHandoff` repository.
5. Note the **connection name** and **repository resource name** — you will need these for Terraform.

### 2. Add Cloud Build Trigger Resource in Terraform

Add the following to `infra/terraform/environments/<env>/main.tf`. Use a `for_each` over the service list to avoid duplicating the trigger resource 10 times.

```hcl
locals {
  cicd_services = toset([
    "api-gateway", "hl7-listener", "coordinator-agent", "docs-agent",
    "medrecon-agent", "comms-agent", "ml-inference", "notification-svc",
    "audit-svc", "portal-bff"
  ])
}

resource "google_cloudbuild_trigger" "main_push" {
  for_each    = local.cicd_services
  name        = "smarthandoff-${each.key}-main-push-${var.environment}"
  description = "CI/CD pipeline for ${each.key} on push to main — ${var.environment}"
  project     = var.project_id
  location    = "global"

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^main$"
    }
  }

  # Only trigger when files under the service directory or shared config change
  included_files = [
    "services/${each.key}/**",
    ".cloudbuild/**",
    "cloudbuild-shared.yaml"
  ]

  filename = "services/${each.key}/cloudbuild.yaml"

  substitutions = {
    _SERVICE_NAME = each.key
    _ENVIRONMENT  = var.environment
    _REGION       = var.region
    _PROJECT_ID   = var.project_id
    _ORG_ID       = var.org_id
  }

  service_account = "projects/${var.project_id}/serviceAccounts/${var.cloudbuild_sa_email}"
}
```

### 3. Add Required Variables to `variables.tf`

Add the following variables to `infra/terraform/environments/<env>/variables.tf` if not already present:

```hcl
variable "github_owner" {
  type        = string
  description = "GitHub organisation or user that owns the SmartHandoff repository"
}

variable "github_repo" {
  type        = string
  description = "GitHub repository name (without owner prefix)"
}

variable "org_id" {
  type        = string
  description = "GCP Organisation ID — required for Cloud SCC SARIF upload (TASK-003)"
}

variable "cloudbuild_sa_email" {
  type        = string
  description = "Service account email used by Cloud Build triggers; must have roles/run.developer, roles/artifactregistry.writer, roles/iam.serviceAccountUser"
}
```

Add corresponding values to `terraform.tfvars`:

```hcl
github_owner        = "your-github-org"
github_repo         = "SmartHandoff"
org_id              = "123456789012"
cloudbuild_sa_email = "cloudbuild-sa@smarthandoff-dev.iam.gserviceaccount.com"
```

### 4. Grant Cloud Build Service Account Required IAM Roles

The Cloud Build service account must have the following roles to execute all pipeline stages:

```hcl
locals {
  cloudbuild_roles = [
    "roles/run.developer",               # Deploy Cloud Run revisions + traffic split
    "roles/artifactregistry.writer",      # Push images to Artifact Registry
    "roles/iam.serviceAccountUser",       # Act as Cloud Run service account
    "roles/secretmanager.secretAccessor", # Read secrets at runtime (Scenario 4)
    "roles/monitoring.viewer",            # Read error rate metrics (TASK-004 observation window)
    "roles/logging.viewer",               # Read Cloud Build logs for audit
    "roles/storage.objectAdmin",          # Read/write Trivy cache bucket (TASK-003)
  ]
}

resource "google_project_iam_member" "cloudbuild_sa_roles" {
  for_each = toset(local.cloudbuild_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${var.cloudbuild_sa_email}"
}
```

### 5. Verify Trigger Fires on Test Push

After `terraform apply` succeeds:

1. Create a branch `test/cicd-trigger-verify` from `main`.
2. Make a trivial change to `services/api-gateway/README.md`.
3. Merge the branch to `main` via a pull request.
4. Observe in **Cloud Build → History** that the `smarthandoff-api-gateway-main-push-dev` trigger fired within 60 seconds.
5. Confirm the build progresses through lint → unit test steps (stages 1–2 from TASK-001).

---

## Files Produced

| File | Action |
|---|---|
| `infra/terraform/environments/dev/main.tf` | Update — add `google_cloudbuild_trigger.main_push` and `google_project_iam_member.cloudbuild_sa_roles` |
| `infra/terraform/environments/dev/variables.tf` | Update — add `github_owner`, `github_repo`, `org_id`, `cloudbuild_sa_email` |
| `infra/terraform/environments/dev/terraform.tfvars.example` | Update — add example values for new variables |
| `infra/terraform/environments/staging/main.tf` | Update — mirror changes |
| `infra/terraform/environments/prod/main.tf` | Update — mirror changes |

---

## Definition of Done Checklist

- [ ] GitHub App connection established manually for `SmartHandoff` repository
- [ ] `google_cloudbuild_trigger.main_push` Terraform resource created for all 10 services (dev, staging, prod)
- [ ] `included_files` filter restricts trigger to service-directory changes only — global pushes do not fire all 10 triggers simultaneously
- [ ] Cloud Build service account has all 7 required IAM roles
- [ ] Test push to `main` confirms trigger fires and lint + unit test stages execute
- [ ] `terraform apply` completes with zero errors for dev environment
