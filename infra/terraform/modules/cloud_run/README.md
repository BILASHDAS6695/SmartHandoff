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
- Secret Manager bindings inject credentials via `value_source.secret_key_ref` (no plaintext
  credentials in any env block — satisfies US-001 AC-4 / Scenario 4).

## Health Probes

All 10 services configure three probes per container:

| Probe | Purpose | hl7-listener | All other services |
|-------|---------|-------------|-------------------|
| `liveness_probe` | Restart container on deadlock (3 failures) | `tcp_socket` port 2575 | `GET /health` |
| `startup_probe` | Block traffic during cold start (12×5s = 60s) | `tcp_socket` port 2575 | `GET /ready` |
| `readiness_probe` | Shed traffic when dependencies unavailable (3 failures) | `tcp_socket` port 2575 | `GET /ready` |

`hl7-listener` is a raw TCP MLLP server (port 2575) with no HTTP listener — HTTP probes would
cause a crash loop. `dynamic` conditional blocks select the correct probe type per service.

The 60-second `startup_probe` window (`failure_threshold=12`, `period_seconds=5`) accommodates
slow LangChain framework initialisation for `docs-agent`, `medrecon-agent`, `coordinator-agent`,
and `ml-inference`.

## Multi-Zone Deployment

Cloud Run (fully managed) automatically distributes instances across multiple availability
zones within the configured region. Zone scheduling is managed by the Google Cloud platform
and cannot be overridden at the service level.

Verified region: `us-central1` (zones: us-central1-a, us-central1-b, us-central1-c,
us-central1-f). Services with `min_instance_count ≥ 2` (e.g., `api-gateway`) maintain warm
instances in ≥2 zones at all times.

**Do not** add `zones` or node affinity annotations to `google_cloud_run_v2_service` resources
— they are not valid fields and will cause `terraform validate` errors.
