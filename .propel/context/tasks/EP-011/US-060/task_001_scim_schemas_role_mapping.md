---
id: TASK-001
title: "Create SCIM 2.0 Pydantic Schemas + `config/scim_role_mapping.yaml`"
user_story: US-060
epic: EP-011
sprint: 2
layer: Backend / Config
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-006/TASK-001]
---

# TASK-001: Create SCIM 2.0 Pydantic Schemas + `config/scim_role_mapping.yaml`

> **Story:** US-060 | **Epic:** EP-011 | **Sprint:** 2 | **Layer:** Backend / Config | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

All SCIM 2.0 endpoints share two foundational artefacts that must exist before any router is written:

1. **`config/scim_role_mapping.yaml`** — Maps SCIM `enterpriseUser.department` values to SmartHandoff `AppRole` enum values. US-060 Technical Notes specify the canonical mapping (`Nursing → NURSE`, `Pharmacy → PHARMACIST`, etc.). Storing this in YAML (not hardcoded) allows hospital-specific customisation without a code change (AC Scenario 4 — department change triggers role update via this mapping).

2. **`backend/app/api/v1/admin/scim/schemas.py`** — Pydantic v2 models representing the SCIM 2.0 User resource (RFC 7643 §4.1) and the `ListResponse` container (RFC 7643 §3.3). These schemas are the single source of truth for all SCIM request parsing and response serialisation, ensuring RFC compliance across all six endpoints.

Design.md §7.4 AIR-032 specifies the SCIM user attributes that must be supported; the Pydantic models enforce this contract at the API boundary.

---

## Acceptance Criteria Addressed

| US-060 AC | Requirement |
|---|---|
| **Scenario 1** | `role=NURSE` set from `enterpriseUser.department=Nursing` via mapping file |
| **Scenario 4** | `app_user.role` updates from `NURSE → PHARMACIST` via department-to-role mapping |
| **DoD** | `config/scim_role_mapping.yaml` present; SCIM 2.0 response schemas (RFC 7643) |

---

## Implementation Steps

### 1. Create `config/scim_role_mapping.yaml`

```yaml
# SCIM 2.0 department → SmartHandoff role mapping
# Used by: backend/app/api/v1/admin/scim/schemas.py (ScimRoleMapper)
# RFC ref:  RFC 7643 §4.1 enterpriseUser.department
# Design:   design.md §7.4 AIR-032
#
# Keys  = values that arrive in urn:ietf:params:scim:schemas:extension:
#           enterprise:2.0:User.department
# Values = SmartHandoff AppRole enum member names (app/models/user.py)
#
# Update this file for hospital-specific department naming without
# modifying application code.

role_mapping:
  Nursing: NURSE
  Pharmacy: PHARMACIST
  Medicine: PHYSICIAN
  BedManagement: BED_MANAGER
  Administration: ADMIN
  # Add hospital-specific aliases below:
  # "ICU Nursing": NURSE
  # "Clinical Pharmacy": PHARMACIST
```

Place this file at the repository root as `config/scim_role_mapping.yaml` so it is accessible from both the backend service and the Terraform secrets module if needed.

---

### 2. Create `backend/app/api/v1/admin/scim/__init__.py`

Empty init to register the package:

```python
"""SCIM 2.0 User provisioning API package.

Endpoints: POST, GET (single + list), PATCH, PUT, DELETE /api/v1/admin/scim/Users
Auth:       SCIM bearer token (separate from staff JWTs — see scim_auth.py)
RFC refs:   RFC 7643 (SCIM Schema), RFC 7644 (SCIM Protocol)
Design:     design.md §7.4 AIR-032
"""
```

---

### 3. Create `backend/app/api/v1/admin/scim/schemas.py`

