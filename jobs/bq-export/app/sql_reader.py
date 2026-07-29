"""Cloud SQL encounter data reader.

Connects to the Cloud SQL PostgreSQL read replica via the Cloud SQL connector
(Unix socket) and fetches encounters admitted on the specified target date.

PHI guardrail:
    The SELECT query must NEVER include: mrn, first_name, last_name,
    dob, phone, email. These columns are excluded at query level, not
    post-processing, to prevent PHI from entering memory.

Design refs:
    design.md §4.1 — SQLAlchemy 2.x; Cloud SQL connector
    US-062 — queries encounter data from Cloud SQL
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

import sqlalchemy
from sqlalchemy import text

from app.config import Config

logger = logging.getLogger(__name__)

# Columns explicitly selected — PHI columns are omitted at SQL level
_SAFE_COLUMNS = """
    encounter_id,
    admit_date,
    discharge_date,
    primary_diagnosis_code,
    risk_score,
    risk_tier,
    unit,
    los_days,
    discharge_disposition,
    readmitted_30d
"""

_FETCH_ENCOUNTERS_SQL = text(f"""
    SELECT {_SAFE_COLUMNS}
    FROM encounters
    WHERE admit_date = :target_date
      AND discharge_date IS NOT NULL
""")


def get_engine() -> sqlalchemy.Engine:
    """Build a SQLAlchemy engine connected to the Cloud SQL read replica.

    Returns:
        A configured SQLAlchemy engine for the PostgreSQL database.
    """
    password = Config.db_password()
    url = sqlalchemy.engine.URL.create(
        drivername="postgresql+psycopg2",
        username=Config.DB_USER,
        password=password,
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        database=Config.DB_NAME,
    )
    return sqlalchemy.create_engine(url, pool_pre_ping=True, pool_size=2)


def fetch_encounters(target_date: datetime.date) -> list[dict[str, Any]]:
    """Fetch de-identification-ready encounter rows for the given date.

    Returns a list of dicts containing only safe (non-PHI) fields.
    encounter_id is included here solely for SHA-256 hashing downstream;
    it is replaced by encounter_id_hash before any BigQuery write.

    Args:
        target_date: The date for which to fetch encounters (admitted on this date).

    Returns:
        List of encounter dicts with safe columns only.
    """
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(_FETCH_ENCOUNTERS_SQL, {"target_date": target_date})
        rows = [dict(row._mapping) for row in result]

    logger.info(
        "Fetched encounter rows from Cloud SQL",
        extra={"target_date": str(target_date), "row_count": len(rows)},
    )
    return rows
