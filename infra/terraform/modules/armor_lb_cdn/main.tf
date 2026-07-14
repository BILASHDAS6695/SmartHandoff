# ── Cloud Armor WAF Security Policy ───────────────────────────────────────
resource "google_compute_security_policy" "api_waf" {
  name    = "smarthandoff-api-waf-${var.environment}"
  project = var.project_id
  type    = "CLOUD_ARMOR"

  # OWASP preconfigured rulesets (stable versions) — OWASP Top 10 coverage
  rule {
    action      = "deny(403)"
    priority    = 1000
    description = "Block XSS attacks"
    match {
      expr { expression = "evaluatePreconfiguredExpr('xss-stable')" }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 1001
    description = "Block SQL injection"
    match {
      expr { expression = "evaluatePreconfiguredExpr('sqli-stable')" }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 1002
    description = "Block Remote File Inclusion"
    match {
      expr { expression = "evaluatePreconfiguredExpr('rfi-stable')" }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 1003
    description = "Block Local File Inclusion"
    match {
      expr { expression = "evaluatePreconfiguredExpr('lfi-stable')" }
    }
  }

  # Rate limiting — 1,000 req/min per IP (SEC-012)
  # `throttle` queues excess requests with 429 rather than hard-blocking them
  rule {
    action      = "throttle"
    priority    = 2000
    description = "Rate limit: 1000 req/min per IP"
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      rate_limit_threshold {
        count        = 1000
        interval_sec = 60
      }
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
    }
  }

  # Default allow — must be the lowest-priority rule
  rule {
    action      = "allow"
    priority    = 2147483647
    description = "Default allow"
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
  }
}

# ── TLS Policy (TLS 1.2 minimum, TLS 1.3 preferred) ──────────────────────
resource "google_compute_ssl_policy" "modern_tls" {
  name            = "smarthandoff-tls-policy-${var.environment}"
  project         = var.project_id
  profile         = "MODERN"  # Enables TLS 1.2 + TLS 1.3, disables weak ciphers
  min_tls_version = "TLS_1_2"
}

# ── Static Global IP for the Load Balancer ────────────────────────────────
resource "google_compute_global_address" "api_ip" {
  name    = "smarthandoff-api-ip-${var.environment}"
  project = var.project_id
}

# ── Serverless NEG for Cloud Run API Gateway ─────────────────────────────
resource "google_compute_region_network_endpoint_group" "api_neg" {
  name                  = "api-gateway-neg-${var.environment}"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = var.api_gateway_service_name
  }
}

# ── Backend Service with Cloud Armor attached ────────────────────────────
resource "google_compute_backend_service" "api_backend" {
  name    = "api-gateway-backend-${var.environment}"
  project = var.project_id

  protocol              = "HTTPS"
  timeout_sec           = 30
  load_balancing_scheme = "EXTERNAL_MANAGED"

  backend {
    group = google_compute_region_network_endpoint_group.api_neg.id
  }

  security_policy = google_compute_security_policy.api_waf.id

  log_config {
    enable      = true
    sample_rate = 1.0 # 100% request logging for security audit
  }
}

# ── Managed SSL Certificate ─────────────────────────────────────────────
resource "google_compute_managed_ssl_certificate" "api_cert" {
  name    = "smarthandoff-api-cert-${var.environment}"
  project = var.project_id

  managed {
    domains = [var.api_domain]
  }
}

# ── URL Map ───────────────────────────────────────────────────────────────
resource "google_compute_url_map" "api_url_map" {
  name            = "smarthandoff-url-map-${var.environment}"
  project         = var.project_id
  default_service = google_compute_backend_service.api_backend.id
}

# ── HTTPS Proxy ────────────────────────────────────────────────────────────
resource "google_compute_target_https_proxy" "api_https_proxy" {
  name             = "smarthandoff-https-proxy-${var.environment}"
  project          = var.project_id
  url_map          = google_compute_url_map.api_url_map.id
  ssl_certificates = [google_compute_managed_ssl_certificate.api_cert.id]
  ssl_policy       = google_compute_ssl_policy.modern_tls.id
}

# ── Global HTTPS Forwarding Rule ───────────────────────────────────────────
resource "google_compute_global_forwarding_rule" "api_https" {
  name                  = "smarthandoff-https-rule-${var.environment}"
  project               = var.project_id
  target                = google_compute_target_https_proxy.api_https_proxy.id
  port_range            = "443"
  ip_address            = google_compute_global_address.api_ip.address
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# HTTP → HTTPS redirect
resource "google_compute_url_map" "http_redirect" {
  name    = "smarthandoff-http-redirect-${var.environment}"
  project = var.project_id

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "http_proxy" {
  name    = "smarthandoff-http-proxy-${var.environment}"
  project = var.project_id
  url_map = google_compute_url_map.http_redirect.id
}

resource "google_compute_global_forwarding_rule" "api_http" {
  name                  = "smarthandoff-http-rule-${var.environment}"
  project               = var.project_id
  target                = google_compute_target_http_proxy.http_proxy.id
  port_range            = "80"
  ip_address            = google_compute_global_address.api_ip.address
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# ── Cloud CDN for Angular PWA Static Assets ─────────────────────────────
resource "google_compute_backend_bucket" "pwa_cdn" {
  name        = "smarthandoff-pwa-cdn-${var.environment}"
  project     = var.project_id
  bucket_name = var.pwa_bucket_name
  enable_cdn  = true

  cdn_policy {
    cache_mode        = "CACHE_ALL_STATIC"
    client_ttl        = 31536000  # 1 year — Angular uses content-hashed filenames
    default_ttl       = 3600
    max_ttl           = 31536000
    serve_while_stale = 86400
  }
}
