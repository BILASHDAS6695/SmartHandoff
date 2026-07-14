output "hl7_archive_bucket" {
  description = "Name of the HL7 raw message archive bucket (HIPAA CMEK, 7-year retention)"
  value       = google_storage_bucket.hl7_archive.name
}

output "audit_export_bucket" {
  description = "Name of the audit log WORM export bucket (HIPAA CMEK, 6-year retention)"
  value       = google_storage_bucket.audit_export.name
}

output "ml_models_bucket" {
  description = "Name of the ML model artefacts bucket"
  value       = google_storage_bucket.ml_models.name
}

output "angular_pwa_bucket" {
  description = "Name of the Angular PWA static assets bucket (CDN-served)"
  value       = google_storage_bucket.angular_pwa.name
}

output "pwa_bucket_url" {
  description = "gs:// URL of the Angular PWA bucket (input for Cloud CDN backend bucket)"
  value       = google_storage_bucket.angular_pwa.url
}
