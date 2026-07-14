# networking module

Provisions the VPC network, subnets, Serverless VPC Access connector, Private Services Access
peering, and firewall rules for SmartHandoff.

## Resources Created

| Resource | Name pattern | Purpose |
|----------|-------------|---------|
| `google_compute_network` | `smarthandoff-vpc-{env}` | Custom-mode VPC — no auto subnets |
| `google_compute_subnetwork` services | `services-subnet-{env}` — `10.0.1.0/24` | Cloud Run VPC connector attachment point |
| `google_compute_subnetwork` data | `data-subnet-{env}` — `10.0.2.0/24` | Cloud SQL and Redis private IPs |
| `google_vpc_access_connector` | `smarthandoff-connector-{env}` — `10.8.0.0/28` | Serverless VPC Access for Cloud Run → data tier |
| `google_compute_global_address` | `smarthandoff-private-ip-{env}` | Reserved IP range for Cloud SQL private peering |
| `google_service_networking_connection` | — | Private Services Access peering for Cloud SQL |
| `google_compute_firewall` deny | `deny-data-ingress-{env}` | Block all internet ingress to `data-tier` tagged resources |
| `google_compute_firewall` allow | `allow-cloudrun-to-data-{env}` | Allow VPC connector → PostgreSQL (5432) + Redis (6379) |

## Inputs

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `project_id` | `string` | — | GCP project ID |
| `region` | `string` | `us-central1` | Region for subnet and connector |
| `environment` | `string` | — | `dev` \| `staging` \| `prod` |

## Outputs

| Name | Description |
|------|-------------|
| `vpc_id` | VPC network self-link |
| `vpc_name` | VPC network name |
| `services_subnet_id` | Services subnet self-link |
| `data_subnet_id` | Data subnet self-link |
| `vpc_connector_id` | Serverless VPC Access connector ID |
| `private_vpc_connection_id` | Private Services Access connection ID (required by `cloud_sql` module) |

## Notes

- `service_networking_connection` takes 10–15 minutes on first apply
- VPC connector `/28` range (`10.8.0.0/28`) must not overlap any subnet CIDR
- Both subnets have `private_ip_google_access = true` — Cloud Run can reach Google APIs without public IP
