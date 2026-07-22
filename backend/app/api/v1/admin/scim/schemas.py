"""SCIM 2.0 Pydantic v2 schemas — RFC 7643/7644 compliance.

Covers:
  - ScimName          — name sub-object (RFC 7643 §4.1.1)
  - ScimEmail         — emails[] entry (RFC 7643 §4.1.2)
  - ScimEnterpriseExt — urn:ietf:params:scim:schemas:extension:enterprise:2.0:User
  - ScimUserRequest   — inbound POST/PUT body
  - ScimPatchOperation — single PatchOp entry (RFC 7644 §3.5.2)
  - ScimPatchOp       — inbound PATCH body
  - ScimMeta          — meta sub-attribute (RFC 7643 §3.1)
  - ScimUserResponse  — outbound single-user representation
  - ScimListResponse  — outbound list-users container (RFC 7643 §3.3)
  - ScimRoleMapper    — loads config/scim_role_mapping.yaml

Design refs:
    design.md §7.4 AIR-032  — SCIM user attributes required
    US-060 Technical Notes   — exact SCIM field list
    RFC 7643 §4.1            — User resource schema
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, EmailStr, Field, field_validator

# ---------------------------------------------------------------------------
# SCIM URN constants
# ---------------------------------------------------------------------------

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_ENTERPRISE_SCHEMA = (
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
)
SCIM_LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


# ---------------------------------------------------------------------------
# Sub-objects
# ---------------------------------------------------------------------------

class ScimName(BaseModel):
    """RFC 7643 §4.1.1 name sub-attribute."""

    familyName: str | None = None
    givenName: str | None = None


class ScimEmail(BaseModel):
    """RFC 7643 §4.1.2 emails multi-value sub-attribute."""

    value: EmailStr
    primary: bool = False
    type: str = "work"


class ScimEnterpriseExt(BaseModel):
    """urn:ietf:params:scim:schemas:extension:enterprise:2.0:User subset.

    Only `department` is used for role mapping (US-060 Technical Notes).
    Additional fields are accepted and ignored to avoid breaking IdP payloads.
    """

    department: str | None = None

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ScimUserRequest(BaseModel):
    """Inbound SCIM 2.0 User body for POST and PUT.

    Validates the mandatory `userName` field; all PHI fields are optional
    to accommodate partial IdP payloads.
    """

    schemas: list[str] = Field(default_factory=lambda: [SCIM_USER_SCHEMA])
    userName: str  # maps to app_user.email
    externalId: str | None = None  # IdP-assigned ID — stored as app_user.scim_id
    name: ScimName | None = None
    emails: list[ScimEmail] = Field(default_factory=list)
    active: bool = True
    # Enterprise extension — carries the department for role mapping
    enterprise: ScimEnterpriseExt | None = Field(
        alias=SCIM_ENTERPRISE_SCHEMA, default=None
    )

    model_config = {"populate_by_name": True}

    @field_validator("userName")
    @classmethod
    def username_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("userName must not be empty")
        return v.lower().strip()


class ScimPatchOperation(BaseModel):
    """Single operation within a PATCH body (RFC 7644 §3.5.2).

    RFC 7644 §3.5.2 treats ``op`` as case-insensitive; this validator
    normalises to lowercase before the Literal check.
    """

    op: Literal["add", "replace", "remove"]
    path: str | None = None
    value: Any = None

    @field_validator("op", mode="before")
    @classmethod
    def _normalise_op(cls, v: Any) -> str:
        """Lowercase op before Literal validation (RFC 7644 §3.5.2)."""
        if isinstance(v, str):
            return v.lower()
        return v


class ScimPatchOp(BaseModel):
    """Inbound SCIM PATCH body (RFC 7644 §3.5.2)."""

    schemas: list[str] = Field(
        default_factory=lambda: [SCIM_PATCH_OP_SCHEMA]
    )
    Operations: list[ScimPatchOperation]


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class ScimMeta(BaseModel):
    """RFC 7643 §3.1 meta sub-attribute."""

    resourceType: str = "User"
    location: str | None = None


class ScimUserResponse(BaseModel):
    """Outbound SCIM 2.0 User resource (RFC 7643 §4.1)."""

    schemas: list[str] = Field(
        default_factory=lambda: [SCIM_USER_SCHEMA, SCIM_ENTERPRISE_SCHEMA]
    )
    id: str                        # SmartHandoff user UUID (SCIM id)
    externalId: str | None = None  # IdP-assigned scim_id
    userName: str
    name: ScimName | None = None
    emails: list[ScimEmail] = Field(default_factory=list)
    active: bool = True
    meta: ScimMeta | None = None


class ScimListResponse(BaseModel):
    """RFC 7643 §3.3 ListResponse container."""

    schemas: list[str] = Field(
        default_factory=lambda: [SCIM_LIST_RESPONSE_SCHEMA]
    )
    totalResults: int
    startIndex: int = 1
    itemsPerPage: int
    Resources: list[ScimUserResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Role mapper
# ---------------------------------------------------------------------------

class ScimRoleMapper:
    """Loads config/scim_role_mapping.yaml and maps department → SmartHandoff role.

    Usage::
        mapper = ScimRoleMapper.load()
        role_name = mapper.map("Nursing")  # → "NURSE"

    Raises:
        ValueError if department is not in the mapping.
    """

    def __init__(self, mapping: dict[str, str]) -> None:
        # Normalise keys to lowercase for case-insensitive matching
        self._mapping = {k.lower(): v for k, v in mapping.items()}

    @classmethod
    def load(cls, path: str | None = None) -> "ScimRoleMapper":
        """Load mapping from YAML file.

        Searches for ``config/scim_role_mapping.yaml`` relative to the
        repository root (resolved upward from this file's location).
        """
        if path is None:
            # File lives at: backend/app/api/v1/admin/scim/schemas.py
            # Repository root is 6 parents up
            base = Path(__file__).resolve().parents[6]
            resolved = base / "config" / "scim_role_mapping.yaml"
            # Fallback: look relative to cwd (CI / test runner)
            if not resolved.exists():
                resolved = Path("config") / "scim_role_mapping.yaml"
            path = str(resolved)

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        mapping: dict[str, str] = data.get("role_mapping", {})
        if not mapping:
            raise ValueError(
                f"scim_role_mapping.yaml at {path} has no role_mapping entries"
            )
        return cls(mapping)

    def map(self, department: str) -> str:
        """Return the role name string for a SCIM department value.

        Args:
            department: Value from ``enterpriseUser.department``.

        Returns:
            A role name string (e.g. ``"NURSE"``).

        Raises:
            ValueError: if the department has no mapping.
        """
        role = self._mapping.get(department.lower())
        if role is None:
            raise ValueError(
                f"SCIM department '{department}' has no role mapping. "
                "Add it to config/scim_role_mapping.yaml."
            )
        return role
