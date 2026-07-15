output "primary_connection_name" {
  description = "Cloud SQL primary connection name (for Cloud SQL Auth Proxy, if needed)"
  value       = google_sql_database_instance.primary.connection_name
}

output "primary_private_ip" {
  description = "Private IP address of the Cloud SQL primary instance"
  value       = google_sql_database_instance.primary.private_ip_address
}

output "replica_private_ip" {
  description = "Private IP address of the Cloud SQL read replica"
  value       = google_sql_database_instance.read_replica.private_ip_address
}

output "database_name" {
  description = "Application database name"
  value       = google_sql_database.app_db.name
}

output "db_user" {
  description = "Application database username"
  value       = google_sql_user.app_user.name
}

output "db_password_secret_id" {
  description = "Secret Manager secret ID for the DB password (without version)"
  value       = google_secret_manager_secret.db_password.secret_id
}

output "kms_key_ring_id" {
  description = "KMS key ring ID — passed to storage module for Cloud Storage CMEK"
  value       = google_kms_key_ring.sql_keyring.id
}

output "sql_cmek_key_id" {
  description = "KMS crypto key ID used for Cloud SQL disk encryption"
  value       = google_kms_crypto_key.sql_cmek.id
}
