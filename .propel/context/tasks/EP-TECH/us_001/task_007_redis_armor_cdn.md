---
task_id: task_007
story_id: us_001
epic: EP-TECH
title: Cloud Memorystore Redis and Cloud Armor + HTTPS Load Balancer + CDN
layer: Cache / WAF / CDN
effort_hours: 2
sequence: 7
status: Implemented
---

# TASK-007: Cloud Memorystore Redis and Cloud Armor + HTTPS Load Balancer + CDN

> **Story:** EP-TECH/US-001 | **Layer:** Cache / WAF / CDN | **Effort:** 2 hours | **Seq:** 7 of 11

## Objective

Provision Cloud Memorystore Redis 7 (for token blocklist, drug interaction cache, conversation history), Cloud Armor WAF with OWASP rules, HTTPS Load Balancer for API Gateway, and Cloud CDN for the Angular PWA static assets.

## Part A — Cloud Memorystore Redis

### Redis Instance (`modules/redis/main.tf`)

```hcl
resource "google_redis_instance" "cache" {
  name           = "smarthandoff-redis-${var.environment}"
  tier           = "STANDARD_HA"  # Standard tier with HA failover
  memory_size_gb = 2
  region         = var.region
  project        = var.project_id

  authorized_network = var.vpc_id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  redis_version      = "REDIS_7_0"

  display_name = "SmartHandoff Cache (${var.environment})"

  redis_configs = {
    "maxmemory-policy" = "allkeys-lru"  # Evict LRU keys when memory full
    "notify-keyspace-events" = "Ex"     # Keyspace events for expiry notifications
  }

  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time { hours = 2; minutes = 0 }
    }
  }
}

output "redis_host" { value = google_redis_instance.cache.host }
output "redis_port" { value = google_redis_instance.cache.port }
```

---

## Part B — Cloud Armor + HTTPS Load Balancer + CDN

### 1. Cloud Armor Security Policy (`modules/armor_lb_cdn/main.tf`)

```hcl
resource "google_compute_security_policy" "api_waf" {
  name    = "smarthandoff-api-waf-${var.environment}"
  project = var.project_id

  # OWASP ModSecurity Core Rule Set — XSS, SQLi, LFI, RFI, RCE
  rule {
    action   = "deny(403)"
    priority = 1000
    match {
      expr { expression = "evaluatePreconfiguredExpr('xss-stable')" }
    }
    description = "Block XSS attacks"
  }

  rule {
    action   = "deny(403)"
    priority = 1001
    match {
      expr { expression = "evaluatePreconfiguredExpr('sqli-stable')" }
    }
    description = "Block SQL injection"
  }

  rule {
    action   = "deny(403)"
    priority = 1002
    match {
      expr { expression = "evaluatePreconfiguredExpr('rfi-stable')" }
    }
    description = "Block Remote File Inclusion"
  }

  rule {
    action   = "deny(403)"
    priority = 1003
    match {
      expr { expression = "evaluatePreconfiguredExpr('lfi-stable')" }
    }
    description = "Block Local File Inclusion"
  }

  # Rate limiting — 1,000 req/min per IP (SEC-012)
  rule {
    action   = "throttle"
    priority = 2000
    match    { versioned_expr = "SRC_IPS_V1"; config { src_ip_ranges = ["*"] } }
    rate_limit_options {
      rate_limit_threshold { count = 1000; interval_sec = 60 }
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
    }
    description = "Rate limit: 1000 req/min per IP"
  }

  # Default allow
  rule {
    action   = "allow"
    priority = 2147483647
    match    { versioned_expr = "SRC_IPS_V1"; config { src_ip_ranges = ["*"] } }
    description = "Default allow"
  }
}
```

### 2. HTTPS Load Balancer for API Gateway

