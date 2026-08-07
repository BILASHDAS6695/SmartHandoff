# ADT Ingest Terraform Module

Provisions a Cloud Run Job + Cloud Scheduler cron that polls a FHIR R4 server for recently updated `Encounter` resources, detects ADT events, and broadcasts them via Azure SignalR Service to the SmartHandoff dashboard.

## Resources

- `google_service_account` — least-privilege SA for the job
- `google_cloud_run_v2_job` — `python -m app.jobs.run_adt_ingest`
- `google_cloud_scheduler_job` — triggers the job on a cron schedule

## Required Secret Manager secrets

| Secret | Purpose |
|--------|---------|
| `fhir-base-url-{env}` | FHIR R4 server base URL |
| `fhir-client-id-{env}` | SMART on FHIR client ID |
| `fhir-client-secret-{env}` | SMART on FHIR client secret |
| `db-password-{env}` | Cloud SQL password |
| `signalr-connection-string-{env}` | Azure SignalR connection string |

## Usage

```hcl
module "adt_ingest" {
  source = "../modules/adt_ingest"

  project_id     = var.project_id
  region         = var.region
  environment    = var.environment
  container_image = var.backend_image

  cloud_sql_connection_name = module.cloud_sql.connection_name
  db_name                   = var.db_name
  db_user                   = var.db_user
  db_password_secret_id     = "db-password-${var.environment}"

  fhir_base_url_secret_id      = "fhir-base-url-${var.environment}"
  fhir_client_id_secret_id     = "fhir-client-id-${var.environment}"
  fhir_client_secret_secret_id = "fhir-client-secret-${var.environment}"
  signalr_connection_string_secret_id = "signalr-connection-string-${var.environment}"
}
```
