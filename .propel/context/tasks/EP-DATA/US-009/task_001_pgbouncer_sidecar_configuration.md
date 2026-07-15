---
id: TASK-001
title: "Configure PgBouncer Sidecar — `pgbouncer.ini`, Dockerfile, and Cloud Run Multi-Container Manifest"
user_story: US-009
epic: EP-DATA
sprint: 1
layer: Infrastructure / Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-001]
---

# TASK-001: Configure PgBouncer Sidecar — `pgbouncer.ini`, Dockerfile, and Cloud Run Multi-Container Manifest

> **Story:** US-009 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Infrastructure / Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

Cloud SQL PostgreSQL enforces a hard server-side connection limit. Without a connection pooler, 500 concurrent FastAPI workers would each hold a persistent session, exhausting the database. PgBouncer in **transaction-pool mode** multiplexes up to 500 client connections onto a small pool of real server-side connections (default_pool_size=20), so the Cloud SQL instance sees at most ~50 server connections regardless of load.

The US-009 Technical Notes mandate PgBouncer as a **Cloud Run multi-container sidecar** — a second container in the same service that listens on localhost port 5432, proxying connections to Cloud SQL. The application container connects to `localhost:5432` rather than the Cloud SQL private IP directly. This keeps network latency near-zero and requires no VPC routing change.

PgBouncer credentials (the `pgbouncer` OS user's password and the application DB user's password) must be stored in **GCP Secret Manager**, not in container images or environment variables committed to version control.

This task covers three deliverables:
1. `backend/pgbouncer/pgbouncer.ini` — PgBouncer configuration file
2. `backend/pgbouncer/Dockerfile` — minimal image built from `bitnami/pgbouncer`
3. `deploy/cloudrun/api-gateway.yaml` — Cloud Run multi-container service manifest with PgBouncer sidecar

---

## Acceptance Criteria Addressed

| US-009 AC | Requirement |
|---|---|
| **Scenario 1** | PgBouncer enforces max 500 client connections; Cloud SQL shows ≤50 server-side connections |
| **DoD** | PgBouncer deployed as sidecar; `pool_mode=transaction`, `max_client_conn=500`, `default_pool_size=20` |

---

## Implementation Steps

### 1. Create `backend/pgbouncer/pgbouncer.ini`

```ini
; PgBouncer configuration for SmartHandoff API Gateway sidecar.
;
; Security note: PGBOUNCER_PASSWORD and APPLICATION_DB_PASSWORD are
; injected at runtime via Cloud Run secret environment variables.
; Do NOT hard-code passwords in this file.
;
; References:
;   TR-009: ≤500 simultaneous DB connections
;   ADR-002: Cloud Run multi-container (sidecar pattern)

[databases]
; "smarthandoff" is the logical database name the application connects to.
; PgBouncer resolves it to the Cloud SQL private IP at runtime.
; CLOUD_SQL_PRIMARY_HOST injected via env var in Cloud Run manifest.
smarthandoff = host=$(CLOUD_SQL_PRIMARY_HOST) port=5432 dbname=smarthandoff

[pgbouncer]
; ── Pool settings ────────────────────────────────────────────────────
; transaction mode: connection returned to pool after each transaction (not session)
pool_mode = transaction

; Max client-side connections this PgBouncer instance will accept
max_client_conn = 500

; Real server-side connections per (db, user) pair
; API Gateway service runs with 2 min / 20 max instances → at most 20×20=400 server
; connections across the fleet; per TR-009 we cap at default_pool_size=20 per pod
default_pool_size = 20

; Reserve pool for burst headroom
reserve_pool_size = 5
reserve_pool_timeout = 3

; Queue client connections that exceed pool capacity (don't reject immediately)
; Max wait before rejecting: 10 seconds
server_connect_timeout = 10
client_login_timeout = 10

; ── Authentication ────────────────────────────────────────────────────
; md5 authentication (PgBouncer ↔ PostgreSQL)
; HBA-style auth to clients connecting from localhost (Cloud Run containers)
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt

; ── Listen address ────────────────────────────────────────────────────
; Sidecar listens on localhost only — not exposed outside the Cloud Run pod
listen_addr = 127.0.0.1
listen_port = 5432

; ── Logging ───────────────────────────────────────────────────────────
; Log to stdout for Cloud Logging capture; no PHI in PgBouncer logs
log_connections = 0
log_disconnections = 0
log_pooler_errors = 1
verbose = 0

; ── Admin interface ──────────────────────────────────────────────────
; Admin console for pgbouncer SHOW POOLS; restricted to pgbouncer OS user
admin_users = pgbouncer_admin
stats_users = pgbouncer_admin

; ── TLS to Cloud SQL ─────────────────────────────────────────────────
; Cloud SQL requires TLS for private IP connections
server_tls_sslmode = require
```