```hcl
# Serverless NEG for Cloud Run API Gateway
resource "google_compute_region_network_endpoint_group" "api_neg" {
  name                  = "api-gateway-neg-${var.environment}"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run { service = var.api_gateway_service_name }
}

# Backend service with Cloud Armor
resource "google_compute_backend_service" "api_backend" {
  name    = "api-gateway-backend-${var.environment}"
  project = var.project_id

  protocol    = "HTTPS"
  timeout_sec = 30

  backend {
    group = google_compute_region_network_endpoint_group.api_neg.id
  }

  security_policy = google_compute_security_policy.api_waf.id

  log_config {
    enable      = true
    sample_rate = 1.0  # 100% request logging
  }
}

# Managed SSL Certificate
resource "google_compute_managed_ssl_certificate" "api_cert" {
  name    = "smarthandoff-api-cert-${var.environment}"
  project = var.project_id

  managed { domains = [var.api_domain] }
}

# URL Map
resource "google_compute_url_map" "api_url_map" {
  name            = "smarthandoff-url-map-${var.environment}"
  project         = var.project_id
  default_service = google_compute_backend_service.api_backend.id
}

# HTTPS Proxy
resource "google_compute_target_https_proxy" "api_https_proxy" {
  name             = "smarthandoff-https-proxy-${var.environment}"
  project          = var.project_id
  url_map          = google_compute_url_map.api_url_map.id
  ssl_certificates = [google_compute_managed_ssl_certificate.api_cert.id]

  ssl_policy = google_compute_ssl_policy.modern_tls.id
}

# TLS 1.3 Policy
resource "google_compute_ssl_policy" "modern_tls" {
  name            = "smarthandoff-tls-policy-${var.environment}"
  project         = var.project_id
  profile         = "MODERN"  # TLS 1.2 minimum; TLS 1.3 preferred
  min_tls_version = "TLS_1_2"
}

# Global Forwarding Rule
resource "google_compute_global_forwarding_rule" "api_https" {
  name       = "smarthandoff-https-rule-${var.environment}"
  project    = var.project_id
  target     = google_compute_target_https_proxy.api_https_proxy.id
  port_range = "443"
  ip_address = google_compute_global_address.api_ip.address
}

resource "google_compute_global_address" "api_ip" {
  name    = "smarthandoff-api-ip-${var.environment}"
  project = var.project_id
}
```

### 3. Cloud CDN for Angular PWA

```hcl
resource "google_compute_backend_bucket" "pwa_cdn" {
  name        = "smarthandoff-pwa-cdn-${var.environment}"
  project     = var.project_id
  bucket_name = var.pwa_bucket_name

  enable_cdn = true

  cdn_policy {
    cache_mode        = "CACHE_ALL_STATIC"
    client_ttl        = 31536000  # 1 year (content-hashed filenames)
    default_ttl       = 3600
    max_ttl           = 31536000
    serve_while_stale = 86400
  }
}
```

### 4. Outputs

```hcl
output "load_balancer_ip"   { value = google_compute_global_address.api_ip.address }
output "redis_host"         { value = google_redis_instance.cache.host }
output "redis_port"         { value = google_redis_instance.cache.port }
```

## Acceptance Criteria

- [ ] Redis instance created in `us-central1` with private IP in VPC; no public endpoint; `tier: STANDARD_HA`
- [ ] Cloud Armor policy has 4 OWASP rules (XSS, SQLi, RFI, LFI) + rate limit rule (1000/min)
- [ ] HTTPS Load Balancer has managed SSL certificate for API domain; TLS policy set to MODERN (TLS 1.2 minimum)
- [ ] Cloud CDN backend bucket configured with `cache_mode: CACHE_ALL_STATIC` for Angular assets
- [ ] `curl -I https://api.{env}.smarthandoff.health/health` returns `200 OK` with `strict-transport-security` header (after DNS configured)
- [ ] Cloud Armor test: `curl` with XSS payload in query string → returns `403 Forbidden`

## Files to Create

```
infra/terraform/modules/redis/main.tf
infra/terraform/modules/redis/variables.tf
infra/terraform/modules/redis/outputs.tf
infra/terraform/modules/armor_lb_cdn/main.tf
infra/terraform/modules/armor_lb_cdn/variables.tf
infra/terraform/modules/armor_lb_cdn/outputs.tf
infra/terraform/modules/armor_lb_cdn/README.md
```

## Notes

- Cloud Armor is only available for **global** load balancers (not regional) — confirms the use of `google_compute_global_forwarding_rule`
- Managed SSL certificate provisioning takes 10–60 minutes after DNS is pointed at the load balancer IP
- Redis `STANDARD_HA` tier provides automatic failover within the same region; connects only via private IP in VPC
- Cloud Armor rate limiting `throttle` action (not `deny`) allows burst traffic while queuing excess requests with 429 response
