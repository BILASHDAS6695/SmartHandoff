---
task_id: task_010
story_id: us_001
epic: EP-TECH
title: Environment Root Module — Wire All Modules Together
layer: IaC / Integration
effort_hours: 1.5
sequence: 10
status: Draft
---

# TASK-010: Environment Root Module — Wire All Modules Together

> **Story:** EP-TECH/US-001 | **Layer:** IaC / Integration | **Effort:** 1.5 hours | **Seq:** 10 of 11

## Objective

Complete the `environments/dev/main.tf` root module by wiring all 8 sub-modules together, passing outputs as inputs between modules, defining the complete variable schema, and verifying that a single `terraform apply` provisions the full stack from a clean state.

## Implementation Steps

### 1. Complete `environments/dev/main.tf`

```hcl
# ──────────────────────────────────────────
# 1. Project APIs
# ──────────────────────────────────────────
resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com", "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com", "sqladmin.googleapis.com",
    "redis.googleapis.com", "run.googleapis.com",
    "pubsub.googleapis.com", "secretmanager.googleapis.com",
    "monitoring.googleapis.com", "cloudtrace.googleapis.com",
    "artifactregistry.googleapis.com", "cloudbuild.googleapis.com",
    "clouddeploy.googleapis.com", "cloudkms.googleapis.com",
    "bigquery.googleapis.com", "cloudscheduler.googleapis.com",
  ])
  service            = each.value
  project            = var.project_id
  disable_on_destroy = false
}

# ──────────────────────────────────────────
# 2. Networking
# ──────────────────────────────────────────
module "networking" {
  source      = "../../modules/networking"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  depends_on  = [google_project_service.apis]
}

# ──────────────────────────────────────────
# 3. Cloud Run Services (with service accounts)
# ──────────────────────────────────────────
module "cloud_run" {
  source      = "../../modules/cloud_run"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  vpc_connector_id = module.networking.vpc_connector_id
  depends_on       = [module.networking]
}

# ──────────────────────────────────────────
# 4. Cloud SQL (depends on networking peering)
# ──────────────────────────────────────────
module "cloud_sql" {
  source      = "../../modules/cloud_sql"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  vpc_id                    = module.networking.vpc_id
  private_vpc_connection_id = module.networking.private_vpc_connection_id
  kms_key_ring_id           = module.secrets.kms_key_ring_id

  depends_on = [module.networking, module.secrets]
}

# ──────────────────────────────────────────
# 5. Pub/Sub
# ──────────────────────────────────────────
module "pubsub" {
  source      = "../../modules/pubsub"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  project_number         = data.google_project.project.number
  hl7_listener_sa        = module.cloud_run.service_accounts["hl7-listener"]
  agent_service_accounts = module.cloud_run.service_accounts

  depends_on = [module.cloud_run]
}

# ──────────────────────────────────────────
# 6. Cloud Storage
# ──────────────────────────────────────────
module "storage" {
  source      = "../../modules/storage"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  kms_key_ring_id       = module.secrets.kms_key_ring_id
  hl7_listener_sa       = module.cloud_run.service_accounts["hl7-listener"]
  api_gateway_sa        = module.cloud_run.service_accounts["api-gateway"]
  agent_service_accounts = module.cloud_run.service_accounts

  depends_on = [module.cloud_run, module.secrets]
}

# ──────────────────────────────────────────
# 7. Redis + Load Balancer + CDN
# ──────────────────────────────────────────
module "redis" {
  source      = "../../modules/redis"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
  vpc_id      = module.networking.vpc_id

  depends_on = [module.networking]
}

module "armor_lb_cdn" {
  source      = "../../modules/armor_lb_cdn"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  api_gateway_service_name = "api-gateway-${var.environment}"
  pwa_bucket_name          = module.storage.angular_pwa_bucket
  api_domain               = var.api_domain

  depends_on = [module.cloud_run, module.storage]
}

# ──────────────────────────────────────────
# 8. Secrets
# ──────────────────────────────────────────
module "secrets" {
  source      = "../../modules/secrets"
  project_id  = var.project_id
  environment = var.environment
  service_accounts = module.cloud_run.service_accounts

  # DB password created in cloud_sql module — cross-reference
  # db_password_secret_id provided as input after cloud_sql creates it

  depends_on = [module.cloud_run]
}

# ──────────────────────────────────────────
# 9. Monitoring
# ──────────────────────────────────────────
module "monitoring" {
  source      = "../../modules/monitoring"
  project_id  = var.project_id
  environment = var.environment
  api_domain  = var.api_domain
  oncall_email = var.oncall_email

  depends_on = [module.armor_lb_cdn]
}

data "google_project" "project" { project_id = var.project_id }
```

