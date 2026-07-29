"""API Gateway configuration and settings.

Loads environment variables from GCP Secret Manager (mounted at runtime).
All secrets should be injected via environment variables, never hardcoded.
"""
from __future__ import annotations

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for the API Gateway service.

    All secrets are sourced from GCP Secret Manager and injected as
    environment variables at Cloud Run startup.
    """

    # ── OTP & Portal Auth (US-052) ────────────────────────────────────────────
    # HS256 secrets for signing and validating JWTs
    PORTAL_TOKEN_SECRET: str = os.environ.get(
        "PORTAL_TOKEN_SECRET",
        "dev-portal-token-secret-min32chars-xxxxx",
    )
    PATIENT_JWT_SECRET: str = os.environ.get(
        "PATIENT_JWT_SECRET",
        "dev-patient-jwt-secret-min32chars-xxxxxx",
    )

    # Notification Service endpoint (US-064) for OTP delivery via Twilio
    NOTIFICATION_SERVICE_URL: str = os.environ.get(
        "NOTIFICATION_SERVICE_URL",
        "http://notification-svc:8080",
    )
    NOTIFICATION_SERVICE_TIMEOUT_SECONDS: int = int(
        os.environ.get("NOTIFICATION_SERVICE_TIMEOUT_SECONDS", "10")
    )

    # ── Redis (shared across services) ────────────────────────────────────────
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # ── GCP Project Configuration ─────────────────────────────────────────────
    GCP_PROJECT_ID: str = os.environ.get("GCP_PROJECT_ID", "smarthandoff-dev")
    VERTEX_AI_LOCATION: str = os.environ.get("VERTEX_AI_LOCATION", "us-central1")

    # ── Existing JWT (staff auth) ─────────────────────────────────────────────
    JWT_SIGNING_KEY: str = os.environ.get("JWT_SIGNING_KEY", "dev-jwt-key")

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
