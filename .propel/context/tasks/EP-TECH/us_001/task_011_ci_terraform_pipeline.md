---
task_id: task_011
story_id: us_001
epic: EP-TECH
title: CI Integration — terraform validate and plan in Cloud Build PR Pipeline
layer: CI/CD
effort_hours: 1.5
sequence: 11
status: Draft
---

# TASK-011: CI Integration — terraform validate and plan in Cloud Build PR Pipeline

> **Story:** EP-TECH/US-001 | **Layer:** CI/CD | **Effort:** 1.5 hours | **Seq:** 11 of 11

## Objective

Add `terraform validate` and `terraform plan` steps to the Cloud Build CI pipeline so that every pull request affecting `infra/terraform/` triggers automated validation — and `terraform apply` runs automatically on merge to `main` for the staging environment, satisfying US-001 AC-6.

## Implementation Steps

### 1. Cloud Build Trigger for Terraform PRs (`.cloudbuild/terraform-pr.yaml`)

```yaml
# Cloud Build pipeline: runs on every PR touching infra/terraform/**
steps:

  # Step 1: Install Terraform
  - name: 'hashicorp/terraform:1.7.0'
    entrypoint: 'terraform'
    args: ['version']
    id: 'terraform-version'

  # Step 2: Init with GCS backend for staging
  - name: 'hashicorp/terraform:1.7.0'
    entrypoint: 'terraform'
    args:
      - 'init'
      - '-backend-config=bucket=smarthandoff-tf-state-staging'
      - '-reconfigure'
    dir: 'infra/terraform/environments/staging'
    id: 'terraform-init'
    env:
      - 'TF_VAR_project_id=${_PROJECT_ID}'
      - 'TF_VAR_environment=staging'

  # Step 3: Validate — syntax and schema check
  - name: 'hashicorp/terraform:1.7.0'
    entrypoint: 'terraform'
    args: ['validate']
    dir: 'infra/terraform/environments/staging'
    id: 'terraform-validate'
    waitFor: ['terraform-init']

  # Step 4: Plan — dry run; output saved to artifact
  - name: 'hashicorp/terraform:1.7.0'
    entrypoint: 'terraform'
    args:
      - 'plan'
      - '-out=/workspace/tfplan-staging'
      - '-no-color'
      - '-var=project_id=${_PROJECT_ID}'
      - '-var=environment=staging'
      - '-var=region=us-central1'
      - '-var=api_domain=api.staging.smarthandoff.health'
      - '-var=oncall_email=${_ONCALL_EMAIL}'
    dir: 'infra/terraform/environments/staging'
    id: 'terraform-plan'
    waitFor: ['terraform-validate']

  # Step 5: Show plan summary (posted to PR comment via substitution)
  - name: 'hashicorp/terraform:1.7.0'
    entrypoint: 'terraform'
    args: ['show', '-no-color', '/workspace/tfplan-staging']
    dir: 'infra/terraform/environments/staging'
    id: 'terraform-show'
    waitFor: ['terraform-plan']

artifacts:
  objects:
    location: 'gs://smarthandoff-tf-state-staging/plans'
    paths: ['/workspace/tfplan-staging']

substitutions:
  _PROJECT_ID: 'smarthandoff-staging'
  _ONCALL_EMAIL: 'oncall@smarthandoff.health'

options:
  logging: CLOUD_LOGGING_ONLY
  machineType: 'N1_HIGHCPU_8'
```

### 2. Cloud Build Trigger for Terraform Apply on `main` (`.cloudbuild/terraform-apply.yaml`)

```yaml
# Runs on push to main branch — applies to staging automatically
steps:

  - name: 'hashicorp/terraform:1.7.0'
    entrypoint: 'terraform'
    args: ['init', '-backend-config=bucket=smarthandoff-tf-state-staging', '-reconfigure']
    dir: 'infra/terraform/environments/staging'

  - name: 'hashicorp/terraform:1.7.0'
    entrypoint: 'terraform'
    args: ['validate']
    dir: 'infra/terraform/environments/staging'

  - name: 'hashicorp/terraform:1.7.0'
    entrypoint: 'terraform'
    args:
      - 'apply'
      - '-auto-approve'
      - '-var=project_id=${_PROJECT_ID}'
      - '-var=environment=staging'
      - '-var=region=us-central1'
      - '-var=api_domain=api.staging.smarthandoff.health'
      - '-var=oncall_email=${_ONCALL_EMAIL}'
    dir: 'infra/terraform/environments/staging'

substitutions:
  _PROJECT_ID: 'smarthandoff-staging'
  _ONCALL_EMAIL: 'oncall@smarthandoff.health'

options:
  logging: CLOUD_LOGGING_ONLY
```

### 3. Cloud Build Trigger Definitions (Terraform-managed)

