# ── HL7 Listener → HL7 archive (write-only — no delete) ───────────────
resource "google_storage_bucket_iam_member" "hl7_archive_writer" {
  bucket = google_storage_bucket.hl7_archive.name
  role   = "roles/storage.objectCreator" # Creator only — cannot read or delete objects
  member = "serviceAccount:${var.hl7_listener_sa}"
}

# ── All agent SAs → ML models bucket (read at startup) ────────────────
resource "google_storage_bucket_iam_member" "ml_model_readers" {
  for_each = var.agent_service_accounts

  bucket = google_storage_bucket.ml_models.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${each.value}"
}

# ── API Gateway SA → audit export bucket (write audit log exports) ────
resource "google_storage_bucket_iam_member" "audit_export_writer" {
  bucket = google_storage_bucket.audit_export.name
  role   = "roles/storage.objectCreator" # Creator only — immutable WORM pattern
  member = "serviceAccount:${var.api_gateway_sa}"
}

# ── Cloud CDN / public → Angular PWA bucket (serve static assets) ─────
# Angular PWA assets are public non-PHI content. API calls are JWT-protected.
resource "google_storage_bucket_iam_member" "pwa_public_read" {
  bucket = google_storage_bucket.angular_pwa.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}
