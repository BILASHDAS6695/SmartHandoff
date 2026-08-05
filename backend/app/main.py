"""FastAPI application entry point.

Performs eager PHI encryption key validation at startup via the lifespan
context manager (US-007). If the key is misconfigured, the service fails fast
at boot rather than silently writing unencrypted PHI.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

# US-058: register PHI logging filter before any other import emits a log
from app.core.logging_config import configure_logging
configure_logging()

from app.api.v1.routers.auth import router as auth_router
from app.api.v1.routers.auth_patient_otp import router as patient_otp_router
from app.api.v1.routers.auth_patient_verify import router as patient_verify_router
from app.api.v1.routers.portal import router as portal_router
from app.api.v1.routers.portal_preferences import router as portal_preferences_router
from app.api.v1.routers.patients import router as patients_router
# from app.api.v1.routers.test_sync import router as test_sync_router  # REMOVED - file does not exist
# from app.api.v1.routers.debug_schema import router as debug_schema_router  # REMOVED - file does not exist
from app.api.v1.routers.encounters import router as encounters_router
from app.api.v1.routers.encounter_tasks import router as encounter_tasks_router
from app.api.v1.routers.documents import router as documents_router
from app.api.v1.routers.medications import (
    router as medications_router,
    encounters_medications_router,
)
from app.api.v1.routers.alerts import router as alerts_router
from app.api.v1.routers.beds import router as beds_router
from app.api.v1.routers.care_escalations import router as care_escalations_router
from app.api.v1.routers.analytics import router as analytics_router
from app.api.v1.routers.tasks import router as tasks_router
from app.api.v1.routers.notifications import router as notifications_router
from app.api.v1.routers.admin.audit import router as admin_audit_router
from app.api.v1.routers.admin.users import router as admin_users_router
from app.api.v1.admin.scim.router import router as scim_router
from app.api.v1.routers.signalr_hub import router as signalr_router, set_signalr_broadcaster
from app.api.v1.routers.signalr_negotiate import router as negotiate_router
from app.core.auth.rbac_validator import validate_rbac_config
from app.core.config import get_settings
from app.signalr.broadcaster import SignalRBroadcaster
from app.db.encryption_key import get_phi_encryption_key
from app.db.session import create_db_engines, dispose_db_engines, get_write_session
# from app.db.ensure_schema import ensure_schema  # REMOVED - file does not exist
# from app.db.add_missing_encounter_columns import add_missing_encounter_columns  # REMOVED - file does not exist
from app.middleware.audit import HIPAAAuditMiddleware
from app.middleware.phi_log_sanitiser import PhiLogSanitiserMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — validates config and warms resources at startup."""
    import sys
    print("🚀 LIFESPAN STARTUP BEGINNING", file=sys.stderr, flush=True)
    
    logger = logging.getLogger(__name__)
    logger.warning("=" * 80)
    logger.warning("🚀 FastAPI lifespan startup beginning...")
    logger.warning("=" * 80)
    
    broadcaster = None
    try:
        # 1. Validate RBAC config — refuse startup if matrix is misconfigured (US-057)
        logger.warning("🔧 Startup Step 1/4: Validating RBAC config...")
        validate_rbac_config()
        logger.warning("✓ RBAC config validated successfully")
        
        # 2. Fail fast: raises RuntimeError / ValueError on misconfiguration.
        # This prevents the service from accepting requests with a broken key.
        logger.warning("🔧 Startup Step 2/4: Validating PHI encryption key...")
        get_phi_encryption_key()
        logger.warning("✓ PHI encryption key validated successfully")
        
        # 3. Warm write + read DB connection pools (PgBouncer → primary + direct replica).
        logger.warning("🔧 Startup Step 3/4: Initializing database engines...")
        print("🔧 ABOUT TO CALL create_db_engines()", file=sys.stderr, flush=True)
        create_db_engines()
        print("✓ create_db_engines() COMPLETED", file=sys.stderr, flush=True)
        logger.warning("✓ Database engines initialized successfully")
        
        # 3.1 Run Alembic migrations to add missing columns
        logger.warning("🔧 Startup Step 3.1/4: Skipping Alembic migrations (no function available)...")
        # try:
        #     run_db_migrations()
        #     logger.warning("✓ Alembic migrations completed successfully")
        # except Exception as exc:
        #     logger.warning(f"⚠️  Alembic migrations failed (continuing): {exc}")
        
        # 3.5 Ensure database schema has required columns
        logger.warning("🔧 Startup Step 3.5/4: Skipping schema verification (functions removed)...")
        # try:
        #     # Schema verification (add_missing_encounter_columns is now handled by Alembic)
        #     settings = get_settings()
        #     
        #     async with get_write_session() as db:
        #         await ensure_schema(db)
        #     logger.warning("✓ Schema verification completed")
        # except Exception as exc:
        #     logger.warning(f"⚠️  Schema verification failed (continuing): {exc}")
        
        # 4. Initialize SignalR broadcaster (US-022) - optional
        settings = get_settings()
        if settings.AZURE_SIGNALR_CONNECTION_STRING:
            logger.warning("🔧 Startup Step 4/4: Initializing SignalR broadcaster...")
            broadcaster = SignalRBroadcaster(settings.AZURE_SIGNALR_CONNECTION_STRING)
            set_signalr_broadcaster(broadcaster)
            logger.warning("✓ SignalR broadcaster initialized successfully")
        else:
            logger.warning("🔧 Startup Step 4/4: SignalR broadcaster not configured (skipped)")
        
        logger.warning("=" * 80)
        logger.warning("✅ FastAPI application startup COMPLETE - READY TO ACCEPT REQUESTS")
        logger.warning("=" * 80)
        
    except Exception as exc:
        logger.error("=" * 80)
        logger.error("❌ FATAL: Application startup failed!")
        logger.error("=" * 80)
        logger.exception("Startup exception: %s", exc)
        raise  # Re-raise to prevent app from starting with broken config
    
    yield
    
    logger.warning("🔽 FastAPI lifespan shutdown beginning...")
    try:
        # Shutdown: drain DB connections gracefully before Cloud Run SIGTERM timeout (30s).
        await dispose_db_engines()
        # Shutdown: close SignalR broadcaster HTTP client
        if broadcaster:
            await broadcaster.aclose()
        logger.warning("✓ FastAPI lifespan shutdown completed")
    except Exception as exc:
        logger.error("❌ Error during shutdown: %s", exc)


