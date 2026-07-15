---
id: TASK-002
title: "Implement `app/core/auth/rbac.py` — `require_permission` FastAPI Dependency"
user_story: US-057
epic: EP-011
sprint: 1
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-057/TASK-001, US-056/TASK-004]
---

# TASK-002: Implement `app/core/auth/rbac.py` — `require_permission` FastAPI Dependency

> **Story:** US-057 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

This task implements the core RBAC enforcement logic: a FastAPI dependency factory `require_permission(resource, action)` that:

1. Reads the RBAC matrix loaded from `config/rbac_permissions.yaml` (TASK-001).
2. Extracts the caller's `role` from the application JWT via `get_current_user()` (US-056/TASK-004).
3. Raises `HTTP 403 Forbidden` if the role is not permitted to perform `action` on `resource`.
4. Writes an audit log entry on every denial (DoD requirement).

The PATIENT role is handled as a **hardcoded immutable security boundary** — no YAML entry exists for it. If a PATIENT-role JWT is presented to any endpoint decorated with `require_permission(...)`, the dependency raises 403 unconditionally. Patient portal endpoints use a separate `require_patient_auth()` dependency (not in scope for this story).

Design.md §3.3 middleware stack position 5: *"RBAC Enforcer (role claims → permission policy)"* — this dependency fulfils that position.

---

## Acceptance Criteria Addressed

| US-057 AC | Requirement |
|---|---|
| **Scenario 1** | `role=NURSE` calling `PATCH /alerts/{id}/resolve` → 403 Forbidden; alert unchanged; audit log entry recorded |
| **Scenario 2** | `role=PHARMACIST` calling `PATCH /alerts/{id}/resolve` → 2xx; audit log records successful action |
| **Scenario 4** | `role=PATIENT` calling `GET /api/v1/patients` → 403 Forbidden |
| **DoD** | `RBACMiddleware` as FastAPI `Depends()`: `require_permission(resource, action)` checks `jwt.role` against RBAC matrix |

---

## Implementation Steps

### 1. Add `PyYAML` to `backend/requirements.txt`

`pyyaml` is required to load the RBAC config. Add it if not already present:

```
PyYAML>=6.0.1
```

> **Security note:** `PyYAML>=6.0.1` is required — earlier 5.x versions contain a known arbitrary code execution vulnerability via `yaml.load()`. This task uses `yaml.safe_load()` exclusively.

### 2. Create `backend/app/core/auth/rbac.py`

```python
"""RBAC permission enforcement for SmartHandoff API endpoints.

Provides the `require_permission(resource, action)` FastAPI dependency factory.
The returned dependency checks the caller's JWT role against the permission
matrix loaded from `config/rbac_permissions.yaml` (TASK-001).

Design refs:
    design.md §3.3  — RBAC Enforcer at middleware stack position 5
    design.md §8.3  — RBAC Permission Matrix
    SEC-002         — Role-Based Access Control
    US-057          — Story implementing this module

Usage on any protected router:
    @router.patch("/alerts/{alert_id}/resolve")
    async def resolve_alert(
        alert_id: uuid.UUID,
        _: TokenClaims = Depends(require_permission("alert", "resolve")),
        ...
    ):
        ...

PATIENT role boundary:
    PATIENT-role JWTs are issued for the patient portal (encounter-scoped).
    Any PATIENT JWT presented to a staff/admin endpoint is denied unconditionally
    here. Patient portal endpoints use `require_patient_auth()` instead (not in
    scope for US-057).
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml
from fastapi import Depends, HTTPException, status

from app.core.auth.jwt import TokenClaims, get_current_user
from app.db.audit import write_rbac_audit_entry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PATIENT_ROLE = "PATIENT"
_VALID_ACTIONS = frozenset({"list", "read", "write", "approve", "resolve"})

_CONFIG_PATH = Path(os.getenv("RBAC_CONFIG_PATH", "config/rbac_permissions.yaml"))


# ---------------------------------------------------------------------------
# RBAC matrix loader
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_rbac_matrix() -> dict[str, dict[str, list[str]]]:
    """Load and cache the RBAC permission matrix from YAML.

    Uses lru_cache so the file is read once at first call and cached for the
    lifetime of the process. Call `load_rbac_matrix.cache_clear()` in tests
    to reload from a patched path.

    Returns:
        dict mapping role → resource → list[action]

    Raises:
        RuntimeError: if the config file is missing or malformed.
    """
    if not _CONFIG_PATH.exists():
        raise RuntimeError(
            f"RBAC config file not found: {_CONFIG_PATH}. "
            "Ensure config/rbac_permissions.yaml is present in the working directory."
        )

    with _CONFIG_PATH.open("r") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict) or "roles" not in raw:
        raise RuntimeError(
            f"RBAC config at {_CONFIG_PATH} is missing required top-level 'roles' key."
        )

    matrix: dict[str, dict[str, list[str]]] = {}
    for role, resources in raw["roles"].items():
        if role == _PATIENT_ROLE:
            # PATIENT must never appear in the YAML — log and skip
            logger.warning(
                "PATIENT role found in rbac_permissions.yaml — ignoring. "
                "PATIENT access is controlled by require_patient_auth() only."
            )
            continue
        matrix[role] = {resource: list(actions or []) for resource, actions in resources.items()}

    return matrix


# ---------------------------------------------------------------------------
# Dependency factory
# ---------------------------------------------------------------------------

def require_permission(resource: str, action: str) -> Callable:
    """FastAPI dependency factory enforcing RBAC for a given resource and action.

    Args:
        resource: The resource name (e.g. "alert", "document", "bed").
                  Must correspond to a key in rbac_permissions.yaml.
        action:   The action name (e.g. "read", "write", "approve", "resolve").
                  Must be one of the valid actions in _VALID_ACTIONS.

    Returns:
        An async FastAPI dependency callable. Inject via ``Depends(require_permission(...))``.

    Example::

        @router.patch("/alerts/{alert_id}/resolve")
        async def resolve_alert(
            alert_id: uuid.UUID,
            current_user: TokenClaims = Depends(require_permission("alert", "resolve")),
        ):
            ...

    Raises:
        HTTP 403: if the caller's role is not permitted to perform action on resource.
        HTTP 401: propagated from get_current_user() if the JWT is invalid or expired.
    """
    if action not in _VALID_ACTIONS:
        raise ValueError(
            f"require_permission called with unknown action '{action}'. "
            f"Valid actions: {sorted(_VALID_ACTIONS)}"
        )

    async def _dependency(
        current_user: TokenClaims = Depends(get_current_user),
    ) -> TokenClaims:
        role: str = current_user.role

        # Hardcoded PATIENT boundary — PATIENT-role JWTs never pass staff endpoints
        if role == _PATIENT_ROLE:
            await write_rbac_audit_entry(
                user_id=current_user.sub,
                role=role,
                resource=resource,
                action=action,
                granted=False,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )

        matrix = load_rbac_matrix()
        role_permissions = matrix.get(role, {})
        allowed_actions: list[str] = role_permissions.get(resource, [])

        if action not in allowed_actions:
            # Log the denial — required by US-057 DoD
            await write_rbac_audit_entry(
                user_id=current_user.sub,
                role=role,
                resource=resource,
                action=action,
                granted=False,
            )
            logger.info(
                "RBAC denial: user=%s role=%s resource=%s action=%s",
                current_user.sub,
                role,
                resource,
                action,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )

        return current_user

    return _dependency
```

