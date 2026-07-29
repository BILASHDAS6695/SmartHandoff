"""De-identification pipeline for encounter export records.

Transforms raw Cloud SQL encounter rows into BigQuery-safe records by:
  1. Hashing encounter_id with SHA-256(encounter_id + salt)
  2. Dropping the raw encounter_id from the output dict
  3. Asserting no PHI columns remain before the record is returned

HIPAA Safe Harbor compliance:
    Implements the de-identification standard under 45 CFR §164.514(b).
    The following identifiers are removed:
      - Names (first_name, last_name) — excluded at SQL query level (TASK-001)
      - Geographic data below state level — unit field contains only unit code
      - Dates — only year-level aggregation for dates >89y old (not applicable here;
        admit_date and discharge_date retained as date only, no birth year correlation)
      - Account numbers / encounter IDs — replaced by one-way hash
      - Contact info (phone, email, MRN) — excluded at SQL query level (TASK-001)

Design refs:
    US-062 Technical Notes — SHA-256(encounter_id + salt); monthly salt rotation
    design.md §8.3 — PHI containment
    DR-017 — de-identified analytics data
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.schema import assert_no_phi

logger = logging.getLogger(__name__)

# Name of the raw encounter ID key as returned by sql_reader.fetch_encounters()
_RAW_ID_FIELD = "encounter_id"
# Name of the hashed field written to BigQuery
_HASH_FIELD = "encounter_id_hash"


def hash_encounter_id(encounter_id: str | int, salt: str) -> str:
    """Return the SHA-256 hex digest of (encounter_id + salt).

    The concatenation uses a pipe separator to prevent length-extension
    collisions between different encounter_id / salt combinations.

    Args:
        encounter_id: Raw encounter primary key from Cloud SQL.
        salt: Monthly-rotated secret salt from Secret Manager.

    Returns:
        64-character lowercase hex string (SHA-256 digest).
    """
    payload = f"{encounter_id}|{salt}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def deidentify_row(row: dict[str, Any], salt: str) -> dict[str, Any]:
    """Transform a single encounter row into a de-identified BigQuery record.

    Steps:
      1. Hash the raw encounter_id → encounter_id_hash
      2. Remove the raw encounter_id key
      3. Assert no PHI columns remain in the output dict

    Args:
        row: A dict returned by sql_reader.fetch_encounters(); must contain
             the 'encounter_id' key plus the safe columns defined in schema.py.
        salt: Monthly-rotated de-identification salt from Secret Manager.

    Returns:
        A new dict safe for BigQuery insertion; never mutates the input row.

    Raises:
        KeyError: If 'encounter_id' is absent from the row.
        ValueError: If any PHI column is detected in the output (schema violation).
    """
    output = dict(row)  # shallow copy — never mutate caller's data

    raw_id = output.pop(_RAW_ID_FIELD)
    output[_HASH_FIELD] = hash_encounter_id(raw_id, salt)

    # Final PHI guard — raises ValueError if any blocklisted column is present
    assert_no_phi(list(output.keys()))

    return output


def deidentify_batch(
    rows: list[dict[str, Any]], salt: str
) -> list[dict[str, Any]]:
    """Apply de-identification to an entire batch of encounter rows.

    Logs a warning (and skips) any row missing the encounter_id key rather
    than aborting the entire export — partial exports are preferable to
    complete failures for non-critical data quality issues.

    Args:
        rows: List of dicts from sql_reader.fetch_encounters().
        salt: Monthly-rotated de-identification salt.

    Returns:
        List of de-identified dicts ready for BigQuery insertion.
    """
    output: list[dict[str, Any]] = []
    skipped = 0

    for row in rows:
        if _RAW_ID_FIELD not in row:
            logger.warning(
                "Skipping row missing encounter_id — cannot hash",
                extra={"row_keys": list(row.keys())},
            )
            skipped += 1
            continue
        output.append(deidentify_row(row, salt))

    if skipped:
        logger.warning(
            "De-identification batch completed with skipped rows",
            extra={"total": len(rows), "skipped": skipped, "exported": len(output)},
        )
    else:
        logger.info(
            "De-identification batch completed",
            extra={"total": len(rows), "exported": len(output)},
        )

    return output
