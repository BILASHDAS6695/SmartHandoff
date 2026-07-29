"""
services/api-gateway/main.py

API Gateway Cloud Run service entry point.

Observability is bootstrapped via the shared OTel and structured logging
libraries (EP-TECH / US-004 / TASK-006, TASK-007) before the FastAPI
application is instantiated.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from shared.otel import init_tracer
from shared.logging import configure_logging
from shared.otel.middleware import TraceMiddleware

# ── Observability bootstrap (must run before app creation) ───────────────────
# Cloud Run injects K_SERVICE with the deployed service name.
SERVICE_NAME = os.environ.get("K_SERVICE", "api-gateway")
init_tracer(service_name=SERVICE_NAME)
configure_logging(service_name=SERVICE_NAME)
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="SmartHandoff API Gateway")

# Register OTel middleware before any other middleware so the trace context
# is established before route handlers execute.
app.add_middleware(TraceMiddleware)

# Auto-instrument all FastAPI route handlers (creates per-endpoint child spans).
FastAPIInstrumentor.instrument_app(app)

# Register middleware (patient encounter scope enforcement — US-052 TASK-004)
from app.middleware.patient_encounter_scope import PatientEncounterScopeMiddleware
app.add_middleware(PatientEncounterScopeMiddleware)

# Register routers
from app.routers.beds import router as beds_router
from app.routers.chat import router as chat_router
from app.routers.escalation import router as escalation_router
from app.routers.encounters_risk import router as encounters_risk_router
from app.routers.transcript import router as transcript_router
from app.routers.auth.patient_otp import router as patient_otp_router
from app.routers.auth.patient_verify import router as patient_verify_router
from app.routers.analytics_export import router as analytics_export_router

app.include_router(beds_router, prefix="/api/v1")
app.include_router(chat_router)
app.include_router(escalation_router)
app.include_router(encounters_risk_router, prefix="/api/v1")
app.include_router(transcript_router)
app.include_router(patient_otp_router)
app.include_router(patient_verify_router)
app.include_router(analytics_export_router, prefix="/api/v1")


# ── Startup validation ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_validation() -> None:
    """Validate required environment variables on application startup.

    Prevents deployment with missing configuration that would cause runtime
    failures. Required by the chatbot service (US-043):
      - REDIS_URL: Redis/Memorystore connection string for conversation history
      - GCP_PROJECT_ID: GCP project ID for Vertex AI / Gemini API access
      - VERTEX_AI_LOCATION: GCP region for Vertex AI (e.g., 'us-central1')
      - JWT_SIGNING_KEY: Secret key for JWT validation (mounted from Secret Manager)

    Raises:
        RuntimeError: If any required environment variable is missing.
    """
    import logging
    logger = logging.getLogger(__name__)

    required_vars = {
        "REDIS_URL": "Redis/Memorystore connection string",
        "GCP_PROJECT_ID": "GCP project ID",
        "VERTEX_AI_LOCATION": "Vertex AI region",
        "JWT_SIGNING_KEY": "JWT signing key (Secret Manager)",
        "PORTAL_TOKEN_SECRET": "HS256 signing secret for portal tokens (Secret Manager) — US-052",
        "PATIENT_JWT_SECRET": "HS256 signing secret for patient JWTs (Secret Manager) — US-052",
        "NOTIFICATION_SERVICE_URL": "Internal URL for Notification Service (US-064)",
    }

    missing = []
    for var_name, description in required_vars.items():
        if not os.environ.get(var_name):
            missing.append(f"{var_name}: {description}")

    if missing:
        error_msg = (
            "Missing required environment variables:\n  "
            + "\n  ".join(missing)
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info(
        "Startup validation passed: all required environment variables present"
    )


@app.on_event("shutdown")
async def shutdown_handler() -> None:
    """Clean up connections on application shutdown."""
    from app.core.redis import close_redis
    await close_redis()


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Cloud Run health probe endpoint — must return HTTP 200."""
    return {"status": "ok", "service": SERVICE_NAME}
