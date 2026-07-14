---
task_id: task_001
story_id: us_004
epic: EP-TECH
title: Application Secret Loading Pattern — Settings Module with Secret Manager Bindings
layer: Application / Configuration
effort_hours: 1.5
sequence: 1
status: Draft
---

# TASK-001: Application Secret Loading Pattern — Settings Module with Secret Manager Bindings

> **Story:** EP-TECH/US-004 | **Layer:** Application / Config | **Effort:** 1.5 hours | **Seq:** 1 of 3

## Objective

Implement the shared `settings.py` module that all Python services use to load secrets from environment variables (injected by Secret Manager bindings defined in Terraform us_001/task_008). Fail fast with a clear error if any required secret is missing — satisfying AC-2 (secrets accessed via bindings, never hardcoded).

## Implementation Steps

### 1. Shared Settings Module (`services/shared/settings.py`)

```python
"""
services/shared/settings.py

Centralised application settings loaded exclusively from environment variables.
All secrets are injected by GCP Secret Manager via Cloud Run secretKeyRef bindings.
NEVER read secrets from files, hardcoded strings, or .env files in production.
"""
import os
import base64
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


class SecretMissing(RuntimeError):
    """Raised at startup when a required secret environment variable is absent."""


def _require(key: str) -> str:
    """Load a required env var; raise SecretMissing if absent or empty."""
    val = os.environ.get(key, "").strip()
    if not val:
        raise SecretMissing(
            f"Required secret '{key}' is not set. "
            "Ensure the Cloud Run service has a secretKeyRef binding for this secret."
        )
    # Warn if value looks like a placeholder left by SecOps
    if val.startswith("PLACEHOLDER"):
        logger.warning(
            "Secret '%s' appears to be a placeholder value. "
            "Replace it in GCP Secret Manager before production use.", key
        )
    return val


def _optional(key: str, default: str = "") -> str:
    """Load an optional env var; return default if absent."""
    return os.environ.get(key, default).strip()


@dataclass(frozen=True)
class DatabaseSettings:
    host: str          = field(default_factory=lambda: _require("DB_HOST"))
    port: int          = field(default_factory=lambda: int(_optional("DB_PORT", "5432")))
    name: str          = field(default_factory=lambda: _optional("DB_NAME", "smarthandoff"))
    user: str          = field(default_factory=lambda: _require("DB_USER"))
    password: str      = field(default_factory=lambda: _require("DB_PASSWORD"))

    @property
    def async_url(self) -> str:
        """PostgreSQL asyncpg DSN — never log this value."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        """PostgreSQL psycopg2 DSN for Alembic migrations."""
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass(frozen=True)
class PHIEncryptionSettings:
    key_b64: str         = field(default_factory=lambda: _require("PHI_ENCRYPTION_KEY"))
    det_key_b64: str     = field(default_factory=lambda: _require("PHI_ENCRYPTION_KEY_DET"))

    @property
    def key_bytes(self) -> bytes:
        """AES-256-GCM encryption key decoded from Base64."""
        return base64.b64decode(self.key_b64)

    @property
    def det_key_bytes(self) -> bytes:
        """Deterministic AES-256-GCM key (for MRN indexed lookups)."""
        return base64.b64decode(self.det_key_b64)


@dataclass(frozen=True)
class JWTSettings:
    private_key_pem: str  = field(default_factory=lambda: _require("JWT_SIGNING_KEY_PRIVATE"))
    public_key_pem: str   = field(default_factory=lambda: _require("JWT_SIGNING_KEY_PUBLIC"))
    algorithm: str        = "RS256"
    expiry_minutes: int   = field(default_factory=lambda: int(_optional("JWT_EXPIRY_MINUTES", "15")))


@dataclass(frozen=True)
class OIDCSettings:
    client_id: str        = field(default_factory=lambda: _require("OIDC_CLIENT_ID"))
    client_secret: str    = field(default_factory=lambda: _require("OIDC_CLIENT_SECRET"))
    discovery_url: str    = field(default_factory=lambda: _require("OIDC_DISCOVERY_URL"))


@dataclass(frozen=True)
class FHIRSettings:
    base_url: str         = field(default_factory=lambda: _require("FHIR_BASE_URL"))
    client_id: str        = field(default_factory=lambda: _require("FHIR_CLIENT_ID"))
    client_secret: str    = field(default_factory=lambda: _require("FHIR_CLIENT_SECRET"))


@dataclass(frozen=True)
class VertexAISettings:
    project_id: str       = field(default_factory=lambda: _require("VERTEX_AI_PROJECT"))
    region: str           = field(default_factory=lambda: _optional("VERTEX_AI_REGION", "us-central1"))


@dataclass(frozen=True)
class TwilioSettings:
    account_sid: str      = field(default_factory=lambda: _require("TWILIO_ACCOUNT_SID"))
    auth_token: str       = field(default_factory=lambda: _require("TWILIO_AUTH_TOKEN"))
    verify_service_sid: str = field(default_factory=lambda: _require("TWILIO_VERIFY_SERVICE_SID"))
    phone_number: str     = field(default_factory=lambda: _require("TWILIO_PHONE_NUMBER"))


@dataclass(frozen=True)
class SendGridSettings:
    api_key: str          = field(default_factory=lambda: _require("SENDGRID_API_KEY"))


@dataclass(frozen=True)
class AppSettings:
    environment: str      = field(default_factory=lambda: _optional("ENVIRONMENT", "dev"))
    gcp_project_id: str   = field(default_factory=lambda: _optional("GCP_PROJECT_ID", ""))
    region: str           = field(default_factory=lambda: _optional("REGION", "us-central1"))

    db: DatabaseSettings          = field(default_factory=DatabaseSettings)
    phi_encryption: PHIEncryptionSettings = field(default_factory=PHIEncryptionSettings)
    jwt: JWTSettings              = field(default_factory=JWTSettings)
    oidc: OIDCSettings            = field(default_factory=OIDCSettings)
    fhir: FHIRSettings            = field(default_factory=FHIRSettings)
    vertex_ai: VertexAISettings   = field(default_factory=VertexAISettings)
    twilio: TwilioSettings        = field(default_factory=TwilioSettings)
    sendgrid: SendGridSettings    = field(default_factory=SendGridSettings)


def load_settings(service_name: str) -> AppSettings:
    """
    Load and validate all settings at service startup.

    Raises SecretMissing if any required secret is absent.
    Log the service name for traceability but never log secret values.
    """
    logger.info("Loading settings for service: %s", service_name)
    try:
        settings = AppSettings()
        logger.info(
            "Settings loaded successfully for %s (env=%s, project=%s)",
            service_name, settings.environment, settings.gcp_project_id
        )
        return settings
    except SecretMissing as exc:
        logger.critical("Startup failed — missing required secret: %s", exc)
        raise


# Module-level singleton — loaded once at import time
# Each service only imports the subset it needs:
#   from services.shared.settings import load_settings
#   settings = load_settings("api-gateway")
```

