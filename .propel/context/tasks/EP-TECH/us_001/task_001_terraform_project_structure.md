---
task_id: task_001
story_id: us_001
epic: EP-TECH
title: Terraform Project Structure and GCS Remote State Backend
layer: IaC / Configuration
effort_hours: 2
sequence: 1
status: Implemented
---

# TASK-001: Terraform Project Structure and GCS Remote State Backend

> **Story:** EP-TECH/US-001 | **Layer:** IaC | **Effort:** 2 hours | **Seq:** 1 of 11

## Objective

Bootstrap the Terraform workspace with the correct module structure, variable schema, and a GCS remote state backend with versioning — before any resource definitions are written.

## Implementation Steps

### 1. Directory Structure

Create the following layout:

```
infra/
├── terraform/
│   ├── environments/
│   │   ├── dev/
│   │   │   ├── main.tf          # Root module for dev
│   │   │   ├── terraform.tfvars # Dev-specific variable values
│   │   │   └── backend.tf       # GCS backend for dev state
│   │   ├── staging/
│   │   │   ├── main.tf
│   │   │   ├── terraform.tfvars
│   │   │   └── backend.tf
│   │   └── prod/
│   │       ├── main.tf
│   │       ├── terraform.tfvars
│   │       └── backend.tf
│   └── modules/
│       ├── networking/          # Task 002
│       ├── cloud_run/           # Task 003
│       ├── cloud_sql/           # Task 004
│       ├── pubsub/              # Task 005
│       ├── storage/             # Task 006
│       ├── redis/               # Task 007
│       ├── secrets/             # Task 008
│       ├── armor_lb_cdn/        # Task 009
│       └── monitoring/          # Task 010
```

### 2. GCS State Backend Bucket

Manually create the state bucket (bootstrap step — not managed by Terraform itself):

```bash
gcloud storage buckets create gs://smarthandoff-tf-state-{env} \
  --project={GCP_PROJECT_ID} \
  --location=us-central1 \
  --uniform-bucket-level-access \
  --versioning
```

Document this as a **one-time bootstrap** in the project README.

### 3. Root Backend Configuration (`environments/dev/backend.tf`)

```hcl
terraform {
  backend "gcs" {
    bucket  = "smarthandoff-tf-state-dev"
    prefix  = "terraform/state"
  }
}
```

### 4. Provider and Version Constraints (`environments/dev/main.tf`)

```hcl
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}
```

### 5. Root Variables (`environments/dev/variables.tf`)

```hcl
variable "project_id"   { type = string }
variable "region"        { type = string  default = "us-central1" }
variable "environment"   { type = string  description = "dev|staging|prod" }
```

### 6. `terraform.tfvars` for Dev

```hcl
project_id  = "smarthandoff-dev"
region      = "us-central1"
environment = "dev"
```

### 7. Module Interface Convention

Each module must expose:
- `variables.tf` — typed inputs with descriptions
- `outputs.tf` — all IDs/names that other modules need
- `main.tf` — resource definitions only (no providers)
- `README.md` — one-paragraph description + input/output table

## Acceptance Criteria

- [x] `infra/terraform/` directory structure matches spec above
- [ ] `terraform init` in `environments/dev/` succeeds and connects to GCS backend *(requires GCS bucket — see BOOTSTRAP.md Step 1)*
- [ ] GCS state bucket exists with versioning enabled *(requires GCS bucket — see BOOTSTRAP.md Step 1)*
- [x] `terraform validate` passes with empty module stubs in place
- [x] `.gitignore` excludes: `.terraform/`, `*.tfstate`, `*.tfstate.backup`, `*.tfplan`, `terraform.tfvars`

## Files to Create

```
infra/terraform/environments/dev/backend.tf
infra/terraform/environments/dev/main.tf
infra/terraform/environments/dev/variables.tf
infra/terraform/environments/dev/terraform.tfvars.example  (commit example; exclude actual .tfvars)
infra/terraform/environments/staging/  (same structure)
infra/terraform/environments/prod/     (same structure)
infra/terraform/modules/.gitkeep       (placeholder until Task 002)
infra/.gitignore
```

## Verification Command

```bash
cd infra/terraform/environments/dev
terraform init
terraform validate
# Expected: "Success! The configuration is valid."
```

## Notes

- GCS state bucket creation is a **manual bootstrap step** — it cannot be managed by the same Terraform that uses it
- Use separate state buckets per environment: `smarthandoff-tf-state-dev`, `smarthandoff-tf-state-staging`, `smarthandoff-tf-state-prod`
- CI/CD service account must have `storage.objectAdmin` on the state bucket (Task 011)
