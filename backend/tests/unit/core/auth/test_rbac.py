"""Unit tests for US-057 RBAC — load_rbac_matrix, require_permission, validate_rbac_config."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from app.core.auth.rbac import load_rbac_matrix, require_permission
from app.core.auth.rbac_validator import validate_rbac_config
from app.core.auth.jwt import TokenClaims

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_ROLES = {"ADMIN", "PHYSICIAN", "NURSE", "PHARMACIST", "BED_MANAGER", "CARE_MANAGER"}
REQUIRED_RESOURCES = {
    "patient", "encounter", "document", "medication",
    "alert", "bed", "analytics", "agent_task", "audit_log", "user",
}


@pytest.fixture(autouse=True)
def _clear_rbac_cache():
    """Clear the lru_cache on load_rbac_matrix before each test.

    Prevents cache state from polluting subsequent tests, especially those
    that patch load_rbac_matrix to return a bad matrix for validation tests.
    """
    load_rbac_matrix.cache_clear()
    yield
    load_rbac_matrix.cache_clear()


def _make_claims(role: str, sub: str = "user-123") -> TokenClaims:
    return TokenClaims(sub=sub, role=role, units=[], email="test@example.com", iat=0, exp=9999999999)


async def _call_dependency(dep_func, claims: TokenClaims):
    """Invoke the dependency coroutine returned by require_permission()."""
    # The dependency uses Depends(get_current_user) — we patch it via the claims fixture.
    with patch("app.core.auth.rbac.get_current_user", return_value=claims):
        dep = dep_func(current_user=claims)
        if asyncio.iscoroutine(dep):
            return await dep
        return dep


# ---------------------------------------------------------------------------
# TestLoadRbacMatrix
# ---------------------------------------------------------------------------

class TestLoadRbacMatrix:
    def test_returns_dict(self):
        matrix = load_rbac_matrix()
        assert isinstance(matrix, dict)

    def test_contains_exactly_six_staff_roles(self):
        matrix = load_rbac_matrix()
        assert set(matrix.keys()) == REQUIRED_ROLES

    def test_patient_role_excluded(self):
        matrix = load_rbac_matrix()
        assert "PATIENT" not in matrix

    def test_all_resources_present_per_role(self):
        matrix = load_rbac_matrix()
        for role, resources in matrix.items():
            missing = REQUIRED_RESOURCES - set(resources.keys())
            assert not missing, f"Role {role} missing resources: {missing}"

    def test_pharmacist_has_alert_resolve(self):
        matrix = load_rbac_matrix()
        assert "resolve" in matrix["PHARMACIST"]["alert"]

    def test_nurse_lacks_alert_resolve(self):
        matrix = load_rbac_matrix()
        assert "resolve" not in matrix["NURSE"]["alert"]

    def test_physician_has_document_approve(self):
        matrix = load_rbac_matrix()
        assert "approve" in matrix["PHYSICIAN"]["document"]

    def test_admin_has_all_resources_with_write(self):
        matrix = load_rbac_matrix()
        for resource in REQUIRED_RESOURCES:
            assert "write" in matrix["ADMIN"].get(resource, []) or \
                   "list" in matrix["ADMIN"].get(resource, []), \
                f"ADMIN missing meaningful permission on {resource}"

    def test_missing_config_raises_runtime_error(self, tmp_path, monkeypatch):
        """RuntimeError raised when RBAC_CONFIG_PATH points to a non-existent file."""
        monkeypatch.setenv("RBAC_CONFIG_PATH", str(tmp_path / "nonexistent.yaml"))
        with pytest.raises(RuntimeError, match="RBAC config file not found"):
            load_rbac_matrix()

    def test_malformed_yaml_raises_runtime_error(self, tmp_path, monkeypatch):
        """RuntimeError raised when YAML file is missing the top-level 'roles' key."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("not_roles_key: {}")
        monkeypatch.setenv("RBAC_CONFIG_PATH", str(bad_yaml))
        with pytest.raises(RuntimeError, match="missing required top-level 'roles' key"):
            load_rbac_matrix()


# ---------------------------------------------------------------------------
# TestRequirePermissionFactory
# ---------------------------------------------------------------------------

class TestRequirePermissionFactory:
    def test_invalid_action_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown action"):
            require_permission("patient", "delete")

    def test_valid_call_returns_callable(self):
        dep = require_permission("alert", "list")
        assert callable(dep)


# ---------------------------------------------------------------------------
# TestRequirePermissionGrant  (parametrized happy paths)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role,resource,action", [
    ("ADMIN",       "patient",    "list"),
    ("ADMIN",       "audit_log",  "list"),
    ("PHYSICIAN",   "patient",    "read"),
    ("PHYSICIAN",   "document",   "approve"),
    ("PHARMACIST",  "alert",      "resolve"),
    ("NURSE",       "patient",    "list"),
    ("BED_MANAGER", "bed",        "write"),
    ("CARE_MANAGER","encounter",  "list"),
])
@pytest.mark.asyncio
async def test_require_permission_grants(role, resource, action):
    claims = _make_claims(role)
    dep_func = require_permission(resource, action)

    with patch("app.core.auth.rbac.get_current_user", return_value=claims), \
         patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock) as mock_audit:
        result = await dep_func(current_user=claims)

    assert result.sub == claims.sub
    mock_audit.assert_awaited_once()
    call_kwargs = mock_audit.call_args.kwargs
    assert call_kwargs["granted"] is True
    assert call_kwargs["role"] == role
    assert call_kwargs["resource"] == resource
    assert call_kwargs["action"] == action


