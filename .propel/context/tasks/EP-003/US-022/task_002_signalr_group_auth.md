---
id: TASK-002
title: "Implement SignalR Group Membership Management and JWT Authentication Middleware for Hub Connections"
user_story: US-022
epic: EP-003
sprint: 2
layer: Backend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001]
---

# TASK-002: Implement SignalR Group Membership Management and JWT Authentication Middleware for Hub Connections

> **Story:** US-022 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Backend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-022 specifies two closely related security and routing requirements:

> *"SignalR hub secured: JWT validation middleware on hub connection"* (Scenario 4)
> *"Group routing by encounter, unit, and role — users in unit 4B do NOT receive events for unit 3A"* (Scenario 2)

In the Azure SignalR Service model, client group membership is driven by the **negotiate endpoint** — the FastAPI `/signalr/negotiate` endpoint generates a client access token that encodes which groups the client should join. The Angular `HubConnectionBuilder` calls this endpoint before establishing the WebSocket, so the JWT claim validation and group assignment happen server-side at connection time, before any WebSocket state is created.

This task creates:
1. `POST /api/v1/signalr/negotiate` — validates staff JWT, extracts claims, and returns an Azure SignalR client access token scoped to the correct groups.
2. `GroupResolver` — maps JWT claims (`unit_id`, `role`, `encounter_ids`) to the group name set per US-022 naming convention.
3. Unit tests for group routing logic (US-022 DoD: *"unit tests: group routing logic for encounter/unit/role subscriptions"*).
4. GCP Secret Manager entry for the connection string (Terraform snippet).

---

## Acceptance Criteria Addressed

| US-022 AC | Requirement |
|---|---|
| **Scenario 2** | Nurse unit 3A receives event; nurse unit 4B does NOT receive it; pharmacist role group receives it |
| **Scenario 4** | Connection without valid JWT refused with 401; no groups created |
| **DoD** | JWT validation middleware on hub connection; unit tests for group routing |

---

## Implementation Steps

### 1. Create `backend/app/signalr/group_resolver.py`

```python
"""GroupResolver — maps JWT user claims to Azure SignalR group names.

US-022 Group naming convention (DoD):
  - encounter-{encounter_id}   : events for a specific encounter
  - unit-{unit_id}             : events for all encounters in a unit
  - role-{role_name}           : events for a specific clinical role

A user is added to ALL groups they are entitled to at negotiate time.
The broadcaster (TASK-001) sends to all three groups per event;
Azure SignalR delivers only to the intersection of what the client joined.

No PHI is embedded in group names — only opaque IDs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class UserClaims:
    """Subset of JWT claims relevant to SignalR group assignment.

    Populated from the validated JWT payload by the negotiate endpoint.
    """

    user_id: str
    role: str                        # e.g. "nurse", "pharmacist", "physician"
    unit_id: str | None              # e.g. "3A" — None for non-unit-bound roles
    encounter_ids: list[str] = field(default_factory=list)  # active encounter IDs


class GroupResolver:
    """Pure function wrapper: resolves group names from user claims.

    Stateless — safe to instantiate once and reuse across requests.
    """

    def resolve(self, claims: UserClaims) -> list[str]:
        """Return the list of SignalR group names for the given user.

        Rules (US-022 Scenario 2):
          1. Always join role group.
          2. Join unit group if unit_id is present.
          3. Join one encounter group per active encounter_id.

        Order is deterministic for testability.
        """
        groups: list[str] = []

        # Role group — every authenticated user belongs to their role group.
        groups.append(f"role-{claims.role}")

        # Unit group — unit-bound staff (nurses, charge nurses, bed managers).
        if claims.unit_id:
            groups.append(f"unit-{claims.unit_id}")

        # Per-encounter groups — subscribes to specific active encounters.
        for enc_id in sorted(claims.encounter_ids):
            groups.append(f"encounter-{enc_id}")

        return groups
```

### 2. Create `backend/app/routers/signalr_negotiate.py`

