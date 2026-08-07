output "job_name" {
  description = "Name of the ADT ingest Cloud Run job"
  value       = google_cloud_run_v2_job.adt_ingest.name
}

output "scheduler_job_name" {
  description = "Name of the Cloud Scheduler job that triggers ADT ingest"
  value       = google_cloud_scheduler_job.adt_ingest.name
}

output "service_account_email" {
  description = "Email of the ADT ingest job service account"
  value       = google_service_account.adt_ingest.email
}