### 2. Per-Service Secret Subset

Not all services need all secrets. Import only the required subset to limit blast radius:

**`services/api-gateway/src/config.py`:**
```python
from services.shared.settings import load_settings, AppSettings

_settings: AppSettings | None = None

def get_settings() -> AppSettings:
    global _settings
    if _settings is None:
        _settings = load_settings("api-gateway")
    return _settings
```

**`services/docs-agent/src/config.py`:**
```python
# Only FHIR, Vertex AI, DB, PHI encryption — no Twilio/SendGrid
from services.shared.settings import AppSettings, FHIRSettings, VertexAISettings, DatabaseSettings, PHIEncryptionSettings
```

### 3. Environment Variable → Secret Manager Binding Map

This table documents which env var corresponds to which Secret Manager secret:

| Env Var | Secret Manager Key | Services |
|---------|--------------------|---------|
| `DB_HOST` | `smarthandoff-db-host-{env}` | All |
| `DB_PASSWORD` | `smarthandoff-db-password-{env}` | All |
| `PHI_ENCRYPTION_KEY` | `smarthandoff-phi-encryption-key-{env}` | api-gateway, docs-agent, comms-agent, followup-agent |
| `PHI_ENCRYPTION_KEY_DET` | `smarthandoff-phi-encryption-key-det-{env}` | api-gateway |
| `JWT_SIGNING_KEY_PRIVATE` | `smarthandoff-jwt-signing-key-private-{env}` | api-gateway |
| `JWT_SIGNING_KEY_PUBLIC` | `smarthandoff-jwt-signing-key-public-{env}` | api-gateway |
| `OIDC_CLIENT_ID` | `smarthandoff-oidc-client-id-{env}` | api-gateway |
| `OIDC_CLIENT_SECRET` | `smarthandoff-oidc-client-secret-{env}` | api-gateway |
| `FHIR_BASE_URL` | `smarthandoff-fhir-base-url-{env}` | docs-agent, medrecon-agent, followup-agent |
| `FHIR_CLIENT_ID` | `smarthandoff-fhir-client-id-{env}` | docs-agent, medrecon-agent, followup-agent |
| `FHIR_CLIENT_SECRET` | `smarthandoff-fhir-client-secret-{env}` | docs-agent, medrecon-agent, followup-agent |
| `VERTEX_AI_PROJECT` | `smarthandoff-vertex-ai-project-{env}` | docs-agent, comms-agent |
| `TWILIO_ACCOUNT_SID` | `smarthandoff-twilio-account-sid-{env}` | notification-svc |
| `TWILIO_AUTH_TOKEN` | `smarthandoff-twilio-auth-token-{env}` | notification-svc |
| `SENDGRID_API_KEY` | `smarthandoff-sendgrid-api-key-{env}` | notification-svc |

## Acceptance Criteria

- [ ] **AC-2:** `services/shared/settings.py` exists and `_require()` raises `SecretMissing` when an env var is absent — confirmed by unit test: `os.environ.pop("DB_PASSWORD"); load_settings("test")` raises `SecretMissing`
- [ ] `load_settings()` logs the service name and environment at INFO level but NEVER logs secret values — confirmed by capturing log output in test and verifying no secret appears
- [ ] Each service uses `get_settings()` from its `config.py` — grep confirms no `os.environ.get("DB_PASSWORD")` calls outside `settings.py`
- [ ] `settings.db.async_url` property not logged anywhere — `grep -r "async_url" services/` returns zero logger calls

## Files to Create

```
services/shared/settings.py
services/api-gateway/src/config.py
services/docs-agent/src/config.py
services/medrecon-agent/src/config.py
services/notification-svc/src/config.py
```

## Notes

- `frozen=True` on dataclasses prevents accidental mutation of settings after startup
- `SecretMissing` causes the Cloud Run service to crash at startup with a clear error message — this is intentional; a service without its required secrets should not start silently and produce incorrect output
- The `_optional()` pattern avoids `SecretMissing` for settings that have sensible defaults (region, port) while `_require()` enforces presence for all credentials