> **Note on `userlist.txt`:** PgBouncer loads credentials from `/etc/pgbouncer/userlist.txt`. The file format is `"username" "md5-hash-or-plaintext-password"`. In the Cloud Run sidecar, a Cloud Run entrypoint script (see Step 3) writes this file at container startup using secrets injected as environment variables, so no credentials are baked into the image.

### 2. Create `backend/pgbouncer/Dockerfile`

Use Bitnami's official `pgbouncer` image to avoid building from scratch. The entrypoint script writes `userlist.txt` from injected secrets at startup.

```dockerfile
# PgBouncer sidecar image for SmartHandoff Cloud Run multi-container deployment.
#
# Build: docker build -t pgbouncer-sidecar backend/pgbouncer/
# Base:  bitnami/pgbouncer (includes glibc, openssl — no root required)
#
# Secrets injected at runtime (Cloud Run secret env vars):
#   PGBOUNCER_AUTH_USER      — the application DB username (e.g. "smarthandoff_app")
#   PGBOUNCER_AUTH_PASSWORD  — the application DB user's password
#   CLOUD_SQL_PRIMARY_HOST   — private IP of the Cloud SQL primary instance

FROM bitnami/pgbouncer:1.22.1

# Copy configuration template (env vars substituted at startup by entrypoint)
COPY pgbouncer.ini /etc/pgbouncer/pgbouncer.ini.template

# Startup script: writes userlist.txt from injected secrets, then execs pgbouncer
COPY entrypoint.sh /entrypoint.sh

USER 0
RUN chmod +x /entrypoint.sh
USER 1001

EXPOSE 5432

ENTRYPOINT ["/entrypoint.sh"]
```

### 3. Create `backend/pgbouncer/entrypoint.sh`

This script runs as the container ENTRYPOINT. It writes `userlist.txt` from secrets injected via environment variables (never stored in the image), substitutes `CLOUD_SQL_PRIMARY_HOST` into the config template, then execs PgBouncer.

```bash
#!/bin/sh
# PgBouncer sidecar entrypoint.
# Writes userlist.txt from injected Cloud Run secret env vars at startup.
# Substitutes CLOUD_SQL_PRIMARY_HOST into pgbouncer.ini before starting.
#
# Required env vars (injected by Cloud Run secret bindings):
#   PGBOUNCER_AUTH_USER       — DB username
#   PGBOUNCER_AUTH_PASSWORD   — DB password (plaintext; PgBouncer hashes internally)
#   CLOUD_SQL_PRIMARY_HOST    — Cloud SQL primary private IP

set -e

# Validate required environment variables
: "${PGBOUNCER_AUTH_USER:?PGBOUNCER_AUTH_USER must be set}"
: "${PGBOUNCER_AUTH_PASSWORD:?PGBOUNCER_AUTH_PASSWORD must be set}"
: "${CLOUD_SQL_PRIMARY_HOST:?CLOUD_SQL_PRIMARY_HOST must be set}"

# Write userlist.txt — format: "username" "plaintext-password"
# PgBouncer md5 auth reads from this file.
cat > /etc/pgbouncer/userlist.txt <<EOF
"${PGBOUNCER_AUTH_USER}" "${PGBOUNCER_AUTH_PASSWORD}"
"pgbouncer_admin" "${PGBOUNCER_ADMIN_PASSWORD:-pgbouncer_admin_local}"
EOF

# Substitute CLOUD_SQL_PRIMARY_HOST into the config template
envsubst '${CLOUD_SQL_PRIMARY_HOST}' \
  < /etc/pgbouncer/pgbouncer.ini.template \
  > /etc/pgbouncer/pgbouncer.ini

echo "PgBouncer starting — primary host: ${CLOUD_SQL_PRIMARY_HOST}"
exec pgbouncer /etc/pgbouncer/pgbouncer.ini
```

> **Security:** `userlist.txt` is written to the container's in-memory tmpfs at runtime. The secrets are never written to the image layer or to persistent storage. PgBouncer must not be rebuilt when passwords rotate — rotation only requires updating the Secret Manager version and redeploying.

### 4. Create `deploy/cloudrun/api-gateway.yaml` — Multi-Container Service Manifest

Cloud Run multi-container support (`--container` flag or YAML manifest) allows the PgBouncer sidecar to run alongside the FastAPI application container in the same service.

