#!/usr/bin/env python3
"""Seed the bed inventory to a minimum count without altering existing beds."""
from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

MINIMUM_BED_COUNT = 100
UNITS = ("ED", "MED", "SURG", "ICU", "CCU", "CARD", "NEURO", "PED")


def get_database_url() -> str:
    """Return the configured primary database URL for local or deployed seeding."""
    database_url = os.getenv("PRIMARY_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set PRIMARY_DATABASE_URL or DATABASE_URL before running this script.")
    return database_url


def build_bed_number(index: int) -> str:
    """Build a unique, human-readable bed identifier."""
    unit = UNITS[(index - 1) % len(UNITS)]
    return f"{unit}-{(index - 1) // len(UNITS) + 1:03d}"


async def seed_beds() -> None:
    """Insert vacant bed records until the inventory contains at least 100 rows."""
    engine = create_async_engine(get_database_url(), pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            current_count = await connection.scalar(text("SELECT COUNT(*) FROM public.bed"))
            required_count = max(0, MINIMUM_BED_COUNT - (current_count or 0))

            for index in range(1, required_count + 1):
                bed_number = build_bed_number(index)
                await connection.execute(
                    text(
                        """
                        INSERT INTO public.bed (
                            id, bed_number, unit, ward, status,
                            current_encounter_id, predicted_discharge_at
                        )
                        VALUES (
                            :id, :bed_number, :unit, :ward, :status,
                            NULL, NULL
                        )
                        ON CONFLICT (unit, bed_number) DO NOTHING
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "bed_number": bed_number,
                        "unit": bed_number.split("-", maxsplit=1)[0],
                        "ward": f"Ward-{(index - 1) // 10 + 1:02d}",
                        "status": "VACANT",
                    },
                )

            final_count = await connection.scalar(text("SELECT COUNT(*) FROM public.bed"))

        print(f"Bed inventory count: {final_count}")
        if (final_count or 0) < MINIMUM_BED_COUNT:
            raise RuntimeError("Unable to seed the requested minimum of 100 beds.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_beds())