```python
"""SCIM 2.0 Pydantic v2 schemas — RFC 7643/7644 compliance.

Covers:
  - ScimName          — name sub-object
  - ScimEmail         — emails[] entry
  - ScimEnterpriseExt — urn:ietf:params:scim:schemas:extension:enterprise:2.0:User
  - ScimUserRequest   — inbound POST/PUT body
  - ScimPatchOp       — inbound PATCH body (RFC 7644 §3.5.2)
  - ScimUserResponse  — outbound single-user representation
  - ScimListResponse  — outbound list-users container (RFC 7643 §3.3)
  - ScimRoleMapper    — loads config/scim_role_mapping.yaml

Design refs:
    design.md §7.4 AIR-032  — SCIM user attributes required
    US-060 Technical Notes   — exact SCIM field list
    RFC 7643 §4.1            — User resource schema
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, EmailStr, Field, field_validator

# ---------------------------------------------------------------------------
# Sub-objects
# ---------------------------------------------------------------------------

SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_ENTERPRISE_SCHEMA = (
    "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
)
SCIM_LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


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
    """Single operation within a PATCH body (RFC 7644 §3.5.2)."""

    op: Literal["add", "replace", "remove"]
    path: str | None = None
    value: Any = None


class ScimPatchOp(BaseModel):
    """Inbound SCIM PATCH body."""

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
    id: str                    # SmartHandoff user UUID (mapped to SCIM id)
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
    """Loads config/scim_role_mapping.yaml and maps department → AppRole name.

    Usage:
        mapper = ScimRoleMapper.load()
        role_name = mapper.map("Nursing")  # → "NURSE"

    Raises:
        ValueError if department is not in the mapping.
    """

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = {k.lower(): v for k, v in mapping.items()}

    @classmethod
    def load(cls, path: str | None = None) -> "ScimRoleMapper":
        """Load mapping from YAML file.

        Searches for config/scim_role_mapping.yaml relative to repository
        root (two levels up from this file's package directory).
        """
        if path is None:
            # Resolve: backend/app/api/v1/admin/scim/ → repo root → config/
            base = Path(__file__).resolve().parents[6]
            path = str(base / "config" / "scim_role_mapping.yaml")

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        mapping: dict[str, str] = data.get("role_mapping", {})
        if not mapping:
            raise ValueError(
                f"scim_role_mapping.yaml at {path} has no role_mapping entries"
            )
        return cls(mapping)

    def map(self, department: str) -> str:
        """Return the AppRole name for a department string.

        Raises:
            ValueError: if the department is not in the mapping file.
        """
        role = self._mapping.get(department.lower())
        if role is None:
            raise ValueError(
                f"SCIM department '{department}' has no role mapping. "
                "Add it to config/scim_role_mapping.yaml."
            )
        return role
```

---

### 4. Add `pyyaml` to `backend/requirements.txt`

```
# SCIM role mapping YAML loader (US-060)
pyyaml>=6.0.1
```

> **Note:** PyYAML is likely already present (used by other config loaders); add only if not present.

---

## Files Created / Modified

| File | Action |
|---|---|
| `config/scim_role_mapping.yaml` | **Create** |
| `backend/app/api/v1/admin/scim/__init__.py` | **Create** |
| `backend/app/api/v1/admin/scim/schemas.py` | **Create** |
| `backend/requirements.txt` | **Modify** — add `pyyaml` if absent |

---

## Validation

```bash
# Verify YAML loads without error
python -c "
import yaml
with open('config/scim_role_mapping.yaml') as f:
    d = yaml.safe_load(f)
print('Mapping entries:', list(d['role_mapping'].keys()))
"

# Verify Pydantic schemas parse a sample SCIM payload
python -c "
import sys; sys.path.insert(0, 'backend')
from app.api.v1.admin.scim.schemas import ScimUserRequest, SCIM_ENTERPRISE_SCHEMA
payload = {
    'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
    'userName': 'jdoe@hospital.org',
    'name': {'givenName': 'Jane', 'familyName': 'Doe'},
    'emails': [{'value': 'jdoe@hospital.org', 'primary': True}],
    SCIM_ENTERPRISE_SCHEMA: {'department': 'Nursing'},
}
u = ScimUserRequest.model_validate(payload)
print('Parsed userName:', u.userName)
print('Department:', u.enterprise.department if u.enterprise else 'None')
"
```
