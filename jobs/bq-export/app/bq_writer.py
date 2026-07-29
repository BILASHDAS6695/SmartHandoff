"""Idempotent BigQuery partition writer for de-identified encounter data.

Write strategy:
    - WriteDisposition.WRITE_TRUNCATE on the specific admit_date partition
    - Ensures re-runs for the same date REPLACE rows, never APPEND
    - Partition decorator set to the target date to scope truncation to that
      partition only (prevents overwriting other date partitions)

Design refs:
    US-062 AC Scenario 3 — WRITE_TRUNCATE; idempotent export
    US-062 Technical Notes — TimePartitioning by admit_date
    US-062 DoD — WRITE_TRUNCATE for the date partition on each run
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig, WriteDisposition

from app.config import Config
from app.schema import (
    ENCOUNTERS_DEIDENTIFIED_SCHEMA,
    ENCOUNTERS_DEIDENTIFIED_TIME_PARTITIONING,
    assert_no_phi,
)

logger = logging.getLogger(__name__)


def write_partition(
    client: bigquery.Client,
    rows: list[dict[str, Any]],
    target_date: datetime.date,
) -> int:
    """Write de-identified rows to the BigQuery encounters_deidentified table.

    Uses WRITE_TRUNCATE scoped to the admit_date partition so that:
      - Re-running the job for the same date replaces rather than appends
      - Other date partitions are unaffected

    Args:
        client: Authenticated BigQuery client.
        rows: De-identified row dicts (output of deidentify.deidentify_batch()).
        target_date: The admit_date partition being written; used as the
                     partition decorator in the destination table reference.

    Returns:
        Number of rows written to BigQuery.

    Raises:
        ValueError: If any PHI column is detected in any row (pre-write guard).
        google.cloud.exceptions.GoogleCloudError: On BigQuery API errors.
    """
    if not rows:
        logger.info(
            "No rows to write — skipping BigQuery load",
            extra={"target_date": str(target_date)},
        )
        return 0

    # Pre-write PHI guard — second line of defence after deidentify_row()
    assert_no_phi(list(rows[0].keys()))

    # Partition decorator: table$YYYYMMDD scopes WRITE_TRUNCATE to one partition
    partition_str = target_date.strftime("%Y%m%d")
    destination = (
        f"{Config.GCP_PROJECT_ID}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"
        f"${partition_str}"
    )

    job_config = LoadJobConfig(
        schema=ENCOUNTERS_DEIDENTIFIED_SCHEMA,
        time_partitioning=ENCOUNTERS_DEIDENTIFIED_TIME_PARTITIONING,
        write_disposition=WriteDisposition.WRITE_TRUNCATE,
        # Fail the job on unknown fields to catch schema drift early
        ignore_unknown_values=False,
    )

    load_job = client.load_table_from_json(
        rows, destination, job_config=job_config
    )
    load_job.result()  # Block until the load job completes

    destination_table = client.get_table(
        f"{Config.GCP_PROJECT_ID}.{Config.BQ_DATASET}.{Config.BQ_TABLE}"
    )
    logger.info(
        "BigQuery partition write complete",
        extra={
            "target_date": str(target_date),
            "rows_written": len(rows),
            "table_total_rows": destination_table.num_rows,
            "partition": partition_str,
        },
    )
    return len(rows)
