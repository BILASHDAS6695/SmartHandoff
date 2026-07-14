---
task_id: task_002
story_id: us_001
epic: EP-TECH
title: VPC Networking — Subnets, Firewall Rules, and VPC Connector
layer: Networking
effort_hours: 2
sequence: 2
status: Implemented
---

# TASK-002: VPC Networking — Subnets, Firewall Rules, and VPC Connector

> **Story:** EP-TECH/US-001 | **Layer:** Networking | **Effort:** 2 hours | **Seq:** 2 of 11

## Objective

Create the `networking` Terraform module that provisions the VPC, two subnets (services + data), firewall rules enforcing zero public access to the data tier, and a VPC connector enabling Cloud Run services to reach Cloud SQL and Redis on private IPs.

## Implementation Steps

### 1. Module File: `modules/networking/main.tf`

```hcl
resource "google_compute_network" "vpc" {
  name                    = "smarthandoff-vpc-${var.environment}"
  auto_create_subnetworks = false
  project                 = var.project_id
}

# Services subnet — Cloud Run VPC connector attaches here
resource "google_compute_subnetwork" "services" {
  name          = "services-subnet-${var.environment}"
  network       = google_compute_network.vpc.id
  region        = var.region
  ip_cidr_range = "10.0.1.0/24"
  project       = var.project_id

  private_ip_google_access = true
}

# Data subnet — Cloud SQL and Redis private IPs
resource "google_compute_subnetwork" "data" {
  name          = "data-subnet-${var.environment}"
  network       = google_compute_network.vpc.id
  region        = var.region
  ip_cidr_range = "10.0.2.0/24"
  project       = var.project_id

  private_ip_google_access = true
}

# VPC Connector — bridges Cloud Run to data subnet
resource "google_vpc_access_connector" "connector" {
  provider      = google-beta
  name          = "smarthandoff-connector-${var.environment}"
  region        = var.region
  project       = var.project_id
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.8.0.0/28"  # /28 required by VPC Connector
  min_instances = 2
  max_instances = 10
}

# Private Services Access — required for Cloud SQL private IP
resource "google_compute_global_address" "private_ip_range" {
  name          = "smarthandoff-private-ip-${var.environment}"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
  project       = var.project_id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
}

# Firewall: deny all ingress to data subnet from internet
resource "google_compute_firewall" "deny_data_subnet_ingress" {
  name    = "deny-data-ingress-${var.environment}"
  network = google_compute_network.vpc.name
  project = var.project_id

  deny { protocol = "all" }

  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["data-tier"]

  priority = 1000
}

# Firewall: allow Cloud Run services (via VPC connector) to reach data tier
resource "google_compute_firewall" "allow_cloudrun_to_data" {
  name    = "allow-cloudrun-to-data-${var.environment}"
  network = google_compute_network.vpc.name
  project = var.project_id

  allow { protocol = "tcp"; ports = ["5432", "6379"] }  # PostgreSQL + Redis

  direction   = "INGRESS"
  source_tags = ["vpc-connector"]
  target_tags = ["data-tier"]

  priority = 900
}
```

### 2. Module Variables (`modules/networking/variables.tf`)

```hcl
variable "project_id"   { type = string }
variable "region"        { type = string }
variable "environment"   { type = string }
```

### 3. Module Outputs (`modules/networking/outputs.tf`)

```hcl
output "vpc_id"              { value = google_compute_network.vpc.id }
output "vpc_name"            { value = google_compute_network.vpc.name }
output "services_subnet_id"  { value = google_compute_subnetwork.services.id }
output "data_subnet_id"      { value = google_compute_subnetwork.data.id }
output "vpc_connector_id"    { value = google_vpc_access_connector.connector.id }
```

### 4. Wire into Environment Root (`environments/dev/main.tf` addition)

```hcl
module "networking" {
  source      = "../../modules/networking"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
}
```

### 5. Required APIs to Enable (one-time, done via gcloud or Terraform)

```hcl
resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "redis.googleapis.com",
    "run.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "clouddeploy.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}
```

## Acceptance Criteria

- [ ] `terraform apply` creates: 1 VPC, 2 subnets (`10.0.1.0/24` services, `10.0.2.0/24` data), 1 VPC connector (`10.8.0.0/28`), 2 firewall rules, 1 private services access peering
- [ ] `gcloud compute networks subnets list --project={PROJECT}` shows both subnets with `privateIpGoogleAccess: true`
- [ ] VPC connector status: `gcloud compute networks vpc-access connectors describe smarthandoff-connector-dev --region=us-central1` shows `state: READY`
- [ ] Firewall rule `deny-data-ingress-*` appears with priority 1000 and `action: DENY`
- [ ] Cloud SQL (provisioned in Task 004) receives no public IP; only accessible via private IP on `10.0.2.0/24`

## Files to Create

```
infra/terraform/modules/networking/main.tf
infra/terraform/modules/networking/variables.tf
infra/terraform/modules/networking/outputs.tf
infra/terraform/modules/networking/README.md
infra/terraform/environments/dev/apis.tf   (project API enablement)
```

## Notes

- The VPC connector `/28` range (`10.8.0.0/28`) must not overlap with any subnet CIDR
- `private_ip_google_access = true` on subnets allows Cloud Run services to reach Google APIs without public IP
- `service_networking_connection` creation can take 10–15 minutes — factor into first `terraform apply` runtime
