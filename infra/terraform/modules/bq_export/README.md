# BigQuery Nightly Export Module

Provisions Cloud Run job and Cloud Scheduler trigger for the nightly de-identified encounter export to BigQuery.

## Resources

- Cloud Run V2 Job (bq-export)
- Cloud Scheduler Job (nightly trigger at 02:00 UTC)
- BigQuery Dataset (smarthandoff)
- Service Accounts (Cloud Run job SA + Cloud Scheduler invoker SA)
- IAM bindings (least-privilege access to Cloud SQL, Secret Manager, BigQuery)

## Input Variables

- `project_id` - GCP project ID
- `environment` - Deployment environment (dev/staging/prod)
- `region` - GCP region
- `container_image` - Container image URI for the Cloud Run job
- `cloud_sql_connection_name` - Cloud SQL connection name
- `db_name` - PostgreSQL database name
- `db_user` - PostgreSQL user
- `db_password_secret_id` - Secret Manager secret ID for DB password
- `deidentification_salt_secret_id` - Secret Manager secret ID for salt

## Outputs

- `cloud_run_job_name` - Name of the Cloud Run job
- `bq_export_sa_email` - Service account email
- `bigquery_dataset_id` - BigQuery dataset ID
- `scheduler_job_name` - Cloud Scheduler job name

## Design Notes

- Uses Secret Manager volume mounts for credentials (no plaintext env vars)
- Cloud SQL connection via Unix socket (/cloudsql mount)
- WRITE_TRUNCATE partition logic scoped to target date only (idempotent)
- Retry policy: 3 attempts with exponential backoff
- 10-minute timeout (should complete in <2 minutes normally)
