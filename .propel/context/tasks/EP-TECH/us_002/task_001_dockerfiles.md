---
task_id: task_001
story_id: us_002
epic: EP-TECH
title: Dockerfile Templates for Python Services and Angular PWA
layer: Containerisation
effort_hours: 2
sequence: 1
status: Draft
---

# TASK-001: Dockerfile Templates for Python Services and Angular PWA

> **Story:** EP-TECH/US-002 | **Layer:** Containerisation | **Effort:** 2 hours | **Seq:** 1 of 7

## Objective

Create production-grade, security-hardened Dockerfile templates for two service categories: Python-based backend and agent services (FastAPI/LangChain), and the Angular 17 PWA. These are the artefacts that every CI/CD build step produces — correctness here directly determines image security posture and build reproducibility.

## Implementation Steps

### 1. Python Service Dockerfile (`docker/python-service/Dockerfile`)

Used by: `api-gateway`, `hl7-listener`, all 6 agent services, `ml-inference`, `notification-svc`

```dockerfile
# ── Stage 1: Build dependencies ──────────────────────────────────────
FROM python:3.12-slim AS builder

# Install build tools needed for native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy and install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime image ────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Security: run as non-root user
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false appuser

# Copy only installed packages from builder — not build tools
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY --chown=appuser:appgroup src/ ./src/

USER appuser

# Expose the Cloud Run expected port
EXPOSE 8080

# Health probe endpoint assumed at GET /health
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# Gunicorn with uvicorn workers — tuned for Cloud Run
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

CMD ["sh", "-c", \
     "gunicorn src.main:app \
      --worker-class uvicorn.workers.UvicornWorker \
      --workers 2 \
      --bind 0.0.0.0:${PORT} \
      --timeout 120 \
      --keepalive 5 \
      --access-logfile - \
      --error-logfile -"]
```

### 2. Agent Service Dockerfile (`docker/agent-service/Dockerfile`)

Agent services (LangChain-based) have the same structure but larger memory footprint and a different entrypoint (Pub/Sub pull loop, not HTTP):

```dockerfile
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime

RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false appuser

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=appuser:appgroup src/ ./src/

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

# Agents expose a minimal HTTP server for Cloud Run health probes
# The main loop is the Pub/Sub subscriber (started in main.py)
EXPOSE 8080

CMD ["python", "-m", "src.main"]
```

### 3. Angular PWA Dockerfile (`docker/angular-pwa/Dockerfile`)

```dockerfile
# ── Stage 1: Build ────────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files first for layer caching
COPY package.json package-lock.json ./
RUN npm ci --prefer-offline

# Copy source and build
COPY . .
RUN npm run build -- --configuration=production --output-path=dist/smarthandoff


# ── Stage 2: Nginx static server ─────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx config for Angular SPA routing
COPY docker/angular-pwa/nginx.conf /etc/nginx/conf.d/app.conf

# Copy Angular build artefacts
COPY --from=builder /app/dist/smarthandoff /usr/share/nginx/html

# Security: non-root nginx
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:8080/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
```

### 4. Nginx Config for Angular SPA (`docker/angular-pwa/nginx.conf`)

```nginx
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; connect-src 'self' https://api.smarthandoff.health wss://api.smarthandoff.health; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;" always;

    # Cache static assets with content-hash filenames
    location ~* \.(js|css|woff2?|ttf|eot|svg|png|ico)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # SPA routing — return index.html for all non-file paths
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Health probe endpoint
    location /health {
        access_log off;
        return 200 '{"status":"ok"}';
        add_header Content-Type application/json;
    }

    # Deny access to hidden files
    location ~ /\. {
        deny all;
    }
}
```

### 5. `.dockerignore` Templates

`docker/python-service/.dockerignore`:
```
.git/
.github/
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.coverage
htmlcov/
dist/
*.egg-info/
.venv/
.env
*.tfstate
infra/
docs/
tests/
```

`docker/angular-pwa/.dockerignore`:
```
.git/
.github/
node_modules/
dist/
.angular/
coverage/
*.tf
*.tfstate
infra/
docs/
```

## Acceptance Criteria

- [ ] `docker build -f docker/python-service/Dockerfile -t test-python-svc .` succeeds with zero warnings from a backend service directory
- [ ] Resulting image runs as UID 1001 (non-root): `docker run --rm test-python-svc id` returns `uid=1001(appuser)`
- [ ] Image does not contain build tools (`gcc`): `docker run --rm test-python-svc which gcc` returns exit code 1
- [ ] Angular build: `docker build -f docker/angular-pwa/Dockerfile -t test-pwa .` completes successfully; `curl http://localhost:8080/health` returns `{"status":"ok"}`
- [ ] Nginx security headers present: `curl -I http://localhost:8080` shows `X-Frame-Options: DENY` and `X-Content-Type-Options: nosniff`
- [ ] Images sizes: Python runtime image <200MB; Angular Nginx image <50MB (multi-stage build verified)

## Files to Create

```
docker/python-service/Dockerfile
docker/python-service/.dockerignore
docker/agent-service/Dockerfile
docker/agent-service/.dockerignore
docker/angular-pwa/Dockerfile
docker/angular-pwa/nginx.conf
docker/angular-pwa/.dockerignore
```

## Notes

- `python:3.12-slim` base avoids development tools present in `python:3.12`; eliminates common CVEs in build toolchains
- `--no-cache-dir` in pip install prevents pip cache being included in the image layer
- `gunicorn --workers 2` is appropriate for Cloud Run (2 vCPU); Cloud Run scales instances, not workers
- Multi-stage build is mandatory — single-stage would include gcc and build tools, dramatically increasing attack surface
