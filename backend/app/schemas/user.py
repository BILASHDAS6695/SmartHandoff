"""Pydantic schemas for admin user management API.

Used by the RBAC-protected /api/v1/admin/users endpoints to expose and
mutate ``app_user`` records.  SCIM provisioning continues to use the
SCIM-specific schemas in ``app.api.v1.admin.scim.schemas``.

Email fields use plain ``str`` rather than ``EmailStr`` because the
application stores whatever email the IdP provides, including
special-use domains such as ``.local`` used in local development/test
fixtures.  Uniqueness is enforced at the database level.

Design refs:
    design.md §3.3 Routers — /admin/users
    design.md §8.3 RBAC — Admin role required
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserBase(BaseModel):
    """Common fields for user request/response payloads."""

    email: str = Field(..., min_length=1, max_length=320)
    full_name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., min_length=1, max_length=32)
    unit: Optional[str] = Field(default=None, max_length=64)

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: str) -> str:
        """Store role in lowercase to match ``AppUser.role`` convention."""
        if isinstance(value, str):
            return value.lower().strip()
        return value


class UserCreateRequest(UserBase):
    """Payload for POST /api/v1/admin/users — admin-created staff account."""

    pass


class UserUpdateRequest(UserBase):
    """Payload for PATCH /api/v1/admin/users/{id}.

    All fields are optional to support partial updates.
    """

    email: Optional[str] = Field(default=None, min_length=1, max_length=320)
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    role: Optional[str] = Field(default=None, min_length=1, max_length=32)


class UserResponse(UserBase):
    """Outbound user representation for admin user management."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    deprovisioned_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    """Envelope for GET /api/v1/admin/users."""

    users: list[UserResponse]
    total: int


class BulkRoleAssignRequest(BaseModel):
    """Payload for POST /api/v1/admin/users/bulk-assign-roles."""

    user_ids: list[uuid.UUID] = Field(..., min_length=1, description="UUIDs of users to update")
    role: str = Field(..., min_length=1, max_length=32, description="Target role from RBAC matrix")

    @field_validator("role", mode="before")
    @classmethod
    def _normalize_role(cls, value: str) -> str:
        if isinstance(value, str):
            return value.lower().strip()
        return value


class BulkRoleAssignResult(BaseModel):
    """Result item for a single user in a bulk role assignment."""

    user_id: uuid.UUID
    previous_role: str
    new_role: str


class BulkRoleAssignResponse(BaseModel):
    """Envelope for bulk role assignment response."""

    assigned: list[BulkRoleAssignResult]
    not_found: list[uuid.UUID]
    total_requested: int
    total_assigned: int