```python
"""Router: POST /api/v1/signalr/negotiate

Negotiate endpoint for Azure SignalR Service.
Angular HubConnectionBuilder calls this before opening the WebSocket.

Flow:
  1. Validate staff JWT via get_current_staff_user dependency.
  2. Extract unit_id, role, encounter_ids from token claims.
  3. Call GroupResolver to compute group list.
  4. Call Azure SignalR Management SDK (or REST API) to generate a client
     access token scoped to those groups.
  5. Return { url, accessToken } to Angular client.

Security (US-022 Scenario 4):
  - get_current_staff_user raises HTTP 401 if JWT is missing or invalid.
  - No groups are created when authentication fails.

Reference:
  Azure SignalR negotiate REST:
  POST /api/v1/hubs/{hub}/negotiate?negotiateVersion=1
  Returns: { url, accessToken }
"""
from __future__ import annotations

import logging
import time
from typing import Annotated
from uuid import UUID

import jwt as pyjwt
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.dependencies import get_current_staff_user
from app.auth.models import StaffUser
from app.config.settings import settings
from app.signalr.broadcaster import _generate_access_token, _parse_connection_string
from app.signalr.group_resolver import GroupResolver, UserClaims

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/signalr", tags=["signalr"])

_resolver = GroupResolver()


class NegotiateResponse(BaseModel):
    """Response returned to Angular HubConnectionBuilder.withUrl(negotiate_url)."""

    url: str
    accessToken: str  # noqa: N815 — Angular SDK expects camelCase


@router.post(
    "/negotiate",
    response_model=NegotiateResponse,
    status_code=status.HTTP_200_OK,
    summary="Negotiate Azure SignalR client access token",
    description=(
        "Called by Angular HubConnectionBuilder before establishing WebSocket. "
        "Validates staff JWT and returns a scoped Azure SignalR client token. "
        "Returns 401 if JWT is invalid or missing."
    ),
)
async def negotiate(
    current_user: Annotated[StaffUser, Depends(get_current_staff_user)],
) -> NegotiateResponse:
    """Generate a client access token scoped to the user's groups.

    US-022 Scenario 4: authentication failure returns 401 before this handler runs.
    """
    claims = UserClaims(
        user_id=str(current_user.id),
        role=current_user.role,
        unit_id=getattr(current_user, "unit_id", None),
        encounter_ids=[str(eid) for eid in getattr(current_user, "active_encounter_ids", [])],
    )
    groups = _resolver.resolve(claims)

    endpoint, access_key = _parse_connection_string(settings.azure_signalr_connection_string)
    hub_url = f"{endpoint}/client/?hub=dashboard"

    # Generate a client-scoped token — audience is the WebSocket URL.
    # Groups are embedded as a custom claim consumed by Azure SignalR Service.
    client_token = pyjwt.encode(
        {
            "aud": hub_url,
            "sub": str(current_user.id),
            "exp": int(time.time()) + 3600,
            "groups": groups,
        },
        access_key,
        algorithm="HS256",
    )

    logger.info(
        "SignalR negotiate issued",
        extra={"user_id": str(current_user.id), "groups": groups},
    )

    return NegotiateResponse(url=hub_url, accessToken=client_token)
```

### 3. Register negotiate router in `backend/app/main.py`

```python
from app.routers.signalr_negotiate import router as negotiate_router

app.include_router(negotiate_router, prefix="/api/v1")
```

### 4. Create GCP Secret Manager Terraform resource (add to `infra/terraform/modules/secrets/main.tf`)

```hcl
# Azure SignalR Service connection string — used by FastAPI backend Cloud Run service.
# US-022: SignalR hub requires the connection string for REST API broadcasts
# and client token generation at negotiate endpoint.
resource "google_secret_manager_secret" "azure_signalr_connection_string" {
  project   = var.project_id
  secret_id = "azure-signalr-connection-string"

  replication {
    auto {}
  }

  labels = {
    managed_by = "terraform"
    component  = "signalr"
    us         = "us-022"
  }
}

# Secret version is populated out-of-band by ops team — Terraform manages the
# secret resource only, not the value, to keep the key out of state files.
```

### 5. Create `backend/tests/unit/signalr/test_group_resolver.py`

