"""SQLAlchemy 2.x declarative base for all ORM models.

All models must inherit from `Base`. This registers their metadata
with Alembic's `env.py` via the `target_metadata = Base.metadata` reference.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Project-wide SQLAlchemy declarative base.

    Usage:
        class MyModel(Base):
            __tablename__ = "my_model"
            ...
    """
    pass
