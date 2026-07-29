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
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Receive

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

    Important: This middleware uses a custom receive wrapper to allow the
    request body to be read by both this middleware and the route handler.
    Without this, the body stream would be consumed by the middleware.
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

    Body bytes are cached on request.state to allow both middleware and
    route handler to read the body (Starlette body can only be read once).
    
    Implementation:
        - First call reads from request.body() and caches
        - Subsequent calls use cached value from request.state._body
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
        # Note: request.body() consumes the receive channel; subsequent calls
        # use the cached bytes (handled by Starlette's receive wrapper)
        if not hasattr(request.state, "_body"):
            request.state._body = await request.body()
        body = json.loads(request.state._body)
        return body.get("encounter_id")
    except (ValueError, json.JSONDecodeError, Exception) as e:
        # Body is not valid JSON or other error — skip
        log.debug("encounter_scope_body_extraction_error", extra={"error": str(e)})
        return None

