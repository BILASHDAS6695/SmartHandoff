---
id: TASK-004
title: "PatientEncounterScopeMiddleware — Enforce encounter_id JWT Claim on Patient API Calls"
user_story: US-052
epic: EP-010
sprint: 2
layer: Backend / Middleware
estimate: 1.5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-052/TASK-003]
---

# TASK-004: PatientEncounterScopeMiddleware — Enforce encounter_id JWT Claim on Patient API Calls

> **Story:** US-052 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Backend / Middleware | **Est:** 1.5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

Once the patient has a JWT (issued by TASK-003), every subsequent API call to the patient
portal must be constrained to the patient's own encounter. This task implements the
encounter scope enforcement described in US-052 AC Scenario 4.

### Enforcement rule

For any request where:
- The JWT `role` claim equals `"patient"`, **AND**
- The request path or body contains an `encounter_id` parameter

The middleware validates that the `encounter_id` in the JWT matches the `encounter_id`
in the request. Any mismatch results in **HTTP 403 Forbidden**.

### Scope of enforcement

The middleware inspects the following locations for `encounter_id`:

| Source | Extraction method |
|---|---|
| Path parameter | `request.path_params.get("encounter_id")` |
| Query parameter | `request.query_params.get("encounter_id")` |
| JSON request body | `body.get("encounter_id")` (cached body bytes) |

If none of the above contain `encounter_id`, the request is passed through unchanged
(endpoints that don't operate on encounter resources are not restricted).

**Design references:**

- US-052 AC Scenario 4 — "middleware validates JWT `encounter_id` claim matches the requested resource"
- design.md §3.3 — RBAC Enforcer runs after JWT Validator in middleware stack
- design.md §8.2 — patient JWT carries `encounter_id` as a first-class claim
- design.md §8.3 — RBAC: patient role — own encounter only

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 4 | JWT `encounter_id=ENC-001` + request `encounter_id=ENC-002` → HTTP 403 |
| Scenario 4 | JWT `encounter_id=ENC-001` + request `encounter_id=ENC-001` → request passes through |

---

## Implementation Steps

### 1. Create middleware file

```bash
touch api-gateway/app/middleware/patient_encounter_scope.py
```

### 2. Implement `api-gateway/app/middleware/patient_encounter_scope.py`

```python
"""PatientEncounterScopeMiddleware — enforces encounter_id JWT claim (US-052).

Intercepts all requests from authenticated patients (role='patient') and
validates that the encounter_id in the JWT matches the encounter_id in
the request (path, query, or JSON body).

Position in middleware stack (design.md §3.3):
    ... JWT Validator → RBAC Enforcer → [THIS MIDDLEWARE] → PHI Log Sanitiser ...

Enforcement:
    - Only applied when JWT role == 'patient'
    - Compares JWT claim 'encounter_id' against request encounter_id
    - Mismatch → HTTP 403 Forbidden (no information about the target encounter disclosed)
    - No encounter_id in request → middleware passes through (not all endpoints are scoped)

Design refs:
    US-052 AC Scenario 4
    design.md §3.3 — middleware stack position
    design.md §8.2 — patient JWT encounter_id claim
    design.md §8.3 — patient RBAC: own encounter only
"""
from __future__ import annotations

import json
import logging

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

log = logging.getLogger(__name__)

_PATIENT_ROLE = "patient"
_FORBIDDEN_RESPONSE = JSONResponse(
    status_code=status.HTTP_403_FORBIDDEN,
    content={"detail": "Access denied."},
)


class PatientEncounterScopeMiddleware(BaseHTTPMiddleware):
    """Enforce that patients can only access their own encounter resources.

    Extracts encounter_id from the JWT claims (set by JwtValidatorMiddleware
    on request.state.jwt_claims) and compares it against the encounter_id
    in the current request.

    Does NOT restrict non-patient roles — staff JWTs pass through unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Check patient encounter scope before forwarding the request."""
        jwt_claims: dict = getattr(request.state, "jwt_claims", {})

        # Only enforce for authenticated patients
        if jwt_claims.get("role") != _PATIENT_ROLE:
            return await call_next(request)

        jwt_encounter_id: str | None = jwt_claims.get("encounter_id")
        if not jwt_encounter_id:
            # Patient JWT missing encounter_id claim — reject (malformed token)
            log.warning("patient_jwt_missing_encounter_id_claim")
            return _FORBIDDEN_RESPONSE

        # Extract encounter_id from request (path → query → body)
        request_encounter_id = await _extract_encounter_id(request)

        if request_encounter_id is None:
            # No encounter_id in this request — not an encounter-scoped endpoint
            return await call_next(request)

        if request_encounter_id != jwt_encounter_id:
            log.warning(
                "patient_encounter_scope_violation",
                extra={"jwt_encounter_id": jwt_encounter_id},
                # request encounter_id intentionally excluded (potential PHI enumeration)
            )
            return _FORBIDDEN_RESPONSE

        return await call_next(request)


async def _extract_encounter_id(request: Request) -> str | None:
    """Return encounter_id from path, query, or JSON body; None if absent.

    Extraction order:
        1. Path parameter  — /encounters/{encounter_id}/...
        2. Query parameter — ?encounter_id=...
        3. JSON body field — {"encounter_id": "..."}

    Body bytes are cached on request.state to avoid consuming the stream
    twice (Starlette body can only be read once without caching).
    """
    # 1. Path parameter
    path_enc_id: str | None = request.path_params.get("encounter_id")
    if path_enc_id:
        return path_enc_id

    # 2. Query parameter
    query_enc_id: str | None = request.query_params.get("encounter_id")
    if query_enc_id:
        return query_enc_id

    # 3. JSON body — only attempt for content-type: application/json
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return None

    try:
        # Cache body bytes so the downstream handler can also read them
        if not hasattr(request.state, "_body"):
            request.state._body = await request.body()
        body = json.loads(request.state._body)
        return body.get("encounter_id")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
```

### 3. Register middleware in FastAPI app

```python
# In api-gateway/app/main.py — register AFTER JwtValidatorMiddleware

from api_gateway.app.middleware.patient_encounter_scope import PatientEncounterScopeMiddleware

# Middleware stack — order matters; added after JWT validator
app.add_middleware(PatientEncounterScopeMiddleware)
```

### 4. Ensure `request.state.jwt_claims` is populated by JWT Validator

```python
# In existing api-gateway/app/middleware/jwt_validator.py
# After decoding the JWT, set claims on request.state:

request.state.jwt_claims = decoded_claims  # dict with sub, encounter_id, role, exp
```

---

## Validation Checklist

- [ ] `python -m py_compile api-gateway/app/middleware/patient_encounter_scope.py` — zero errors
- [ ] Patient JWT `encounter_id=ENC-001` + request path `/encounters/ENC-001/...` → passes through (200)
- [ ] Patient JWT `encounter_id=ENC-001` + request path `/encounters/ENC-002/...` → HTTP 403
- [ ] Patient JWT `encounter_id=ENC-001` + JSON body `{"encounter_id": "ENC-002"}` → HTTP 403
- [ ] Staff JWT (role=`nurse`) + any `encounter_id` → passes through (middleware does not apply)
- [ ] Patient JWT without `encounter_id` claim → HTTP 403
- [ ] Request with no `encounter_id` anywhere → passes through (not encounter-scoped endpoint)
- [ ] Body bytes cached on `request.state._body` — downstream handler can still read body

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-052/TASK-003 | Task | Patient JWT issued with `encounter_id` claim |
| Existing `JwtValidatorMiddleware` | Middleware | Must populate `request.state.jwt_claims` before this middleware runs |
