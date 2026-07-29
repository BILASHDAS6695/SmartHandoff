"""Nightly BigQuery export job entrypoint.

Executed as a Cloud Run job triggered by Cloud Scheduler at 02:00 UTC daily.

Exit behaviour:
    - Exit code 0 on success
    - Exit code 1 on any exception (enables Cloud Monitoring alert via
      Cloud Run job failure detection — US-062 AC Scenario 4)

Structured logging:
    All log records use key=value extras to produce structured JSON logs
    in Cloud Logging. Export runtime is logged on completion.

Design refs:
    US-062 AC Scenario 1 — nightly export; runtime logged to Cloud Logging
    US-062 AC Scenario 4 — non-zero exit triggers Cloud Monitoring alert
    design.md §3.1 — Cloud Run jobs; stateless execution
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from app.bq_client import ensure_table_exists, get_bq_client
from app.bq_writer import write_partition
from app.config import Config
from app.date_utils import get_target_date
from app.deidentify import deidentify_batch
from app.sql_reader import fetch_encounters


class JsonFormatter(logging.Formatter):
    """Format logs as Cloud Logging-compatible JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """Emit log as single-line JSON with severity mapped to Cloud Logging."""
        severity_map = {
            logging.DEBUG: "DEBUG",
            logging.INFO: "INFO",
            logging.WARNING: "WARNING",
            logging.ERROR: "ERROR",
            logging.CRITICAL: "CRITICAL",
        }
        
        log_entry: dict[str, Any] = {
            "severity": severity_map.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
        }
        
        # Include exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


# Configure Cloud Logging-compatible structured JSON logging
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger("bq_export_job")

# Replace handler with JSON formatter
root_logger = logging.getLogger()
root_logger.handlers.clear()
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO)


def run() -> None:
    """Execute the full nightly export pipeline.

    Pipeline stages:
      1. Resolve target date (yesterday UTC or EXPORT_DATE_OVERRIDE)
      2. Ensure BigQuery table and partition exist
      3. Fetch encounter rows from Cloud SQL (PHI-excluded at SQL level)
      4. Apply de-identification (SHA-256 hash encounter_id; assert no PHI)
      5. Write to BigQuery with WRITE_TRUNCATE on admit_date partition
    """
    start_time = time.monotonic()
    target_date = get_target_date()

    logger.info(
        "BigQuery nightly export job started",
        extra={"target_date": str(target_date), "project": Config.GCP_PROJECT_ID},
    )

    # Stage 1: Ensure BigQuery table exists (idempotent)
    bq_client = get_bq_client()
    ensure_table_exists(bq_client)

    # Stage 2: Fetch encounter data from Cloud SQL (no PHI in result set)
    rows = fetch_encounters(target_date)
    logger.info(
        "Encounter rows fetched from Cloud SQL",
        extra={"target_date": str(target_date), "row_count": len(rows)},
    )

    # Stage 3: Apply de-identification pipeline
    salt = Config.deidentification_salt()
    deidentified_rows = deidentify_batch(rows, salt)

    # Stage 4: Write to BigQuery (WRITE_TRUNCATE on partition)
    rows_written = write_partition(bq_client, deidentified_rows, target_date)

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "BigQuery nightly export job completed",
        extra={
            "target_date": str(target_date),
            "rows_written": rows_written,
            "elapsed_ms": elapsed_ms,
        },
    )


if __name__ == "__main__":
    try:
        run()
        sys.exit(0)
    except Exception:  # noqa: BLE001
        logger.exception("BigQuery nightly export job FAILED — exiting with code 1")
        sys.exit(1)
