"""RBAC permission enforcement for SmartHandoff API endpoints.

Provides the `require_permission(resource, action)` FastAPI dependency factory.
The returned dependency checks the caller's JWT role against the permission
matrix loaded from `config/rbac_permissions.yaml` (US-057/TASK-001).

Design refs:
    design.md §3.3  — RBAC Enforcer at middleware stack position 5
    design.md §8.3  — RBAC Permission Matrix
    SEC-002         — Role-Based Access Control
    US-057          — Story implementing this module

Usage on any protected router:
    @router.patch("/alerts/{alert_id}/resolve")
    async def resolve_alert(
        alert_id: uuid.UUID,
        current_user: TokenClaims = Depends(require_permission("alert", "resolve")),
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
    to reload after changing ``RBAC_CONFIG_PATH`` in the environment.

    The config path is resolved at call time (not import time) so that tests
    can set ``os.environ['RBAC_CONFIG_PATH']`` before calling this function
    after clearing the cache.

    Returns:
        dict mapping role → resource → list[action]

    Raises:
        RuntimeError: if the config file is missing or malformed.
    """
    config_path = Path(os.getenv("RBAC_CONFIG_PATH", str(_CONFIG_PATH)))

    if not config_path.exists():
        raise RuntimeError(
            f"RBAC config file not found: {config_path}. "
            "Ensure config/rbac_permissions.yaml is present in the working directory."
        )

    with config_path.open("r") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict) or "roles" not in raw:
        raise RuntimeError(
            f"RBAC config at {config_path} is missing required top-level 'roles' key."
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
        matrix[role] = {
            resource: list(actions or [])
            for resource, actions in resources.items()
        }

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
        ValueError:  if action is not a recognised action name (caught at definition time).
        HTTP 403:    if the caller's role is not permitted to perform action on resource.
        HTTP 401:    propagated from get_current_user() if the JWT is invalid or expired.
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
            # Log the denial — required by US-057 DoD and HIPAA §164.312(b)
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

        # Log successful access — AC Scenario 2 / HIPAA §164.312(b) audit trail
        await write_rbac_audit_entry(
            user_id=current_user.sub,
            role=role,
            resource=resource,
            action=action,
            granted=True,
        )

        return current_user

    return _dependency
