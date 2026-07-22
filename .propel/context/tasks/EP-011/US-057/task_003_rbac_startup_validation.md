---
id: TASK-003
title: "RBAC Config Startup Validation — Lifespan Integration and Role Completeness Check"
user_story: US-057
epic: EP-011
sprint: 1
layer: Backend
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-057/TASK-002]
---

# TASK-003: RBAC Config Startup Validation — Lifespan Integration and Role Completeness Check

> **Story:** US-057 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 1 h
> **Status:** Done | **Date:** 2026-07-15

---

## Context

US-057 AC Scenario 3 and the DoD both require: *"Startup validation: RBAC config file validated on application start (missing role → refuse startup)"*.

A misconfigured RBAC matrix is a security risk: a role that is absent from the YAML would silently pass permission checks if the code falls back to an empty dict (no permissions) rather than failing. Refusing startup on misconfiguration ensures that a typo or merge conflict in `rbac_permissions.yaml` is caught in CI integration tests before reaching production.

This task hooks into FastAPI's `lifespan` context manager (the modern replacement for deprecated `on_event("startup")` handlers) to call `validate_rbac_config()` during boot. If validation fails, the application process exits with a non-zero code and Cloud Run's health check fails, preventing traffic from reaching the broken instance.

---

## Acceptance Criteria Addressed

| US-057 AC | Requirement |
|---|---|
| **Scenario 3** | When FastAPI app starts, `config/rbac_permissions.yaml` is validated; missing role → startup error (Cloud Run readiness probe fails) |
| **DoD** | Startup validation: missing role → refuse startup |

---

## Implementation Steps

### 1. Create `backend/app/core/auth/rbac_validator.py`

```python
"""RBAC configuration startup validator.

Called during FastAPI application lifespan startup (app/main.py).
Validates that rbac_permissions.yaml contains the expected staff roles and
resource keys. Raises RuntimeError on misconfiguration so the process exits
before accepting traffic — Cloud Run readiness probe will fail, preventing
a misconfigured instance from serving requests.

Expected roles (6 staff/admin roles — PATIENT is hardcoded separately):
    ADMIN, PHYSICIAN, NURSE, PHARMACIST, BED_MANAGER, CARE_MANAGER

Expected resource keys (must be present for every role, even if empty list):
    patient, encounter, document, medication, alert, bed,
    analytics, audit_log, user, agent_task
"""
from __future__ import annotations

import logging

from app.core.auth.rbac import load_rbac_matrix

logger = logging.getLogger(__name__)

_REQUIRED_ROLES = frozenset({
    "ADMIN",
    "PHYSICIAN",
    "NURSE",
    "PHARMACIST",
    "BED_MANAGER",
    "CARE_MANAGER",
})

_REQUIRED_RESOURCES = frozenset({
    "patient",
    "encounter",
    "document",
    "medication",
    "alert",
    "bed",
    "analytics",
    "audit_log",
    "user",
    "agent_task",
})

_VALID_ACTIONS = frozenset({"list", "read", "write", "approve", "resolve"})


def validate_rbac_config() -> None:
    """Validate the RBAC permission matrix loaded from YAML.

    Checks:
      1. All required roles are present.
      2. No unexpected roles are present (defence against PATIENT being added).
      3. All required resource keys are present under each role.
      4. All listed actions are from the allowed set.

    Raises:
        RuntimeError: on any validation failure — propagates to lifespan
                      startup, causing the FastAPI process to exit.
    """
    logger.info("Validating RBAC configuration...")

    matrix = load_rbac_matrix()
    defined_roles = set(matrix.keys())

    # 1. Missing roles
    missing = _REQUIRED_ROLES - defined_roles
    if missing:
        raise RuntimeError(
            f"RBAC config validation failed: missing required roles: {sorted(missing)}. "
            "Add the missing roles to config/rbac_permissions.yaml and re-deploy."
        )

    # 2. PATIENT must never appear in the matrix
    if "PATIENT" in defined_roles:
        raise RuntimeError(
            "RBAC config validation failed: PATIENT role must NOT be defined in "
            "rbac_permissions.yaml. PATIENT access is controlled via require_patient_auth()."
        )

    # 3. Resource key completeness per role
    for role, resources in matrix.items():
        defined_resources = set(resources.keys())
        missing_resources = _REQUIRED_RESOURCES - defined_resources
        if missing_resources:
            raise RuntimeError(
                f"RBAC config validation failed: role '{role}' is missing resource keys: "
                f"{sorted(missing_resources)}. Every role must define all resource keys "
                "(use an empty list [] for explicit deny)."
            )

        # 4. Action validity per resource
        for resource, actions in resources.items():
            invalid_actions = set(actions) - _VALID_ACTIONS
            if invalid_actions:
                raise RuntimeError(
                    f"RBAC config validation failed: role '{role}', resource '{resource}' "
                    f"contains unknown actions: {sorted(invalid_actions)}. "
                    f"Valid actions are: {sorted(_VALID_ACTIONS)}."
                )

    logger.info(
        "RBAC configuration validated successfully: %d roles, %d resources each.",
        len(matrix),
        len(_REQUIRED_RESOURCES),
    )
```