```yaml
# Cloud Run multi-container service manifest for api-gateway.
# PgBouncer sidecar proxies connections from the FastAPI container to Cloud SQL.
#
# Deploy:
#   gcloud run services replace deploy/cloudrun/api-gateway.yaml \
#     --project=$PROJECT_ID --region=us-central1
#
# References:
#   ADR-002: Cloud Run stateless hosting
#   TR-009: ≤500 client connections via PgBouncer transaction-pool mode
#   TR-022: Cloud SQL behind VPC; no public DB exposure

apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: api-gateway
  annotations:
    run.googleapis.com/launch-stage: BETA  # Required for multi-container
spec:
  template:
    metadata:
      annotations:
        # Min instances: 2 for API latency (TR-013)
        autoscaling.knative.dev/minScale: "2"
        autoscaling.knative.dev/maxScale: "20"
        # VPC connector for Cloud SQL private IP access (TR-022)
        run.googleapis.com/vpc-access-connector: projects/${PROJECT_ID}/locations/us-central1/connectors/smarthandoff-vpc-connector
        run.googleapis.com/vpc-access-egress: private-ranges-only
    spec:
      containerConcurrency: 100
      timeoutSeconds: 300
      serviceAccountName: api-gateway-sa@${PROJECT_ID}.iam.gserviceaccount.com

      containers:
        # ── Primary container: FastAPI application ────────────────────
        - name: api-gateway
          image: us-central1-docker.pkg.dev/${PROJECT_ID}/smarthandoff/api-gateway:${IMAGE_TAG}
          ports:
            - name: http1
              containerPort: 8080
          resources:
            limits:
              cpu: "2"
              memory: 2Gi
          env:
            # Application connects to PgBouncer on localhost (write=primary, read=replica)
            - name: PRIMARY_DATABASE_URL
              value: "postgresql+asyncpg://$(PGBOUNCER_AUTH_USER):$(PGBOUNCER_AUTH_PASSWORD)@127.0.0.1:5432/smarthandoff"
            - name: REPLICA_DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: smarthandoff-replica-db-url-prod
                  key: latest
            - name: ENVIRONMENT
              value: production
          envFrom: []
          volumeMounts:
            - name: app-secrets
              mountPath: /secrets
              readOnly: true
          startupProbe:
            httpGet:
              path: /ready
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            periodSeconds: 10

        # ── Sidecar container: PgBouncer ──────────────────────────────
        - name: pgbouncer
          image: us-central1-docker.pkg.dev/${PROJECT_ID}/smarthandoff/pgbouncer-sidecar:latest
          resources:
            limits:
              cpu: "0.5"
              memory: 256Mi
          env:
            - name: PGBOUNCER_AUTH_USER
              valueFrom:
                secretKeyRef:
                  name: smarthandoff-db-user-prod
                  key: latest
            - name: PGBOUNCER_AUTH_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: smarthandoff-db-password-prod
                  key: latest
            - name: CLOUD_SQL_PRIMARY_HOST
              valueFrom:
                secretKeyRef:
                  name: smarthandoff-cloudsql-primary-host-prod
                  key: latest
            - name: PGBOUNCER_ADMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: smarthandoff-pgbouncer-admin-password-prod
                  key: latest
          # Sidecar not exposed externally; only the api-gateway container is
          # reachable via the service URL
```

### 5. Provision Required Secret Manager Secrets

The following secrets must exist before deploying. Add them to the Terraform `secrets` module or provision manually for initial dev:

| Secret Name (prod) | Content | Created By |
|---|---|---|
| `smarthandoff-db-user-prod` | `smarthandoff_app` (DB username) | Terraform / manual |
| `smarthandoff-db-password-prod` | App user password | Terraform / manual |
| `smarthandoff-cloudsql-primary-host-prod` | Private IP of Cloud SQL primary | Terraform output |
| `smarthandoff-pgbouncer-admin-password-prod` | PgBouncer admin user password | Terraform / manual |
| `smarthandoff-replica-db-url-prod` | Full async DSN for read replica | TASK-002 |

### 6. Verify PgBouncer Is Running (Smoke Test)

After deployment, connect to PgBouncer's admin console from within the running container to confirm pool configuration:

```bash
# Exec into the running api-gateway Cloud Run instance (requires Cloud Run exec access)
gcloud beta run services exec api-gateway \
  --project=$PROJECT_ID --region=us-central1 \
  --container=pgbouncer \
  -- psql -h 127.0.0.1 -p 5432 -U pgbouncer_admin pgbouncer -c "SHOW POOLS;"
```

Expected output contains `pool_mode=transaction` and `cl_active ≤ 500`.

---

## File Checklist

| File | Action |
|---|---|
| `backend/pgbouncer/pgbouncer.ini` | Create |
| `backend/pgbouncer/Dockerfile` | Create |
| `backend/pgbouncer/entrypoint.sh` | Create |
| `deploy/cloudrun/api-gateway.yaml` | Create |

---

## Dependencies

- **US-001** — Cloud SQL primary and replica must be provisioned and their private IPs known
- **TASK-002** — Read replica DSN (`smarthandoff-replica-db-url-prod` secret) created by the session factory task
