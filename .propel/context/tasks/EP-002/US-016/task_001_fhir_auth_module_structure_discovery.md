# TASK-001: Setup FHIR Auth Module Structure, Custom Exceptions, and SMART on FHIR Discovery Client

> **Story:** US-016 | **Epic:** EP-002 | **Sprint:** 1 | **Layer:** Backend | **Est:** 8 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task establishes the foundational structure for FHIR authentication by creating the module hierarchy, defining custom exceptions, and implementing SMART on FHIR discovery. The discovery client fetches the `.well-known/smart-configuration` document to dynamically obtain the OAuth token endpoint URL, ensuring compatibility with any SMART-on-FHIR-compliant EHR system.

**Design references:**
- design.md §4.1 — Technology Stack: fhir.resources + httpx for FHIR R4 client
- US-016 Technical Notes — SMART on FHIR well-known discovery
- epics.md EP-002 — SMART on FHIR OAuth 2.0 client credentials flow

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| AC Scenario 1 | Provides discovery mechanism to obtain token endpoint |
| AC Scenario 4 | Defines `FHIRAuthenticationError` exception for auth failures |

---

## Implementation Steps

### 1. Create FHIR module structure

```bash
mkdir -p backend/app/core/fhir
touch backend/app/core/fhir/__init__.py
```

### 2. Implement `backend/app/core/fhir/exceptions.py`

Create custom exception class for FHIR authentication failures:

```python
"""Custom exceptions for FHIR authentication and API interactions.

Design refs:
    US-016 AC Scenario 4 — FHIRAuthenticationError raised on 401
    SEC-011              — no PHI in exception messages or logs
"""
from __future__ import annotations


class FHIRAuthenticationError(Exception):
    """Raised when FHIR OAuth authentication fails.

    Attributes:
        status_code: HTTP status code from the auth server (e.g., 401, 403)
        response_body: Raw response body from the failed auth request (no PHI)
        message: Human-readable error message (no PHI, safe for logging)
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"(HTTP {self.status_code})")
        return " ".join(parts)
```

### 3. Implement `backend/app/core/fhir/discovery.py`

Implement SMART on FHIR discovery client to fetch the well-known configuration:

```python
"""SMART on FHIR discovery client.

Fetches the .well-known/smart-configuration document to discover OAuth endpoints.

Design refs:
    US-016 Technical Notes — SMART on FHIR well-known discovery
    epics.md EP-002        — OAuth 2.0 client credentials flow
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.fhir.exceptions import FHIRAuthenticationError

logger = logging.getLogger(__name__)


async def discover_smart_config(base_url: str) -> dict[str, Any]:
    """Fetch the SMART on FHIR configuration from the EHR's well-known endpoint.

    Args:
        base_url: The FHIR server base URL (e.g., "https://ehr.example.com/fhir")

    Returns:
        Dictionary containing the SMART configuration, including:
            - token_endpoint: OAuth 2.0 token endpoint URL
            - authorization_endpoint: OAuth 2.0 authorization endpoint (unused in client_credentials)
            - capabilities: List of SMART capabilities (e.g., "client-confidential-asymmetric")

    Raises:
        FHIRAuthenticationError: If the discovery endpoint is unreachable or returns invalid JSON

    Example:
        config = await discover_smart_config("https://ehr.example.com/fhir")
        token_endpoint = config["token_endpoint"]
    """
    discovery_url = f"{base_url.rstrip('/')}/.well-known/smart-configuration"
    logger.info("Fetching SMART configuration from %s", discovery_url)

    try:
        async with httpx.AsyncClient(verify=True, timeout=10.0) as client:
            response = await client.get(discovery_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.critical(
            "SMART discovery failed",
            extra={
                "event": "fhir_discovery_failure",
                "url": discovery_url,
                "error": str(exc),
            },
        )
        raise FHIRAuthenticationError(
            f"Failed to fetch SMART configuration from {discovery_url}",
            status_code=getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None,
            response_body=str(exc),
        ) from exc

    try:
        config = response.json()
    except ValueError as exc:
        logger.critical(
            "SMART discovery returned invalid JSON",
            extra={
                "event": "fhir_discovery_invalid_json",
                "url": discovery_url,
            },
        )
        raise FHIRAuthenticationError(
            f"SMART configuration at {discovery_url} returned invalid JSON"
        ) from exc

    # Validate required fields
    if "token_endpoint" not in config:
        logger.critical(
            "SMART configuration missing token_endpoint",
            extra={
                "event": "fhir_discovery_missing_token_endpoint",
                "url": discovery_url,
                "keys": list(config.keys()),
            },
        )
        raise FHIRAuthenticationError(
            f"SMART configuration at {discovery_url} missing 'token_endpoint' field"
        )

    logger.info(
        "SMART configuration fetched successfully",
        extra={
            "event": "fhir_discovery_success",
            "token_endpoint": config["token_endpoint"],
            "capabilities": config.get("capabilities", []),
        },
    )
    return config


def get_token_endpoint(smart_config: dict[str, Any]) -> str:
    """Extract the token endpoint URL from a SMART configuration document.

    Args:
        smart_config: SMART configuration dictionary returned by discover_smart_config()

    Returns:
        OAuth 2.0 token endpoint URL

    Raises:
        KeyError: If token_endpoint is not present in the configuration
    """
    return smart_config["token_endpoint"]
```