### 2. Integrate into FastAPI Lifespan in `backend/app/main.py`

Locate the FastAPI application lifespan context manager in `app/main.py`. If none exists yet, add one using the modern `asynccontextmanager` pattern. Insert `validate_rbac_config()` as the first startup action:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.auth.rbac_validator import validate_rbac_config
# ... other imports


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────
    validate_rbac_config()          # Raises RuntimeError → process exits if invalid
    # ... other startup actions (OIDC discovery, DB pool warm-up, etc.)

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    # ... graceful shutdown actions


app = FastAPI(lifespan=lifespan, ...)
```

> **Important:** If `app/main.py` already uses `@app.on_event("startup")` (deprecated), migrate that handler to the lifespan context manager rather than adding a second startup hook. Do not leave both patterns in the file.

### 3. Update the `/ready` readiness probe endpoint

The `GET /ready` endpoint (TR-016) should return `503 Service Unavailable` if the RBAC matrix failed to load. Since `validate_rbac_config()` raises a `RuntimeError` on startup failure (crashing the process), Cloud Run will automatically restart the container and the readiness probe will fail during the restart window. No explicit change to `/ready` is required, but confirm the endpoint does not suppress startup errors:

```python
# In app/api/v1/health.py (or equivalent)
@router.get("/ready")
async def readiness():
    """Readiness probe — returns 200 only when the application is fully initialised."""
    # No try/except here — if startup raised, this code is never reached
    return {"status": "ready"}
```

---

## Validation

```bash
cd backend

# Test: valid config → startup passes
python -c "
from app.core.auth.rbac_validator import validate_rbac_config
validate_rbac_config()
print('Startup validation: PASS')
"

# Test: missing role → RuntimeError raised
python -c "
import tempfile, os, yaml
from pathlib import Path
from app.core.auth import rbac

# Write a broken config (NURSE missing)
broken = {'roles': {k: {r: [] for r in ['patient','encounter','document','medication','alert','bed','analytics','audit_log','user','agent_task']} for k in ['ADMIN','PHYSICIAN','PHARMACIST','BED_MANAGER','CARE_MANAGER']}}
with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
    yaml.dump(broken, f)
    tmp = f.name

os.environ['RBAC_CONFIG_PATH'] = tmp
rbac.load_rbac_matrix.cache_clear()

from app.core.auth.rbac_validator import validate_rbac_config
try:
    validate_rbac_config()
    print('ERROR: should have raised RuntimeError')
except RuntimeError as e:
    print(f'Correctly raised RuntimeError: {e}')
finally:
    os.unlink(tmp)
    rbac.load_rbac_matrix.cache_clear()
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/app/core/auth/rbac_validator.py` | Create |
| `backend/app/main.py` | Add `validate_rbac_config()` call in lifespan startup |

---

## Definition of Done Checklist

- [ ] `rbac_validator.py` created with `validate_rbac_config()` function
- [ ] All 6 required roles checked at startup
- [ ] PATIENT-in-YAML guard present (raises RuntimeError)
- [ ] All 10 resource keys checked per role
- [ ] All actions validated against allowed set
- [ ] `validate_rbac_config()` called in FastAPI `lifespan` startup
- [ ] Cloud Run readiness probe (`GET /ready`) returns 503 during a restart triggered by startup failure (verified via manual test or integration test)
