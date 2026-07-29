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

    Args:
        client: Authenticated BigQuery client.

    Returns:
        The created or existing BigQuery Table reference.
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