```python
"""Unit tests for GroupResolver — US-022 DoD: group routing logic tests.

Covers:
  - Nurse in unit 3A joins role-nurse, unit-3A, and per-encounter groups.
  - Pharmacist (no unit) joins role-pharmacist and per-encounter groups only.
  - Nurse in unit 4B does NOT appear in unit-3A groups (isolation test).
  - User with no encounter_ids joins only role and unit groups.
  - Group name format matches US-022 DoD naming convention exactly.
"""
from __future__ import annotations

import pytest

from app.signalr.group_resolver import GroupResolver, UserClaims


@pytest.fixture
def resolver() -> GroupResolver:
    return GroupResolver()


class TestGroupResolverNurseUnit3A:
    def test_nurse_3a_joins_role_group(self, resolver):
        claims = UserClaims(user_id="u1", role="nurse", unit_id="3A", encounter_ids=["enc-abc"])
        groups = resolver.resolve(claims)
        assert "role-nurse" in groups

    def test_nurse_3a_joins_unit_group(self, resolver):
        claims = UserClaims(user_id="u1", role="nurse", unit_id="3A", encounter_ids=[])
        groups = resolver.resolve(claims)
        assert "unit-3A" in groups

    def test_nurse_3a_joins_encounter_group(self, resolver):
        claims = UserClaims(user_id="u1", role="nurse", unit_id="3A", encounter_ids=["enc-abc"])
        groups = resolver.resolve(claims)
        assert "encounter-enc-abc" in groups

    def test_nurse_3a_does_not_join_unit_4b(self, resolver):
        """US-022 Scenario 2: nurse in unit 3A must NOT be in unit-4B group."""
        claims = UserClaims(user_id="u1", role="nurse", unit_id="3A", encounter_ids=[])
        groups = resolver.resolve(claims)
        assert "unit-4B" not in groups


class TestGroupResolverPharmacist:
    def test_pharmacist_joins_role_group(self, resolver):
        claims = UserClaims(user_id="u2", role="pharmacist", unit_id=None, encounter_ids=["enc-xyz"])
        groups = resolver.resolve(claims)
        assert "role-pharmacist" in groups

    def test_pharmacist_without_unit_has_no_unit_group(self, resolver):
        claims = UserClaims(user_id="u2", role="pharmacist", unit_id=None, encounter_ids=[])
        groups = resolver.resolve(claims)
        unit_groups = [g for g in groups if g.startswith("unit-")]
        assert len(unit_groups) == 0

    def test_pharmacist_joins_encounter_group(self, resolver):
        """US-022 Scenario 2: pharmacist receives medication reconciliation event via role group."""
        claims = UserClaims(user_id="u2", role="pharmacist", unit_id=None, encounter_ids=["enc-xyz"])
        groups = resolver.resolve(claims)
        assert "encounter-enc-xyz" in groups


class TestGroupResolverNamingConvention:
    """US-022 DoD: group naming convention must be encounter-{id}, unit-{unitId}, role-{roleName}."""

    def test_group_names_use_correct_prefix_format(self, resolver):
        claims = UserClaims(user_id="u3", role="physician", unit_id="ICU", encounter_ids=["enc-001", "enc-002"])
        groups = resolver.resolve(claims)
        for g in groups:
            assert g.startswith(("role-", "unit-", "encounter-")), f"Unexpected group prefix: {g}"

    def test_multiple_encounters_all_resolved(self, resolver):
        enc_ids = ["enc-001", "enc-002", "enc-003"]
        claims = UserClaims(user_id="u4", role="nurse", unit_id="2B", encounter_ids=enc_ids)
        groups = resolver.resolve(claims)
        for enc_id in enc_ids:
            assert f"encounter-{enc_id}" in groups
```

---

## Validation Loop

Before marking this task complete, verify:

```bash
# Unit tests — group routing
pytest backend/tests/unit/signalr/test_group_resolver.py -v

# Confirm negotiate endpoint is registered
python -c "
from app.main import app
routes = [r.path for r in app.routes]
assert '/api/v1/signalr/negotiate' in routes, 'Negotiate route missing'
print('Routes OK')
"

# Confirm 401 on unauthenticated negotiate (requires running dev server)
curl -X POST http://localhost:8000/api/v1/signalr/negotiate \
  -H "Content-Type: application/json"
# Expected: 401 Unauthorized
```

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Upstream task | `SignalRBroadcaster`, `_parse_connection_string`, settings already created |
| `get_current_staff_user` | Existing auth dependency | JWT validation already implemented in EP-011 auth middleware |
| GCP Secret Manager | Infrastructure | Terraform resource added in this task |
| `StaffUser` auth model | Existing | Must expose `role`, `unit_id`, `active_encounter_ids` claims |
