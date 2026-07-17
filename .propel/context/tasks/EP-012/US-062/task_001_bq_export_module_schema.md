---
id: TASK-001
title: "BigQuery Export Module — Project Structure, Schema Definition & Client Initialisation"
user_story: US-062
epic: EP-012
sprint: 2
layer: Backend / Data
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-062, US-001, US-006, DR-017]
---

# TASK-001: BigQuery Export Module — Project Structure, Schema Definition & Client Initialisation

> **Story:** US-062 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Backend / Data | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-062 requires a Cloud Run nightly export job that queries Cloud SQL encounter data, applies de-identification, and writes to BigQuery dataset `smarthandoff.encounters_deidentified`. Before the de-identification logic and write operations are built (TASK-002, TASK-003), this task establishes:

- The Python Cloud Run job project structure under `jobs/bq-export/`
- The BigQuery table schema matching the DoD fields (no PHI columns)
- The `google-cloud-bigquery` client initialisation helper
- The Cloud SQL read connection helper (using environment variables injected by Cloud Run)
- The `requirements.txt` / `pyproject.toml` dependency manifest

**Design references:**
- design.md §3.1 — Cloud SQL (PostgreSQL 15) as system of record; Cloud Run for stateless jobs
- design.md §4.1 — SQLAlchemy 2.x; GCP Secret Manager for credentials
- design.md §6.1 ADR-003 — CMEK encrypted Cloud SQL; read replicas for non-transactional reads
- US-062 Technical Notes — BigQuery client: `google-cloud-bigquery`; partitioned by `admit_date`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Module structure in place; BigQuery client connects to `smarthandoff.encounters_deidentified` |
| Scenario 2 | BigQuery schema defined with zero PHI columns; only safe HIPAA Safe Harbor fields |

---

## Implementation Steps

### 1. Scaffold the module directory

```bash
mkdir -p jobs/bq-export/app
touch jobs/bq-export/app/__init__.py
touch jobs/bq-export/app/config.py
touch jobs/bq-export/app/bq_client.py
touch jobs/bq-export/app/sql_reader.py
touch jobs/bq-export/app/schema.py
touch jobs/bq-export/main.py
touch jobs/bq-export/requirements.txt
touch jobs/bq-export/Dockerfile
touch jobs/bq-export/.env.example
```

### 2. Define configuration in `jobs/bq-export/app/config.py`

```python
"""Runtime configuration for the BigQuery nightly export job.

All values are injected via environment variables set by Cloud Run / Cloud Scheduler.
No hardcoded credentials — secrets come from GCP Secret Manager mounts.

Design refs:
    design.md §4.1 — GCP Secret Manager for credentials
    US-062 Technical Notes — Cloud Run job; Cloud Scheduler trigger
"""
from __future__ import annotations

import os


class Config:
    """Centralised config resolved from environment variables at startup."""

    # GCP project hosting BigQuery dataset
    GCP_PROJECT_ID: str = os.environ["GCP_PROJECT_ID"]

    # BigQuery target dataset and table
    BQ_DATASET: str = os.getenv("BQ_DATASET", "smarthandoff")
    BQ_TABLE: str = os.getenv("BQ_TABLE", "encounters_deidentified")

    # Cloud SQL connection (Unix socket injected by Cloud Run SQL connector)
    DB_HOST: str = os.getenv("DB_HOST", "/cloudsql")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_NAME: str = os.environ["DB_NAME"]
    DB_USER: str = os.environ["DB_USER"]
    # DB_PASSWORD mounted from Secret Manager at /secrets/db-password
    DB_PASSWORD_FILE: str = os.getenv(
        "DB_PASSWORD_FILE", "/secrets/db-password"
    )

    # De-identification salt (rotated monthly; mounted from Secret Manager)
    DEIDENTIFICATION_SALT_FILE: str = os.getenv(
        "DEIDENTIFICATION_SALT_FILE", "/secrets/deidentification-salt"
    )

    # Export date window: defaults to yesterday (UTC)
    EXPORT_DATE_OVERRIDE: str | None = os.getenv("EXPORT_DATE_OVERRIDE")

    @classmethod
    def db_password(cls) -> str:
        """Read DB password from mounted Secret Manager file."""
        with open(cls.DB_PASSWORD_FILE) as f:
            return f.read().strip()

    @classmethod
    def deidentification_salt(cls) -> str:
        """Read de-identification salt from mounted Secret Manager file."""
        with open(cls.DEIDENTIFICATION_SALT_FILE) as f:
            return f.read().strip()
```