app = FastAPI(
    title="SmartHandoff API",
    lifespan=lifespan,
)

# DEBUG ENDPOINT — bypass all middleware and dependencies
@app.get("/debug/test")
def debug_test_endpoint():
    """Sync debug endpoint that returns immediately without any dependencies."""
    return {"debug": "OK", "message": "Sync endpoint"}

# DEBUG ENDPOINT — async version
@app.get("/debug/async")
async def debug_async_endpoint():
    """Async debug endpoint that returns immediately without any dependencies."""
    return {"debug": "OK", "message": "Async endpoint"}

# ── CORS Middleware ──────────────────────────────────────────────────────────
# Allows frontend (Angular app) to call the API from a different origin.
# MUST be added LAST so it's the FIRST middleware to process requests (reverse order).
# FastAPI applies middleware in reverse — last added = outermost = first to run.
settings = get_settings()
logger = logging.getLogger(__name__)
import sys
print(f"🔧 CORS Configuration: {settings.CORS_ORIGINS}", file=sys.stderr, flush=True)
logger.warning("🔧 Configuring CORS middleware with origins: %s", settings.CORS_ORIGINS)

# HIPAA audit logging middleware — must be registered after JWT validation
# middleware so request.state.user_id is populated when this middleware runs.
# Starlette wraps in reverse add_middleware order — last added = outermost.
# Position 1: AuditLogMiddleware (added first = innermost on response)
app.add_middleware(HIPAAAuditMiddleware)
# Position 2: PhiLogSanitiserMiddleware (runs before audit on response path)
app.add_middleware(PhiLogSanitiserMiddleware)

# Position 3: CORSMiddleware (added last = outermost = first to process preflight OPTIONS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# ── Public routers (no JWT required) ─────────────────────────────────────────
# Auth router — public endpoint (no JWT required to exchange OIDC id_token)
app.include_router(auth_router, prefix="/api/v1")
# Patient OTP router — public endpoint (portal token validation only)
app.include_router(patient_otp_router, prefix="/api/v1")
# Patient OTP verify router — public endpoint (portal token + OTP validation)
app.include_router(patient_verify_router, prefix="/api/v1")

# ── Protected routers (JWT + RBAC required) ───────────────────────────────────
app.include_router(portal_router, prefix="/api/v1")
app.include_router(portal_preferences_router, prefix="/api/v1")
app.include_router(patients_router, prefix="/api/v1")
# app.include_router(test_sync_router, prefix="/api/v1")  # REMOVED - file does not exist
# app.include_router(debug_schema_router)  # REMOVED - file does not exist
app.include_router(encounters_router, prefix="/api/v1")
app.include_router(encounter_tasks_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(medications_router, prefix="/api/v1")
app.include_router(encounters_medications_router, prefix="/api/v1")  # US-030: encounter medication reconciliation
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(beds_router, prefix="/api/v1")
app.include_router(care_escalations_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(admin_audit_router, prefix="/api/v1")
app.include_router(admin_users_router, prefix="/api/v1")
app.include_router(scim_router, prefix="/api/v1")
app.include_router(signalr_router, prefix="/api/v1")
app.include_router(negotiate_router, prefix="/api/v1")


# ── Health and Readiness Endpoints ──────────────────────────────────────────────
@app.get("/health")
async def health():
    """Liveness probe endpoint for Cloud Run (TR-016).
    
    Returns 200 OK when the application process is alive.
    Cloud Run restarts the container on 3 consecutive failures.
    
    Design refs:
        TR-016 — Health check probes
        US-002 — Cloud Run service manifests with health probes
    """
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """Readiness probe endpoint for Cloud Run (TR-016).
    
    Returns 200 OK when the application is fully initialized and ready to accept requests.
    Cloud Run blocks traffic during startup until this endpoint returns 200.
    
    This endpoint verifies that critical dependencies (DB engines, RBAC config, PHI encryption key)
    have been successfully initialized during the lifespan startup.
    
    Design refs:
        TR-016 — Readiness check probes
        US-002 — Cloud Run service manifests with startup/readiness probes
    """
    return {"status": "ready"}


# ── Prometheus Metrics Endpoint ──────────────────────────────────────────────
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint (scraped by Cloud Monitoring).
    
    Exposes FHIR resilience metrics:
    - fhir_circuit_state: Circuit breaker state
    - fhir_retry_total: Retry outcomes
    - fhir_rate_limited_total: Rate limit backoffs
    - fhir_fetch_duration_seconds: Fetch latency histogram
    
    Design refs:
        US-018 DoD — Prometheus metrics requirement
        TR-016 — Observability / metrics
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

