# cloud_run module

Provisions all 10 SmartHandoff Cloud Run v2 services with dedicated service accounts,
correct resource sizing, VPC connector bindings, health probes, and IAM.

## Service Sizing (Design §9.2)

| Service | Min | Max | CPU | Memory | Concurrency |
|---------|-----|-----|-----|--------|-------------|
| `api-gateway` | 2 | 20 | 2000m | 2Gi | 100 |
| `hl7-listener` | 1 | 10 | 1000m | 512Mi | 50 |
| `coordinator-agent` | 1 | 10 | 2000m | 2Gi | 20 |
| `docs-agent` | 1 | 10 | 2000m | 4Gi | 5 |
| `medrecon-agent` | 1 | 10 | 2000m | 2Gi | 10 |
| `bed-mgmt-agent` | 1 | 5 | 1000m | 1Gi | 20 |
| `followup-agent` | 1 | 10 | 1000m | 1Gi | 20 |
| `comms-agent` | 1 | 10 | 2000m | 2Gi | 10 |
| `ml-inference` | 1 | 5 | 2000m | 2Gi | 50 |
| `notification-svc` | 1 | 5 | 1000m | 512Mi | 50 |

## Inputs

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `project_id` | `string` | — | GCP project ID |
| `region` | `string` | `us-central1` | Deployment region |
| `environment` | `string` | — | `dev` \| `staging` \| `prod` |
| `vpc_connector_id` | `string` | — | Serverless VPC Access connector ID (from networking module) |

## Outputs

| Name | Description |
|------|-------------|
| `service_urls` | Map of `service-name → Cloud Run URI` |
| `service_accounts` | Map of `service-name → service account email` |
| `api_gateway_url` | URI of the public API Gateway |
| `project_number` | Numeric project number (used by downstream IAM bindings) |

## IAM Model

- `api-gateway` — `roles/run.invoker` for `allUsers` (public LB access)
- All agent services — `roles/run.invoker` on `api-gateway` (service-to-service)
- Cloud Build service account — `roles/run.developer` on all services (CI/CD deployment)
- All other services — **internal only** (`INGRESS_TRAFFIC_INTERNAL_ONLY`)

## Notes

- Placeholder image (`us-docker.pkg.dev/cloudrun/container/hello`) is used at provision time.
  CI/CD (Cloud Deploy) replaces the image on first real deployment.
- `lifecycle.ignore_changes` on `image` prevents Terraform from reverting CI/CD deployments.
- `cpu_idle = false` on `api-gateway`, `hl7-listener`, `coordinator-agent` keeps CPU allocated
  to eliminate cold-start latency on the critical path.
- Secret Manager bindings are added to each service in Task 008.
