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
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
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

data "google_project" "project" {
  project_id = var.project_id
}

# ── Networking ───────────────────────────────────────────────────────────
module "networking" {
  source      = "../../modules/networking"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  depends_on = [google_project_service.apis]
}

# ── Cloud Run Services ────────────────────────────────────────────────────
module "cloud_run" {
  source           = "../../modules/cloud_run"
  project_id       = var.project_id
  region           = var.region
  environment      = var.environment
  vpc_connector_id = module.networking.vpc_connector_id

  depends_on = [module.networking]
}

# ── Pub/Sub ────────────────────────────────────────────────────────────
module "pubsub" {
  source      = "../../modules/pubsub"
  project_id  = var.project_id
  environment = var.environment

  project_number         = module.cloud_run.project_number
  hl7_listener_sa        = module.cloud_run.service_accounts["hl7-listener"]
  agent_service_accounts = module.cloud_run.service_accounts

  depends_on = [module.cloud_run]
}

# ── Cloud SQL ──────────────────────────────────────────────────────────
module "cloud_sql" {
  source      = "../../modules/cloud_sql"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
  vpc_id      = module.networking.vpc_id

  depends_on = [module.networking]
}

# ── Cloud Storage ─────────────────────────────────────────────────────
module "storage" {
  source      = "../../modules/storage"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  kms_key_ring_id = module.cloud_sql.kms_key_ring_id

  hl7_listener_sa        = module.cloud_run.service_accounts["hl7-listener"]
  api_gateway_sa         = module.cloud_run.service_accounts["api-gateway"]
  agent_service_accounts = module.cloud_run.service_accounts

  depends_on = [module.cloud_sql, module.cloud_run]
}

# ── Redis (Cloud Memorystore) ────────────────────────────────────────────
module "redis" {
  source      = "../../modules/redis"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
  vpc_id      = module.networking.vpc_id

  depends_on = [module.networking]
}
# ── Secret Manager ─────────────────────────────────────────────────────
module "secrets" {
  source      = "../../modules/secrets"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  # Reuse the KMS crypto key already created by the cloud_sql module for CMEK encryption
  kms_key_id = module.cloud_sql.sql_cmek_key_id

  # Grant each Cloud Run service account access to its required secrets
  service_accounts = module.cloud_run.service_accounts

  depends_on = [module.cloud_run, module.cloud_sql]
}
# ── Cloud Armor + Load Balancer + CDN ─────────────────────────────────
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
# ── Artifact Registry ────────────────────────────────────────────────
resource "google_artifact_registry_repository" "container_images" {
  location      = var.region
  repository_id = "smarthandoff-${var.environment}"
  format        = "DOCKER"
  project       = var.project_id

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  depends_on = [google_project_service.apis]
}

locals {
  cicd_services = toset([
    "api-gateway", "hl7-listener", "coordinator-agent", "docs-agent",
    "medrecon-agent", "comms-agent", "ml-inference", "notification-svc",
    "audit-svc", "portal-bff",
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

  included_files = [
    "services/${each.key}/**",
    ".cloudbuild/**",
    "cloudbuild-shared.yaml",
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

  depends_on = [google_project_service.apis, google_artifact_registry_repository.container_images]
}

module "monitoring" {
  source      = "../../modules/monitoring"
  project_id  = var.project_id
  environment = var.environment
  region      = var.region

  project_number      = module.cloud_run.project_number
  api_domain          = var.api_domain
  oncall_email        = var.oncall_email
  slack_alert_channel = var.slack_alert_channel
  cloudbuild_sa_email = var.cloudbuild_sa_email

  depends_on = [google_project_service.apis, google_cloudbuild_trigger.main_push]
}