output "secret_ids" {
  description = "Map of logical secret name to Secret Manager resource ID (projects/{proj}/secrets/{id}). Marked sensitive — use -json flag to view."
  value       = { for k, v in google_secret_manager_secret.secrets : k => v.id }
  sensitive   = true
}

output "secret_names" {
  description = "Map of logical secret name to Secret Manager secret_id (short name). Consumed by the cloud_run module for secret_key_ref mounts."
  value       = { for k, v in google_secret_manager_secret.secrets : k => v.secret_id }
}
