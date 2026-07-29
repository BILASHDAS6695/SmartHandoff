"""Runtime configuration for the BigQuery nightly export job.

All values are injected via environment variables set by Cloud Run / Cloud Scheduler.
No hardcoded credentials — secrets come from GCP Secret Manager mounts.

Design refs:
    design.md §4.1 — GCP Secret Manager for credentials
    US-062 Technical Notes — Cloud Run job; Cloud Scheduler trigger
"""
from __future__ import annotations

import os


class Config:
    """Centralised config resolved from environment variables at startup."""

    # GCP project hosting BigQuery dataset
    GCP_PROJECT_ID: str = os.environ["GCP_PROJECT_ID"]

    # BigQuery target dataset and table
    BQ_DATASET: str = os.getenv("BQ_DATASET", "smarthandoff")
    BQ_TABLE: str = os.getenv("BQ_TABLE", "encounters_deidentified")

    # Cloud SQL connection (Unix socket injected by Cloud Run SQL connector)
    DB_HOST: str = os.getenv("DB_HOST", "/cloudsql")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_NAME: str = os.environ["DB_NAME"]
    DB_USER: str = os.environ["DB_USER"]
    # DB_PASSWORD mounted from Secret Manager at /secrets/db-password
    DB_PASSWORD_FILE: str = os.getenv(
        "DB_PASSWORD_FILE", "/secrets/db-password"
    )

    # De-identification salt (rotated monthly; mounted from Secret Manager)
    DEIDENTIFICATION_SALT_FILE: str = os.getenv(
        "DEIDENTIFICATION_SALT_FILE", "/secrets/deidentification-salt"
    )

    # Export date window: defaults to yesterday (UTC)
    EXPORT_DATE_OVERRIDE: str | None = os.getenv("EXPORT_DATE_OVERRIDE")

    @classmethod
    def db_password(cls) -> str:
        """Read DB password from mounted Secret Manager file."""
        with open(cls.DB_PASSWORD_FILE) as f:
            return f.read().strip()

    @classmethod
    def deidentification_salt(cls) -> str:
        """Read de-identification salt from mounted Secret Manager file."""
        with open(cls.DEIDENTIFICATION_SALT_FILE) as f:
            return f.read().strip()