### 3. Define BigQuery schema in `jobs/bq-export/app/schema.py`

```python
"""BigQuery table schema for encounters_deidentified.

HIPAA Safe Harbor guardrail:
    This schema deliberately excludes ALL 18 PHI identifiers.
    Fields mrn, first_name, last_name, dob, phone, email are NEVER
    present in this table or in intermediate data frames.

    Only the following safe fields are included per US-062 DoD and
    HIPAA Safe Harbor method (45 CFR §164.514(b)):

Design refs:
    US-062 DoD — BigQuery schema fields
    design.md §8 — Security architecture; PHI containment
    DR-017 — De-identified analytics data requirement
"""
from google.cloud.bigquery import SchemaField, TimePartitioning, TimePartitioningType

# PHI columns that must NEVER appear in this schema
_PHI_COLUMNS_BLOCKLIST: frozenset[str] = frozenset(
    {"mrn", "first_name", "last_name", "dob", "phone", "email",
     "patient_id", "encounter_id"}
)

ENCOUNTERS_DEIDENTIFIED_SCHEMA: list[SchemaField] = [
    SchemaField("encounter_id_hash", "STRING", mode="REQUIRED",
                description="SHA-256(encounter_id + monthly_salt) — not reversible to source ID"),
    SchemaField("admit_date", "DATE", mode="REQUIRED",
                description="Admission date — partition key; day-level granularity only"),
    SchemaField("discharge_date", "DATE", mode="NULLABLE",
                description="Discharge date; NULL for encounters not yet discharged"),
    SchemaField("primary_diagnosis_code", "STRING", mode="NULLABLE",
                description="ICD-10 primary diagnosis code; not individually identifying"),
    SchemaField("risk_score", "FLOAT64", mode="NULLABLE",
                description="Readmission risk score (0.0–1.0) from ML inference service"),
    SchemaField("risk_tier", "STRING", mode="NULLABLE",
                description="Risk tier label: LOW | MEDIUM | HIGH"),
    SchemaField("unit", "STRING", mode="NULLABLE",
                description="Hospital unit code; no patient-identifying detail"),
    SchemaField("los_days", "FLOAT64", mode="NULLABLE",
                description="Length of stay in days; computed at export time"),
    SchemaField("discharge_disposition", "STRING", mode="NULLABLE",
                description="Disposition code (e.g., HOME, SNF, REHAB)"),
    SchemaField("readmitted_30d", "BOOL", mode="NULLABLE",
                description="True if patient readmitted within 30 days of discharge"),
]

ENCOUNTERS_DEIDENTIFIED_TIME_PARTITIONING = TimePartitioning(
    type_=TimePartitioningType.DAY,
    field="admit_date",
)


def assert_no_phi(column_names: list[str]) -> None:
    """Raise ValueError if any PHI column name appears in the provided list.

    Called before every BigQuery write to enforce schema compliance.
    """
    violations = _PHI_COLUMNS_BLOCKLIST.intersection(set(column_names))
    if violations:
        raise ValueError(
            f"PHI columns detected in export payload — BLOCKED: {violations}"
        )
```

### 4. Implement BigQuery client helper in `jobs/bq-export/app/bq_client.py`

