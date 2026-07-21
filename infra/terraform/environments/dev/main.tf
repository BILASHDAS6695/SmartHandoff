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

# ── Module references ──────────────────────────────────────────────────
# Modules are added as they are implemented (Tasks 002–010).
# See infra/BOOTSTRAP.md for first-run instructions.

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

  # Reuse the KMS key ring created by the cloud_sql module
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