```hcl
# In modules/cloud_run/triggers.tf or a new ci_cd module

resource "google_cloudbuild_trigger" "terraform_pr" {
  name    = "terraform-pr-validation-${var.environment}"
  project = var.project_id

  github {
    owner = var.github_owner
    name  = var.github_repo
    pull_request {
      branch = ".*"  # All branches
      comment_control = "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"
    }
  }

  included_files = ["infra/terraform/**"]
  filename       = ".cloudbuild/terraform-pr.yaml"

  substitutions = {
    _PROJECT_ID   = var.project_id
    _ONCALL_EMAIL = var.oncall_email
  }
}

resource "google_cloudbuild_trigger" "terraform_apply" {
  name    = "terraform-apply-main-${var.environment}"
  project = var.project_id

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^main$"
    }
  }

  included_files = ["infra/terraform/**"]
  filename       = ".cloudbuild/terraform-apply.yaml"

  substitutions = {
    _PROJECT_ID   = var.project_id
    _ONCALL_EMAIL = var.oncall_email
  }
}
```

### 4. CI Service Account IAM

The Cloud Build service account needs access to apply Terraform:

```hcl
locals {
  ci_sa = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"

  ci_roles = [
    "roles/editor",                       # Broad for IaC (scope down in production)
    "roles/iam.serviceAccountAdmin",       # Create service accounts
    "roles/iam.serviceAccountUser",        # Assign service accounts to Cloud Run
    "roles/resourcemanager.projectIamAdmin", # Set IAM policies
    "roles/storage.admin",                 # Terraform state bucket
    "roles/secretmanager.admin",           # Create and manage secrets
    "roles/cloudkms.admin",               # KMS key management
  ]
}

resource "google_project_iam_member" "ci_roles" {
  for_each = toset(local.ci_roles)
  project  = var.project_id
  role     = each.value
  member   = local.ci_sa
}
```

### 5. `.gitignore` for Terraform

```
# infra/.gitignore
**/.terraform/
*.tfstate
*.tfstate.backup
*.tfplan
*.tfvars          # Exclude actual tfvars; commit only .tfvars.example
.terraform.lock.hcl  # Optionally commit this for reproducibility
```

## Acceptance Criteria

- [ ] PR to `main` touching `infra/terraform/**` triggers `terraform-pr-validation-*` Cloud Build job within 2 minutes of PR creation
- [ ] `terraform validate` step in CI pipeline returns exit code 0 for all current modules
- [ ] `terraform plan` step completes without error; plan artifact uploaded to `gs://smarthandoff-tf-state-staging/plans/`
- [ ] Failed `terraform validate` (e.g., syntax error) causes Cloud Build to fail and blocks PR merge (branch protection rule)
- [ ] Push to `main` triggers `terraform-apply-main-staging` which runs `terraform apply -auto-approve` and completes successfully
- [ ] CI service account has required IAM roles; `terraform apply` completes without permission errors in staging CI run
- [ ] `terraform plan` in CI outputs: "X to add, 0 to change, 0 to destroy" on a clean staging environment (verifies idempotency)

## Files to Create

```
.cloudbuild/terraform-pr.yaml
.cloudbuild/terraform-apply.yaml
infra/.gitignore
infra/terraform/environments/dev/terraform.tfvars.example
infra/BOOTSTRAP.md
```

## BOOTSTRAP.md Template

```markdown
# SmartHandoff Infrastructure Bootstrap

## One-Time Manual Steps (before first terraform apply)

### 1. Create GCP Projects
```bash
gcloud projects create smarthandoff-dev --name="SmartHandoff Dev"
gcloud projects create smarthandoff-staging --name="SmartHandoff Staging"
gcloud projects create smarthandoff-prod --name="SmartHandoff Production"
```

### 2. Enable Billing
Link each project to the billing account in GCP Console.

### 3. Create Terraform State Buckets
```bash
for ENV in dev staging prod; do
  gcloud storage buckets create gs://smarthandoff-tf-state-${ENV} \
    --project=smarthandoff-${ENV} \
    --location=us-central1 \
    --uniform-bucket-level-access
  gcloud storage buckets update gs://smarthandoff-tf-state-${ENV} --versioning
done
```

### 4. Update Secret Values
After `terraform apply`, replace placeholder secret values:
```bash
echo -n "actual-value" | gcloud secrets versions add smarthandoff-{secret-name}-{env} --data-file=-
```
```

## Notes

- `included_files = ["infra/terraform/**"]` ensures the Terraform CI trigger only fires when Terraform files change — not on application code PRs
- Consider adding `tfsec` or `checkov` as an additional step for Terraform security scanning (IaC SAST)
- Production `terraform apply` should require manual approval via Cloud Deploy delivery pipeline — not auto-apply from `main` branch push