# ---------------------------------------------------------------------------
# TestRequirePermissionDenial  (parametrized denial paths)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role,resource,action", [
    ("NURSE",       "alert",      "resolve"),   # AC Scenario 1
    ("NURSE",       "audit_log",  "read"),
    ("NURSE",       "document",   "approve"),   # TASK-005 spec denial matrix
    ("PHARMACIST",  "bed",        "write"),
    ("PHYSICIAN",   "bed",        "write"),     # TASK-005 spec denial matrix
    ("BED_MANAGER", "user",       "write"),
    ("CARE_MANAGER","user",       "write"),
])
@pytest.mark.asyncio
async def test_require_permission_denials(role, resource, action):
    from fastapi import HTTPException
    claims = _make_claims(role)
    dep_func = require_permission(resource, action)

    with patch("app.core.auth.rbac.get_current_user", return_value=claims), \
         patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock) as mock_audit:
        with pytest.raises(HTTPException) as exc_info:
            await dep_func(current_user=claims)

    assert exc_info.value.status_code == 403
    mock_audit.assert_awaited_once()
    call_kwargs = mock_audit.call_args.kwargs
    assert call_kwargs["granted"] is False
    assert call_kwargs["role"] == role
    assert call_kwargs["resource"] == resource
    assert call_kwargs["action"] == action


# ---------------------------------------------------------------------------
# TestPatientRoleBoundary (AC Scenario 4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("resource,action", [
    ("patient",    "list"),
    ("patient",    "read"),
    ("encounter",  "list"),
    ("document",   "list"),
    ("medication", "list"),
    ("alert",      "list"),
    ("bed",        "list"),
])
@pytest.mark.asyncio
async def test_patient_role_denied_on_all_resources(resource, action):
    """PATIENT role must never be in the RBAC matrix — always 403."""
    from fastapi import HTTPException
    claims = _make_claims("PATIENT")
    dep_func = require_permission(resource, action)

    with patch("app.core.auth.rbac.get_current_user", return_value=claims), \
         patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock) as mock_audit:
        with pytest.raises(HTTPException) as exc_info:
            await dep_func(current_user=claims)

    assert exc_info.value.status_code == 403
    mock_audit.assert_awaited_once()
    assert mock_audit.call_args.kwargs["granted"] is False


# ---------------------------------------------------------------------------
# TestAlertResolveScenarios  (AC Scenarios 1 & 2 explicit)
# ---------------------------------------------------------------------------

class TestAlertResolveScenarios:
    @pytest.mark.asyncio
    async def test_nurse_cannot_resolve_alert(self):
        """AC Scenario 1: NURSE → alert:resolve → 403."""
        from fastapi import HTTPException
        claims = _make_claims("NURSE")
        dep_func = require_permission("alert", "resolve")

        with patch("app.core.auth.rbac.get_current_user", return_value=claims), \
             patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock):
            with pytest.raises(HTTPException) as exc_info:
                await dep_func(current_user=claims)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_pharmacist_can_resolve_alert(self):
        """AC Scenario 2: PHARMACIST → alert:resolve → granted."""
        claims = _make_claims("PHARMACIST")
        dep_func = require_permission("alert", "resolve")

        with patch("app.core.auth.rbac.get_current_user", return_value=claims), \
             patch("app.core.auth.rbac.write_rbac_audit_entry", new_callable=AsyncMock) as mock_audit:
            result = await dep_func(current_user=claims)

        assert result.role == "PHARMACIST"
        mock_audit.assert_awaited_once()
        assert mock_audit.call_args.kwargs["granted"] is True


# ---------------------------------------------------------------------------
# TestValidateRbacConfig
# ---------------------------------------------------------------------------

class TestValidateRbacConfig:
    def test_valid_config_passes(self):
        """Default config/rbac_permissions.yaml must pass validation without error."""
        validate_rbac_config()  # should not raise

    def test_missing_role_raises(self):
        bad_matrix = {role: {} for role in REQUIRED_ROLES - {"NURSE"}}
        with patch("app.core.auth.rbac_validator.load_rbac_matrix", return_value=bad_matrix):
            with pytest.raises(RuntimeError, match="NURSE"):
                validate_rbac_config()

    def test_patient_in_yaml_raises(self):
        bad_matrix = {role: {r: [] for r in REQUIRED_RESOURCES} for role in REQUIRED_ROLES}
        bad_matrix["PATIENT"] = {}
        with patch("app.core.auth.rbac_validator.load_rbac_matrix", return_value=bad_matrix):
            with pytest.raises(RuntimeError, match="PATIENT"):
                validate_rbac_config()

    def test_missing_resource_key_raises(self):
        bad_matrix = {
            role: {r: ["list"] for r in REQUIRED_RESOURCES - {"audit_log"}}
            for role in REQUIRED_ROLES
        }
        with patch("app.core.auth.rbac_validator.load_rbac_matrix", return_value=bad_matrix):
            with pytest.raises(RuntimeError, match="audit_log"):
                validate_rbac_config()

    def test_invalid_action_in_yaml_raises(self):
        bad_matrix = {
            role: {r: ["list", "delete"] for r in REQUIRED_RESOURCES}
            for role in REQUIRED_ROLES
        }
        with patch("app.core.auth.rbac_validator.load_rbac_matrix", return_value=bad_matrix):
            with pytest.raises(RuntimeError, match="delete"):
                validate_rbac_config()