### 2. Complete Variable Definitions (`environments/dev/variables.tf`)

```hcl
variable "project_id"    { type = string }
variable "region"         { type = string  default = "us-central1" }
variable "environment"    { type = string  description = "dev|staging|prod" }
variable "api_domain"     { type = string  description = "API domain e.g. api.dev.smarthandoff.health" }
variable "portal_domain"  { type = string  description = "Portal domain e.g. portal.dev.smarthandoff.health" }
variable "oncall_email"   { type = string  description = "On-call alert email address" }
```

### 3. Root Outputs (`environments/dev/outputs.tf`)

```hcl
output "api_gateway_url"       { value = module.cloud_run.api_gateway_url }
output "load_balancer_ip"      { value = module.armor_lb_cdn.load_balancer_ip }
output "cloud_sql_primary_ip"  { value = module.cloud_sql.primary_private_ip }
output "cloud_sql_replica_ip"  { value = module.cloud_sql.replica_private_ip }
output "redis_host"            { value = module.redis.redis_host  sensitive = true }
output "hl7_archive_bucket"    { value = module.storage.hl7_archive_bucket }
output "adt_events_topic"      { value = module.pubsub.adt_events_topic_id }
output "service_accounts"      { value = module.cloud_run.service_accounts }
```

## Full `terraform apply` Validation Procedure

```bash
cd infra/terraform/environments/dev

# 1. Initialise with GCS backend
terraform init -backend-config="bucket=smarthandoff-tf-state-dev"

# 2. Validate all modules
terraform validate

# 3. Plan — review all resources to be created
terraform plan -out=tfplan.dev

# 4. Apply — should create ~80-100 resources
terraform apply tfplan.dev

# 5. Verify key resources
gcloud sql instances list --project=$PROJECT_ID
gcloud run services list --region=us-central1 --project=$PROJECT_ID
gcloud pubsub topics list --project=$PROJECT_ID
gcloud secrets list --project=$PROJECT_ID

# 6. Test destroy (dev/staging only — NOT production)
terraform destroy -auto-approve
# Verify: no orphaned resources remain in GCP Console
```

## Acceptance Criteria (US-001 AC-1, AC-2, AC-3, AC-4, AC-5, AC-6)

- [ ] **AC-1:** `terraform apply` from clean state creates all resources: 10 Cloud Run services, Cloud SQL HA + replica, 4 Pub/Sub topics + 7 subscriptions, VPC + 2 subnets + VPC connector, Redis, 4 Cloud Storage buckets, Cloud CDN + Armor + HTTPS LB, Secret Manager (21 secrets), Cloud Monitoring (6 alert policies + uptime check)
- [ ] **AC-2:** `gcloud run services describe docs-agent-dev --region=us-central1 --format=json | jq '.spec.template.spec.containers[0].resources.limits'` returns `{"memory": "4Gi", "cpu": "2000m"}`
- [ ] **AC-3:** `gcloud sql instances describe smarthandoff-pg-dev --format=json | jq '.settings.ipConfiguration.ipv4Enabled'` returns `false`
- [ ] **AC-4:** `terraform destroy -auto-approve` completes without errors; `gcloud run services list --region=us-central1` shows zero SmartHandoff services
- [ ] **AC-5:** `terraform state list` shows `backend = "gcs"`; `gcloud storage ls gs://smarthandoff-tf-state-dev/terraform/state/` shows state files with version history
- [ ] **AC-6:** `terraform validate` and `terraform plan` return zero errors in CI (Task 011)

## Files to Update

```
infra/terraform/environments/dev/main.tf       (complete with all module calls)
infra/terraform/environments/dev/variables.tf  (complete variable schema)
infra/terraform/environments/dev/outputs.tf    (all key outputs)
infra/terraform/environments/staging/main.tf   (copy of dev with staging-specific tfvars)
infra/BOOTSTRAP.md                             (documents manual bootstrap steps)
```

## Notes

- Module dependency chain: APIs → Networking → Cloud Run (service accounts) → Pub/Sub + Storage + Redis → Secrets (uses SA emails) → Monitoring
- `depends_on` at module level handles ordering; Terraform cannot infer cross-module implicit deps reliably for IAM bindings
- `terraform plan` will show `~80-100 resources to add` on first run — review carefully before `apply`
- `BOOTSTRAP.md` must document the two manual prerequisites: GCS state bucket creation + GCP project + billing activation
