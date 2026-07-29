output "cloud_run_job_name" {
  description = "Name of the Cloud Run job resource"
  value       = google_cloud_run_v2_job.bq_export.name
}

output "bq_export_sa_email" {
  description = "Email of the BigQuery export Cloud Run job service account"
  value       = google_service_account.bq_export.email
}

output "bigquery_dataset_id" {
  description = "BigQuery dataset ID for the de-identified analytics dataset"
  value       = google_bigquery_dataset.smarthandoff.dataset_id
}

output "scheduler_job_name" {
  description = "Name of the Cloud Scheduler job that triggers the nightly export"
  value       = google_cloud_scheduler_job.bq_export_nightly.name
}