```python
"""BigQuery client factory and table ensure-exists helper.

Design refs:
    US-062 Technical Notes — google-cloud-bigquery Python SDK
    US-062 DoD — partition by admit_date; WRITE_TRUNCATE for idempotency
"""
from __future__ import annotations

import logging

from google.cloud import bigquery

from app.config import Config
from app.schema import (
    ENCOUNTERS_DEIDENTIFIED_SCHEMA,
    ENCOUNTERS_DEIDENTIFIED_TIME_PARTITIONING,
)

logger = logging.getLogger(__name__)


def get_bq_client() -> bigquery.Client:
    """Return an authenticated BigQuery client for the configured project."""
    return bigquery.Client(project=Config.GCP_PROJECT_ID)


def ensure_table_exists(client: bigquery.Client) -> bigquery.Table:
    """Create the encounters_deidentified table if it does not already exist.

    Safe to call on every job run — uses CREATE IF NOT EXISTS semantics via
    the BigQuery API (exists_ok=True).
    """
    dataset_ref = bigquery.DatasetReference(Config.GCP_PROJECT_ID, Config.BQ_DATASET)
    table_ref = dataset_ref.table(Config.BQ_TABLE)

    table = bigquery.Table(table_ref, schema=ENCOUNTERS_DEIDENTIFIED_SCHEMA)
    table.time_partitioning = ENCOUNTERS_DEIDENTIFIED_TIME_PARTITIONING
    table.description = (
        "De-identified encounter records exported nightly from Cloud SQL. "
        "PHI fields excluded per HIPAA Safe Harbor (45 CFR §164.514(b)). "
        "Managed by US-062 nightly export job."
    )

    created = client.create_table(table, exists_ok=True)
    logger.info(
        "BigQuery table ready",
        extra={"table": str(created.reference), "num_rows": created.num_rows},
    )
    return created
```

### 5. Implement Cloud SQL reader stub in `jobs/bq-export/app/sql_reader.py`

```python
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
    """Build a SQLAlchemy engine connected to the Cloud SQL read replica."""
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
```

### 6. Pin dependencies in `jobs/bq-export/requirements.txt`

```text
google-cloud-bigquery==3.25.0
sqlalchemy==2.0.31
psycopg2-binary==2.9.9
```

### 7. Add `jobs/bq-export/.env.example`

```dotenv
GCP_PROJECT_ID=smarthandoff-dev
BQ_DATASET=smarthandoff
BQ_TABLE=encounters_deidentified
DB_NAME=smarthandoff
DB_USER=smarthandoff_app
DB_PASSWORD_FILE=/secrets/db-password
DEIDENTIFICATION_SALT_FILE=/secrets/deidentification-salt
# Optional override for manual backfill runs (YYYY-MM-DD)
EXPORT_DATE_OVERRIDE=
```

---

## Definition of Done

- [ ] `jobs/bq-export/` directory structure created with all files listed in Step 1
- [ ] `Config` class reads all values from environment variables; `db_password()` and `deidentification_salt()` read from Secret Manager file mounts (no inline secrets)
- [ ] `ENCOUNTERS_DEIDENTIFIED_SCHEMA` contains exactly the 10 fields from US-062 DoD — no PHI columns
- [ ] `_PHI_COLUMNS_BLOCKLIST` and `assert_no_phi()` guard function implemented in `schema.py`
- [ ] `ensure_table_exists()` uses `exists_ok=True` (idempotent)
- [ ] `fetch_encounters()` SQL query explicitly selects only safe columns — PHI columns absent at SQL level
- [ ] `requirements.txt` pins `google-cloud-bigquery`, `sqlalchemy`, `psycopg2-binary`
- [ ] `.env.example` documents all required environment variables

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-001 | Story | BigQuery API enabled via Terraform; Secret Manager secrets provisioned |
| US-006 | Story | `encounters` table exists in Cloud SQL with the columns referenced in `_SAFE_COLUMNS` |

---

## Files Modified

| File | Action |
|---|---|
| `jobs/bq-export/app/__init__.py` | Create — empty package marker |
| `jobs/bq-export/app/config.py` | Create — environment-driven config |
| `jobs/bq-export/app/schema.py` | Create — BigQuery schema + PHI blocklist guard |
| `jobs/bq-export/app/bq_client.py` | Create — BQ client factory + table ensure-exists |
| `jobs/bq-export/app/sql_reader.py` | Create — Cloud SQL encounter reader (PHI-safe SQL) |
| `jobs/bq-export/requirements.txt` | Create — pinned dependencies |
| `jobs/bq-export/.env.example` | Create — environment variable documentation |
