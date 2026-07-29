"""Date utility helpers for the nightly export job.

Centralises the logic for determining the target export date so that:
  - Scheduled runs default to yesterday (UTC)
  - Manual backfill runs can override via EXPORT_DATE_OVERRIDE env var
  - All date arithmetic is UTC-based to avoid DST edge cases

Design refs:
    US-062 AC Scenario 1 — export covers encounters completed in the previous day
    US-062 AC Scenario 3 — idempotent; re-runs for same date must not duplicate
"""
from __future__ import annotations

import datetime
import logging

from app.config import Config

logger = logging.getLogger(__name__)


def get_target_date() -> datetime.date:
    """Return the target export date.

    Priority:
      1. EXPORT_DATE_OVERRIDE env var (format: YYYY-MM-DD) — for manual backfills
      2. Yesterday in UTC — default for scheduled nightly runs

    Returns:
        A datetime.date representing the day whose encounters will be exported.

    Raises:
        ValueError: If EXPORT_DATE_OVERRIDE is set to an invalid format.
    """
    override = Config.EXPORT_DATE_OVERRIDE
    if override:
        try:
            target = datetime.date.fromisoformat(override)
            logger.info(
                "Using EXPORT_DATE_OVERRIDE",
                extra={"target_date": str(target)},
            )
            return target
        except ValueError as exc:
            raise ValueError(
                f"EXPORT_DATE_OVERRIDE must be YYYY-MM-DD, got: {override!r}"
            ) from exc

    yesterday = datetime.datetime.now(tz=datetime.timezone.utc).date() - datetime.timedelta(days=1)
    logger.info(
        "Using default target date (yesterday UTC)",
        extra={"target_date": str(yesterday)},
    )
    return yesterday
