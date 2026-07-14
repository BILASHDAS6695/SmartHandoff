# ── VPC ──────────────────────────────────────────────────────────────
resource "google_compute_network" "vpc" {
  name                    = "smarthandoff-vpc-${var.environment}"
  auto_create_subnetworks = false
  project                 = var.project_id
}

# ── Subnets ───────────────────────────────────────────────────────────
# Services subnet — Cloud Run VPC connector attaches here
resource "google_compute_subnetwork" "services" {
  name          = "services-subnet-${var.environment}"
  network       = google_compute_network.vpc.id
  region        = var.region
  ip_cidr_range = "10.0.1.0/24"
  project       = var.project_id

  private_ip_google_access = true
}

# Data subnet — Cloud SQL and Redis private IPs live here
resource "google_compute_subnetwork" "data" {
  name          = "data-subnet-${var.environment}"
  network       = google_compute_network.vpc.id
  region        = var.region
  ip_cidr_range = "10.0.2.0/24"
  project       = var.project_id

  private_ip_google_access = true
}

# ── VPC Connector ─────────────────────────────────────────────────────
# Bridges Cloud Run (serverless) to the data subnet over private IPs
resource "google_vpc_access_connector" "connector" {
  provider      = google-beta
  name          = "smarthandoff-connector-${var.environment}"
  region        = var.region
  project       = var.project_id
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.8.0.0/28" # /28 required; must not overlap any subnet
  min_instances = 2
  max_instances = 10
}

# ── Private Services Access (Cloud SQL private IP) ────────────────────
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

  depends_on = [google_compute_global_address.private_ip_range]
}

# ── Firewall Rules ────────────────────────────────────────────────────
# Block all inbound traffic to data-tier resources from the internet
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

# Allow Cloud Run services (routed through VPC connector) to reach data tier
resource "google_compute_firewall" "allow_cloudrun_to_data" {
  name    = "allow-cloudrun-to-data-${var.environment}"
  network = google_compute_network.vpc.name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["5432", "6379"] # PostgreSQL + Redis
  }

  direction   = "INGRESS"
  source_tags = ["vpc-connector"]
  target_tags = ["data-tier"]

  priority = 900
}