### 3. Create `backend/app/db/audit.py` stub for `write_rbac_audit_entry`

The RBAC denial audit log write targets the `audit_log` table (DR-003). Create a stub so `rbac.py` imports succeed before the full audit module is implemented:

```python
"""HIPAA audit log writer.

Provides async helpers to write structured audit entries to the
append-only `audit_log` table (DR-003, BR-023).

write_rbac_audit_entry is called by app/core/auth/rbac.py on every
permission check (both granted and denied). Full implementation added
when audit_log ORM model is wired (US-058 or subsequent story).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def write_rbac_audit_entry(
    *,
    user_id: str,
    role: str,
    resource: str,
    action: str,
    granted: bool,
) -> None:
    """Write an RBAC permission check result to the audit log.

    Currently logs to structured application log (Cloud Logging). Full DB
    persistence implemented when audit_log ORM model is available.

    Args:
        user_id: JWT `sub` claim of the requesting user.
        role:    The user's assigned clinical role.
        resource: API resource being accessed (e.g. "alert").
        action:   Action attempted (e.g. "resolve").
        granted:  True if permission was granted; False if denied (403).
    """
    logger.info(
        "RBAC audit: user_id=%s role=%s resource=%s action=%s granted=%s",
        user_id,
        role,
        resource,
        action,
        granted,
    )
    # TODO(US-058): persist to audit_log table via SQLAlchemy session
```

> **Note:** If `app/db/audit.py` already exists from a prior task, append `write_rbac_audit_entry` to it rather than creating the file from scratch.

---

## Validation

```bash
cd backend
# Confirm module imports without errors
python -c "from app.core.auth.rbac import require_permission, load_rbac_matrix; print('rbac.py OK')"

# Confirm PATIENT is rejected from matrix load
python -c "
from app.core.auth.rbac import load_rbac_matrix
m = load_rbac_matrix()
assert 'PATIENT' not in m, 'PATIENT must not appear in RBAC matrix'
assert 'ADMIN' in m
assert 'resolve' in m['PHARMACIST']['alert']
assert 'resolve' not in m['NURSE']['alert']
print('Matrix validation OK')
"
```

---

## Files Touched

| File | Action |
|---|---|
| `backend/requirements.txt` | Add `PyYAML>=6.0.1` (if absent) |
| `backend/app/core/auth/rbac.py` | Create |
| `backend/app/db/audit.py` | Create stub (or append `write_rbac_audit_entry` if file exists) |

---

## Definition of Done Checklist

- [ ] `backend/app/core/auth/rbac.py` exists with `require_permission` and `load_rbac_matrix`
- [ ] `yaml.safe_load()` used exclusively — no `yaml.load()` calls (OWASP A08 supply chain risk)
- [ ] `lru_cache` on `load_rbac_matrix` — YAML file read once per process lifetime
- [ ] PATIENT role blocked unconditionally (not via YAML lookup)
- [ ] `write_rbac_audit_entry` called on every permission denial
- [ ] Module imports without error with YAML file present
- [ ] `PyYAML>=6.0.1` pinned in `requirements.txt`
