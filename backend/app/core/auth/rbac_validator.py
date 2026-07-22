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
      2. PATIENT role is not present (immutable security boundary).
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
