"""Dedicated async session factory for the audit_writer PostgreSQL role.

The audit_writer role has INSERT-only privileges on audit_log (US-008/TASK-001).
This session is intentionally isolated from the main app_write session pool to
ensure the audit trail write path cannot be silenced by app_write privilege
revocation or connection pool exhaustion.

Security: The audit_writer DB URL is stored in Secret Manager under
'smarthandoff-audit-writer-db-url-<environment>'. The local dev fallback is
AUDIT_WRITER_DATABASE_URL — never set this in Cloud Run.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

_audit_engine = None
_audit_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_audit_db_url() -> str:
    """Resolve the audit_writer connection URL from Secret Manager or env var."""
    url = os.getenv("AUDIT_WRITER_DATABASE_URL")
    if url:
        logger.warning(
            "AUDIT_WRITER_DATABASE_URL is set via env var — "
            "acceptable for local dev only. Use Secret Manager in production."
        )
        return url

    # Production: resolve from Secret Manager
    secret_id = os.getenv(
        "AUDIT_WRITER_DB_URL_SECRET_ID",
        "smarthandoff-audit-writer-db-url",
    )
    try:
        from google.cloud import secretmanager  # type: ignore[import-untyped]

        client = secretmanager.SecretManagerServiceClient()
        project_id = os.environ["GCP_PROJECT_ID"]
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8").strip()
    except Exception:
        logger.exception(
            "Failed to resolve audit_writer DB URL from Secret Manager. "
            "Audit logging will be unavailable."
        )
        raise


def get_audit_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the module-level audit session factory, initialising it on first call."""
    global _audit_engine, _audit_session_factory
    if _audit_session_factory is None:
        url = _build_audit_db_url()
        _audit_engine = create_async_engine(
            url,
            pool_size=5,
            max_overflow=5,
            pool_timeout=10,
            pool_recycle=3600,
            echo=False,
        )
        _audit_session_factory = async_sessionmaker(
            _audit_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _audit_session_factory
