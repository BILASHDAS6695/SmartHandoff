# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# SmartHandoff — BigQuery Nightly Export Job
# Cloud Run Job container; triggered by Cloud Scheduler at 02:00 UTC daily.
#
# Design refs:
#   design.md §3.1 — Cloud Run stateless jobs
#   US-062 — nightly BigQuery de-identified encounter export
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run Job executes the entrypoint directly (not a long-running server)
ENTRYPOINT ["python", "main.py"]
