---
id: TASK-002
title: "Implement PHI Encryption Key Loading from GCP Secret Manager"
user_story: US-007
epic: EP-DATA
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [TASK-001, US-005]
---

# TASK-002: Implement PHI Encryption Key Loading from GCP Secret Manager

> **Story:** US-007 | **Epic:** EP-DATA | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

The AES-256-GCM TypeDecorators (TASK-003 and TASK-004) require a 32-byte key to encrypt and decrypt PHI. This key must **never** be hardcoded in source code or container images (TR-021, SEC-011). The mandated pattern (ADR-007) is to load the key from **GCP Secret Manager** at application startup and cache it in memory for the process lifetime.

US-005 provisions the Secret Manager secret (`phi-encryption-key`) and stores a base64url-encoded 32-byte AES-256 key. This task implements `get_phi_encryption_key()` — the single point of key access throughout the codebase — replacing the stub created in TASK-001.

### Key loading requirements

| Requirement | Implementation |
|---|---|
| Key sourced from Secret Manager | `PHI_ENCRYPTION_KEY_SECRET_ID` env var names the secret; key loaded via `google-cloud-secret-manager` SDK |
| Local development fallback | `PHI_ENCRYPTION_KEY` env var may hold a base64url-encoded key directly (dev-only; must never be set in Cloud Run production) |
| Exactly 32 bytes | Validation enforced at load time; `ValueError` raised if wrong length |
| Cached in-process | Module-level `_cached_key` variable; only one Secret Manager call per process lifetime |
| Never logged | Key bytes are **never** passed to any logger; log only the secret ID on load |

---

## Acceptance Criteria Addressed

| US-007 AC | Requirement |
|---|---|
| **DoD** | Encryption key loaded from Secret Manager at application startup; key cached in memory (not logged) |

---

## Implementation Steps

### 1. Add `google-cloud-secret-manager` to `backend/requirements.txt`

```
google-cloud-secret-manager>=2.20.0
```

### 2. Implement `backend/app/db/encryption_key.py`

Replace the stub from TASK-001 with the full implementation:

```python
"""PHI encryption key management.

Loads the AES-256-GCM key from GCP Secret Manager at startup and caches
it in process memory. The key is never written to logs or telemetry.

Environment variables (resolved in priority order):
  PHI_ENCRYPTION_KEY_SECRET_ID  (production)
      GCP Secret Manager secret resource name or short ID.
      Example: "phi-encryption-key" (project inferred from Application Default Credentials)
      Full form: "projects/my-project/secrets/phi-encryption-key/versions/latest"

  PHI_ENCRYPTION_KEY  (local development ONLY)
      Base64url-encoded 32-byte key. Must NOT be set in Cloud Run.
      Generate with: python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

Security invariants:
  - Key bytes are NEVER logged (not even as a hash).
  - Loading raises RuntimeError if neither env var is set.
  - Loading raises ValueError if the decoded key is not exactly 32 bytes.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Final

logger = logging.getLogger(__name__)

# Module-level cache: populated once at first call, reused for process lifetime.
_cached_key: bytes | None = None

_KEY_LENGTH_BYTES: Final[int] = 32  # AES-256 requires a 32-byte (256-bit) key


def get_phi_encryption_key() -> bytes:
    """Return the 32-byte AES-256 key for PHI field encryption.

    Thread-safe under CPython's GIL for the read-then-write cache pattern.
    For multi-threaded environments, the worst case is two concurrent loads
    on first call — both will produce an identical key; the second write is
    harmless.

    Returns:
        32-byte AES-256 key as raw bytes.

    Raises:
        RuntimeError: If no key source environment variable is configured.
        ValueError: If the resolved key is not exactly 32 bytes.
        google.api_core.exceptions.GoogleAPIError: If Secret Manager call fails.
    """
    global _cached_key
    if _cached_key is not None:
        return _cached_key

    key = _load_key()
    _cached_key = key
    return key


def _load_key() -> bytes:
    """Resolve and decode the encryption key from the configured source."""
    # ── Production path: GCP Secret Manager ──────────────────────────────────
    secret_id = os.environ.get("PHI_ENCRYPTION_KEY_SECRET_ID")
    if secret_id:
        return _load_from_secret_manager(secret_id)

    # ── Local development fallback: direct env var ────────────────────────────
    raw_key_b64 = os.environ.get("PHI_ENCRYPTION_KEY")
    if raw_key_b64:
        logger.warning(
            "PHI_ENCRYPTION_KEY loaded from environment variable — "
            "acceptable for local development only. "
            "Ensure PHI_ENCRYPTION_KEY is NOT set in Cloud Run production."
        )
        return _decode_and_validate(raw_key_b64, source="PHI_ENCRYPTION_KEY env var")

    raise RuntimeError(
        "PHI encryption key is not configured. "
        "Set PHI_ENCRYPTION_KEY_SECRET_ID (production) or "
        "PHI_ENCRYPTION_KEY (local dev) environment variable."
    )


def _load_from_secret_manager(secret_id: str) -> bytes:
    """Fetch the latest enabled version of the secret from GCP Secret Manager."""
    # Import here so the library is only required in production environments.
    # Tests can mock `app.db.encryption_key._load_from_secret_manager`.
    from google.cloud import secretmanager  # type: ignore[import-untyped]

    client = secretmanager.SecretManagerServiceClient()

    # Accept both short IDs ("phi-encryption-key") and full resource names.
    if not secret_id.startswith("projects/"):
        # Derive the project from the environment (Cloud Run injects GOOGLE_CLOUD_PROJECT)
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
        if not project:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT is not set. Cannot resolve short secret ID "
                f"'{secret_id}' to a full Secret Manager resource name."
            )
        secret_id = f"projects/{project}/secrets/{secret_id}/versions/latest"
    elif not secret_id.endswith("/versions/latest") and "/versions/" not in secret_id:
        secret_id = f"{secret_id}/versions/latest"

    logger.info("Loading PHI encryption key from Secret Manager: %s", secret_id)
    response = client.access_secret_version(name=secret_id)
    raw_b64 = response.payload.data.decode("utf-8").strip()
    return _decode_and_validate(raw_b64, source=f"Secret Manager: {secret_id}")


def _decode_and_validate(raw_b64: str, source: str) -> bytes:
    """Decode a base64url-encoded key and validate its length."""
    try:
        key = base64.urlsafe_b64decode(raw_b64 + "==")  # padding-tolerant
    except Exception as exc:
        raise ValueError(
            f"PHI encryption key from {source} is not valid base64url: {exc}"
        ) from exc

    if len(key) != _KEY_LENGTH_BYTES:
        raise ValueError(
            f"PHI encryption key from {source} must be exactly {_KEY_LENGTH_BYTES} bytes "
            f"(256 bits). Got {len(key)} bytes. "
            "Generate a correct key with: "
            "python -c \"import secrets,base64; "
            "print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())\""
        )
    # SUCCESS — do NOT log the key bytes or any derivative.
    logger.info(
        "PHI encryption key loaded successfully from %s (%d bytes).",
        source,
        _KEY_LENGTH_BYTES,
    )
    return key


def clear_cached_key() -> None:
    """Clear the in-memory key cache.

    Intended for use in tests and key-rotation scenarios only.
    Do NOT call this in production request handlers.
    """
    global _cached_key
    _cached_key = None
```

