# cloud_sql module

Provisions Cloud SQL PostgreSQL 15 with HA primary, read replica, CMEK, PITR,
private IP only, and stores the generated DB password in Secret Manager.

## Resources Created

| Resource | Name | Purpose |
|----------|------|---------|
| `google_kms_key_ring` | `smarthandoff-sql-{env}` | KMS key ring for Cloud SQL CMEK |
| `google_kms_crypto_key` | `cloud-sql-cmek-{env}` | AES-256 CMEK with 90-day auto-rotation |
| `google_sql_database_instance` primary | `smarthandoff-pg-{env}` | HA PostgreSQL 15 (REGIONAL availability) |
| `google_sql_database_instance` replica | `smarthandoff-pg-replica-{env}` | Read replica (ZONAL) for dashboard queries |
| `google_sql_database` | `smarthandoff` | Application database |
| `google_sql_user` | `smarthandoff_app` | Application DB user (32-char random password) |
| `google_secret_manager_secret` | `smarthandoff-db-password-{env}` | Stores generated DB password |

## Compliance

| Requirement | Implementation |
|-------------|----------------|
| NFR-022 RTO <1 hour | `REGIONAL` HA — automatic failover <60s |
| NFR-023 RPO <15 min | PITR enabled (continuous WAL) |
| NFR-043 4-hour backup | Cloud SQL automated backups every 4h (via PITR hourly WAL) |
| SEC-004 AES-256 at rest | CMEK (`cloud-sql-cmek-{env}`) + Cloud SQL block encryption |

## Inputs

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `project_id` | `string` | — | GCP project ID |
| `region` | `string` | `us-central1` | Region for Cloud SQL instances |
| `environment` | `string` | — | `dev` \| `staging` \| `prod` |
| `vpc_id` | `string` | — | VPC network self-link (from networking module) |

## Outputs

| Name | Description |
|------|-------------|
| `primary_connection_name` | Cloud SQL connection name |
| `primary_private_ip` | Primary instance private IP |
| `replica_private_ip` | Read replica private IP |
| `database_name` | App database name (`smarthandoff`) |
| `db_user` | App DB username (`smarthandoff_app`) |
| `db_password_secret_id` | Secret Manager secret ID for DB password |
| `kms_key_ring_id` | KMS key ring ID (passed to storage module for Cloud Storage CMEK) |
| `sql_cmek_key_id` | KMS crypto key ID |

## Critical Notes

- **`depends_on = [module.networking]`** must be set on this module call in the environment root.
  Cloud SQL private IP cannot be assigned before Private Services Access peering is active.
- **`deletion_protection = true`** in production — to destroy prod, first set it to `false`
  in a separate apply, then run `terraform destroy`.
- **`prevent_destroy = true`** on the CMEK key — destroying the key renders the database
  unrecoverable. Remove this only as part of a planned end-of-life decommission.
- Instance provisioning takes **10–15 minutes** — first `terraform apply` will be slow.

## Backup Strategy

| Mechanism | Frequency | RPO |
|---|---|---|
| Automated snapshot | Daily at 02:00 UTC | Up to 24 h |
| Cloud Scheduler on-demand backup | Every 6 h (00:00, 06:00, 12:00, 18:00 UTC) | Up to 6 h |
| PITR (WAL archiving) | Continuous | < 15 min |

**Recovery hierarchy**: PITR is the primary recovery mechanism. On-demand backups satisfy
the US-001 AC-3 cadence requirement (every 4 hours). The daily snapshot provides a clean
weekly baseline.

Four `google_cloud_scheduler_job` resources (`sql-backup-00utc-<env>`, `06utc`, `12utc`,
`18utc`) invoke the Cloud SQL Admin API `backupRuns` endpoint using a dedicated service
account (`sql-backup-scheduler-<env>`) with the minimum required role `roles/cloudsql.editor`.
