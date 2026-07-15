output "load_balancer_ip" {
  description = "Global static IP address of the HTTPS Load Balancer (point DNS A record here)"
  value       = google_compute_global_address.api_ip.address
}

output "ssl_certificate_name" {
  description = "Managed SSL certificate name (status visible in GCP Console after DNS propagation)"
  value       = google_compute_managed_ssl_certificate.api_cert.name
}

output "waf_policy_name" {
  description = "Cloud Armor security policy name"
  value       = google_compute_security_policy.api_waf.name
}

output "pwa_cdn_backend_name" {
  description = "Cloud CDN backend bucket name"
  value       = google_compute_backend_bucket.pwa_cdn.name
}
