"""Async SQLAlchemy session factory for the HL7 Listener service.

Re-exported from app.db for direct import convenience:

    from app.db.session import get_async_session
"""
from app.db import get_async_session

__all__ = ["get_async_session"]