### 4. Update `backend/app/core/fhir/__init__.py`

Export public interfaces:

```python
"""FHIR authentication and API client.

Provides SMART on FHIR OAuth 2.0 authentication with token caching.
"""
from app.core.fhir.discovery import discover_smart_config, get_token_endpoint
from app.core.fhir.exceptions import FHIRAuthenticationError

__all__ = [
    "FHIRAuthenticationError",
    "discover_smart_config",
    "get_token_endpoint",
]
```

---

## Files Modified / Created

| File | Change Type | Lines (approx) |
|------|-------------|----------------|
| `backend/app/core/fhir/__init__.py` | Created | 10 |
| `backend/app/core/fhir/exceptions.py` | Created | 35 |
| `backend/app/core/fhir/discovery.py` | Created | 110 |

**Total:** ~155 lines

---

## Verification

### Manual testing

```bash
# From backend/ directory
python -m pytest -xvs -k "test_discovery" backend/tests/unit/core/fhir/test_discovery.py
```

Expected:
- SMART discovery successfully fetches .well-known/smart-configuration
- token_endpoint extracted correctly
- Network errors raise FHIRAuthenticationError
- Invalid JSON raises FHIRAuthenticationError
- Missing token_endpoint raises FHIRAuthenticationError

### Code review checklist

- [ ] `FHIRAuthenticationError` includes status_code and response_body attributes
- [ ] No PHI in exception messages or logs (SEC-011)
- [ ] Discovery URL correctly constructed with .rstrip('/') to handle trailing slashes
- [ ] httpx timeout set to 10s (prevents hanging on unreachable EHR)
- [ ] All exceptions logged at CRITICAL level with structured extra fields
- [ ] Module exports defined in `__init__.py`

---

## Definition of Done Checklist

- [ ] FHIR module structure created (`backend/app/core/fhir/`)
- [ ] `FHIRAuthenticationError` exception class implemented
- [ ] `discover_smart_config()` function implemented
- [ ] `get_token_endpoint()` helper function implemented
- [ ] Logging at CRITICAL level for all auth failures (no PHI)
- [ ] Module exports defined in `__init__.py`
- [ ] Manual verification with mock SMART configuration endpoint
- [ ] Code passes `ruff check` and `mypy` validation
- [ ] Code reviewed and approved

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| httpx | Package | Already in requirements.txt (async HTTP client) |
| US-005 | Story | Secret Manager infrastructure must be in place |

---

## Notes

- **SMART on FHIR Specification:** This implementation follows the SMART on FHIR v2.0 specification for `.well-known/smart-configuration` discovery.
- **No PHI in logs:** All logging adheres to SEC-011 (no PHI in logs or exception messages).
- **Future enhancement:** The `capabilities` field from the SMART configuration can be used in future stories to validate server support for specific features (e.g., asymmetric client authentication).
- **Unit tests:** Deferred to TASK-004 (comprehensive unit test suite).
