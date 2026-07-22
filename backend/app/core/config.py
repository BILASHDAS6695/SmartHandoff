"""Application settings — loaded from environment variables (mounted from GCP Secret Manager).

SmartHandoff follows TR-021: zero hardcoded credentials. All secrets are injected
as environment variables by Cloud Run via Secret Manager volume mounts.

Usage::
    from app.core.config import get_settings
    settings = get_settings()
    secret = settings.SCIM_CLIENT_SECRET
"""
from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    """Application settings resolved from environment variables at access time.

    Each property reads from ``os.environ`` so tests can monkeypatch the env
    without needing to reload the module.
    """

    @property
    def SCIM_CLIENT_SECRET(self) -> str:
        """Long-lived bearer token issued to the hospital IdP for SCIM provisioning.

        90-day rotation. Stored in GCP Secret Manager as 'scim-client-secret'.
        Mounted as SCIM_CLIENT_SECRET environment variable in Cloud Run (TR-021).

        Raises:
            RuntimeError: If SCIM_CLIENT_SECRET is not set.
        """
        value = os.environ.get("SCIM_CLIENT_SECRET", "")
        if not value:
            raise RuntimeError(
                "SCIM_CLIENT_SECRET environment variable is not set. "
                "Mount it from GCP Secret Manager 'scim-client-secret-{env}'."
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Call ``get_settings.cache_clear()`` in tests to reset after monkeypatching
    environment variables.
    """
    return Settings()