### 3. Register Key Loading at FastAPI Application Startup

In `backend/app/main.py` (or wherever the FastAPI `lifespan` is configured), call `get_phi_encryption_key()` at startup so that a misconfigured key fails fast rather than at the first PHI write:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.encryption_key import get_phi_encryption_key
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly load the PHI encryption key so startup fails loudly
    # if Secret Manager is misconfigured — not silently at first PHI write.
    get_phi_encryption_key()
    logger.info("PHI encryption key validated at startup.")
    yield
    # (shutdown logic here)

app = FastAPI(lifespan=lifespan)
```

---

## Validation

### Unit Test (in-module smoke test — do NOT commit to main without a proper test in TASK-006)

```bash
cd backend
PHI_ENCRYPTION_KEY=$(python -c \
  "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())") \
python -c "
from app.db.encryption_key import get_phi_encryption_key, clear_cached_key
key = get_phi_encryption_key()
assert len(key) == 32, f'Expected 32 bytes, got {len(key)}'
assert get_phi_encryption_key() is key, 'Cache miss on second call'
clear_cached_key()
print('Key management OK — 32 bytes loaded and cached')
"
```

### Error Path Validation

```bash
cd backend
python -c "
import os; os.environ.pop('PHI_ENCRYPTION_KEY_SECRET_ID', None); os.environ.pop('PHI_ENCRYPTION_KEY', None)
from app.db.encryption_key import clear_cached_key, get_phi_encryption_key
clear_cached_key()
try:
    get_phi_encryption_key()
    assert False, 'Should have raised RuntimeError'
except RuntimeError as e:
    print(f'Correct error raised: {e}')
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/requirements.txt` | Add `google-cloud-secret-manager>=2.20.0` |
| `backend/app/db/encryption_key.py` | Replace stub with full implementation |
| `backend/app/main.py` | Add `get_phi_encryption_key()` call to `lifespan` startup |

---

## Definition of Done Checklist

- [ ] `google-cloud-secret-manager>=2.20.0` in `backend/requirements.txt`
- [ ] `get_phi_encryption_key()` resolves from `PHI_ENCRYPTION_KEY_SECRET_ID` in production
- [ ] `get_phi_encryption_key()` resolves from `PHI_ENCRYPTION_KEY` env var for local dev (with warning log)
- [ ] Key cached in-process; only one Secret Manager round-trip per process lifetime
- [ ] Key bytes never passed to any logger or serialised to any output
- [ ] `ValueError` raised if decoded key is not exactly 32 bytes
- [ ] `RuntimeError` raised at startup if neither env var is set
- [ ] `clear_cached_key()` available for test isolation
- [ ] FastAPI lifespan calls `get_phi_encryption_key()` at startup (fail-fast)
