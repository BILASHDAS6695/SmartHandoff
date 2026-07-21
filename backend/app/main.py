"""FastAPI application entry point.

Performs eager PHI encryption key validation at startup via the lifespan
context manager (US-007). If the key is misconfigured, the service fails fast
at boot rather than silently writing unencrypted PHI.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.encryption_key import get_phi_encryption_key
from app.db.session import create_db_engines, dispose_db_engines
from app.middleware.audit import HIPAAAuditMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — validates encryption key and warms DB pools at startup."""
    # Fail fast: raises RuntimeError / ValueError on misconfiguration.
    # This prevents the service from accepting requests with a broken key.
    get_phi_encryption_key()
    # Warm write + read DB connection pools (PgBouncer → primary + direct replica).
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
app.add_middleware(HIPAAAuditMiddleware)
