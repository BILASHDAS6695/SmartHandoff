"""FastAPI application entry point.

Performs eager PHI encryption key validation at startup via the lifespan
context manager (US-007). If the key is misconfigured, the service fails fast
at boot rather than silently writing unencrypted PHI.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

# US-058: register PHI logging filter before any other import emits a log
from app.core.logging_config import configure_logging
configure_logging()

from app.api.v1.routers.auth import router as auth_router
from app.api.v1.routers.patients import router as patients_router
from app.api.v1.routers.encounters import router as encounters_router
from app.api.v1.routers.documents import router as documents_router
from app.api.v1.routers.medications import router as medications_router
from app.api.v1.routers.alerts import router as alerts_router
from app.api.v1.routers.beds import router as beds_router
from app.api.v1.routers.analytics import router as analytics_router
from app.api.v1.routers.tasks import router as tasks_router
from app.api.v1.routers.admin.audit import router as admin_audit_router
from app.api.v1.routers.admin.users import router as admin_users_router
from app.api.v1.admin.scim.router import router as scim_router
from app.core.auth.rbac_validator import validate_rbac_config
from app.db.encryption_key import get_phi_encryption_key
from app.db.session import create_db_engines, dispose_db_engines
from app.middleware.audit import HIPAAAuditMiddleware
from app.middleware.phi_log_sanitiser import PhiLogSanitiserMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — validates config and warms resources at startup."""
    # 1. Validate RBAC config — refuse startup if matrix is misconfigured (US-057)
    validate_rbac_config()
    # 2. Fail fast: raises RuntimeError / ValueError on misconfiguration.
    # This prevents the service from accepting requests with a broken key.
    get_phi_encryption_key()
    # 3. Warm write + read DB connection pools (PgBouncer → primary + direct replica).
    create_db_engines()
    yield
    # Shutdown: drain DB connections gracefully before Cloud Run SIGTERM timeout (30s).
    await dispose_db_engines()


app = FastAPI(
    title="SmartHandoff API",
    lifespan=lifespan,
)

# HIPAA audit logging middleware — must be registered after JWT validation
# middleware so request.state.user_id is populated when this middleware runs.
# Starlette wraps in reverse add_middleware order — last added = outermost.
# Position 7: AuditLogMiddleware (added first = innermost on response)
app.add_middleware(HIPAAAuditMiddleware)
# Position 6: PhiLogSanitiserMiddleware (runs before audit on response path)
app.add_middleware(PhiLogSanitiserMiddleware)

# ── Public routers (no JWT required) ─────────────────────────────────────────
# Auth router — public endpoint (no JWT required to exchange OIDC id_token)
app.include_router(auth_router, prefix="/api/v1")

# ── Protected routers (JWT + RBAC required) ───────────────────────────────────
app.include_router(patients_router, prefix="/api/v1")
app.include_router(encounters_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(medications_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(beds_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(admin_audit_router, prefix="/api/v1")
app.include_router(admin_users_router, prefix="/api/v1")
app.include_router(scim_router, prefix="/api/v1")

