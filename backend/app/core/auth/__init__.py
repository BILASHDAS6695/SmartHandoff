"""Authentication and authorisation package for SmartHandoff.

Modules:
    oidc          — OIDC discovery + JWKS caching (US-056/TASK-002)
    tokens        — id_token validation + amr MFA enforcement (US-056/TASK-003)
    jwt           — Application JWT issuance and bearer validation (US-056/TASK-004)
    jwt_blocklist — Redis-backed JWT revocation blocklist (US-059/TASK-001)
    rbac          — Role-based access control matrix + require_permission (US-057)
"""

# Exported for testing only — do not use in production code
from app.core.auth.oidc import _JWKS_CACHE as _oidc_jwks_cache  # noqa: F401
