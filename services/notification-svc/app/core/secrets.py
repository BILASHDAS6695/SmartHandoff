"""GCP Secret Manager helper for runtime credential retrieval.

Loads Twilio and SendGrid credentials from Secret Manager on first access.
Values are cached in-process for the container lifetime.

Design refs:
    US-064 Technical Notes — Twilio credentials from Secret Manager
    ADR-007 — No credentials in environment variables or source code
"""
from __future__ import annotations

import functools
import os

from google.cloud import secretmanager


@functools.lru_cache(maxsize=None)
def get_secret(secret_id: str) -> str:
    """Retrieve the latest version of a Secret Manager secret.

    For local development, secrets can also be supplied via environment
    variables with the same names (upper-snake-case). Environment-variable
    lookup takes precedence over Secret Manager to avoid GCP calls during
    localhost testing.

    Args:
        secret_id: Secret resource name suffix, e.g. ``twilio-account-sid``.

    Returns:
        Secret payload as a UTF-8 string.
    """
    env_var_name = secret_id.replace("-", "_").upper()
    env_value = os.environ.get(env_var_name)
    if env_value:
        return env_value

    project_id = os.environ["GCP_PROJECT_ID"]
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")
