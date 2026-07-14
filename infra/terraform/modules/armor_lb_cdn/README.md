# armor_lb_cdn module

Provisions Cloud Armor WAF, HTTPS Global Load Balancer for the API Gateway,
HTTP → HTTPS redirect, TLS 1.2+ policy, and Cloud CDN backend for the Angular PWA.

## Resources Created

| Resource | Name | Purpose |
|----------|------|---------|
| `google_compute_security_policy` | `smarthandoff-api-waf-{env}` | Cloud Armor WAF with OWASP rules + rate limiting |
| `google_compute_ssl_policy` | `smarthandoff-tls-policy-{env}` | TLS MODERN profile (TLS 1.2 min, TLS 1.3 preferred) |
| `google_compute_global_address` | `smarthandoff-api-ip-{env}` | Static global IP for DNS A record |
| `google_compute_region_network_endpoint_group` | `api-gateway-neg-{env}` | Serverless NEG pointing at Cloud Run API Gateway |
| `google_compute_backend_service` | `api-gateway-backend-{env}` | Backend service with Cloud Armor attached |
| `google_compute_managed_ssl_certificate` | `smarthandoff-api-cert-{env}` | Auto-provisioned TLS certificate for `api_domain` |
| `google_compute_url_map` HTTPS | `smarthandoff-url-map-{env}` | Routes all traffic to API Gateway backend |
| `google_compute_target_https_proxy` | `smarthandoff-https-proxy-{env}` | TLS termination with managed cert |
| `google_compute_global_forwarding_rule` HTTPS | `smarthandoff-https-rule-{env}` | Listens on port 443 |
| `google_compute_url_map` HTTP redirect | `smarthandoff-http-redirect-{env}` | Redirects HTTP → HTTPS |
| `google_compute_global_forwarding_rule` HTTP | `smarthandoff-http-rule-{env}` | Listens on port 80, redirects to HTTPS |
| `google_compute_backend_bucket` | `smarthandoff-pwa-cdn-{env}` | Cloud CDN backend for Angular PWA assets |

## Cloud Armor Rules

| Priority | Action | Rule | Threat |
|----------|--------|------|--------|
| 1000 | deny(403) | `xss-stable` | Cross-Site Scripting |
| 1001 | deny(403) | `sqli-stable` | SQL Injection |
| 1002 | deny(403) | `rfi-stable` | Remote File Inclusion |
| 1003 | deny(403) | `lfi-stable` | Local File Inclusion |
| 2000 | throttle → 429 | 1,000 req/min/IP | Rate limiting (SEC-012) |
| 2147483647 | allow | `*` | Default allow |

## Inputs

| Name | Type | Description |
|------|------|-------------|
| `project_id` | `string` | GCP project ID |
| `region` | `string` | Region for Serverless NEG |
| `environment` | `string` | `dev` \| `staging` \| `prod` |
| `api_gateway_service_name` | `string` | Cloud Run API Gateway service name |
| `pwa_bucket_name` | `string` | Angular PWA bucket name (from storage module) |
| `api_domain` | `string` | API domain for managed SSL certificate |

## Outputs

| Name | Description |
|------|-------------|
| `load_balancer_ip` | Static IP — point your DNS A record here |
| `ssl_certificate_name` | Managed SSL cert name |
| `waf_policy_name` | Cloud Armor policy name |
| `pwa_cdn_backend_name` | Cloud CDN backend bucket name |

## Post-Apply Steps

1. **DNS:** Create an A record for `api_domain` → `load_balancer_ip`
2. **SSL provisioning:** Takes 10–60 minutes after DNS propagates.
   Check: `gcloud compute ssl-certificates describe smarthandoff-api-cert-{env}`
3. **Cloud Armor test:**
   ```bash
   curl -v "https://api.{env}.smarthandoff.health/api/v1/health?xss=<script>alert(1)</script>"
   # Expected: HTTP 403
   ```
