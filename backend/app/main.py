"""FastAPI application entry point.

Performs eager PHI encryption key validation at startup via the lifespan
context manager (US-007). If the key is misconfigured, the service fails fast
at boot rather than silently writing unencrypted PHI.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.encryption_key import get_phi_encryption_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — validates encryption key at startup."""
    # Fail fast: raises RuntimeError / ValueError on misconfiguration.
    # This prevents the service from accepting requests with a broken key.
    get_phi_encryption_key()
    yield
    # Teardown: no-op (key cache cleared only in tests via clear_cached_key())


app = FastAPI(
    title="SmartHandoff API",
    lifespan=lifespan,
)
