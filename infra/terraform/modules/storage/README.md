# storage module

Provisions the four Cloud Storage buckets required by SmartHandoff, a shared
Cloud Storage CMEK key (reusing the Cloud SQL KMS key ring), and all IAM bindings.

## Buckets

| Bucket | Pattern | Class | Retention | CMEK | Public |
|--------|---------|-------|-----------|------|--------|
| `smarthandoff-hl7-archive-{project}-{env}` | Regional | STANDARD → NEARLINE 90d → COLDLINE 1yr | 7 years (locked in prod) | ✓ | ✗ |
| `smarthandoff-audit-export-{project}-{env}` | Regional | STANDARD → COLDLINE 6mo | 6 years (locked in prod) | ✓ | ✗ |
| `smarthandoff-ml-models-{project}-{env}` | Regional | STANDARD | None (keep last 3 versions) | ✗ | ✗ |
| `smarthandoff-pwa-{project}-{env}` | Multi-regional (US) | STANDARD | None | ✗ | ✓ (objectViewer) |

## Inputs

| Name | Type | Description |
|------|------|-------------|
| `project_id` | `string` | GCP project ID |
| `region` | `string` | Region for regional buckets (default: `us-central1`) |
| `environment` | `string` | `dev` \| `staging` \| `prod` |
| `kms_key_ring_id` | `string` | KMS key ring ID from `cloud_sql` module (reused for storage CMEK) |
| `hl7_listener_sa` | `string` | HL7 Listener SA email (objectCreator on HL7 archive) |
| `api_gateway_sa` | `string` | API Gateway SA email (objectCreator on audit export) |
| `agent_service_accounts` | `map(string)` | Agent SA map (objectViewer on ML models) |

## Outputs

| Name | Description |
|------|-------------|
| `hl7_archive_bucket` | HL7 archive bucket name |
| `audit_export_bucket` | Audit export bucket name |
| `ml_models_bucket` | ML models bucket name |
| `angular_pwa_bucket` | Angular PWA bucket name |
| `pwa_bucket_url` | `gs://` URL for Cloud CDN backend bucket |

## Critical Notes

### Retention Lock (`is_locked`)

`retention_policy.is_locked = true` on HL7 archive and audit export buckets is **irreversible** —
once applied, the retention period cannot be reduced and the lock cannot be removed.

- **dev / staging:** `is_locked = false` (allows `terraform destroy` and bucket cleanup)
- **prod:** `is_locked = true` (HIPAA compliance — BR-022, BR-023)

This is controlled by `var.environment == "prod"` in the HCL.

### CMEK

The `cloud-storage-cmek-{env}` key is created in this module but shares the **key ring**
provisioned by the `cloud_sql` module (`kms_key_ring_id` output). This avoids
creating a second key ring per environment.

### Angular PWA Public Access

`allUsers objectViewer` on the Angular PWA bucket is intentional. The Angular application
is public static HTML/JS/CSS with no PHI. All data access is through the API Gateway, which
enforces JWT authentication.
