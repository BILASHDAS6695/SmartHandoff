output "job_name" {
  description = "Name of the scheduled notification dispatcher Cloud Run job"
  value       = google_cloud_run_v2_job.scheduled_notifications.name
}

output "scheduler_job_name" {
  description = "Name of the Cloud Scheduler job that triggers the dispatcher"
  value       = google_cloud_scheduler_job.scheduled_notifications.name
}

output "service_account_email" {
  description = "Email of the scheduled notification dispatcher service account"
  value       = google_service_account.scheduled_notifications.email
}
