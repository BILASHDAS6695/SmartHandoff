#!/usr/bin/env python3
"""Seed the patient table to a minimum count without altering existing patients."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Support direct execution with ``python scripts/seed_minimum_patients.py``.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.patient import Patient

MINIMUM_PATIENT_COUNT = 500
BATCH_SIZE = 100
FIRST_NAMES = (
    "Avery", "Blake", "Cameron", "Drew", "Emerson", "Finley", "Gray",
    "Harper", "Jordan", "Kai", "Logan", "Morgan", "Parker", "Quinn",
    "Reese", "Rowan", "Sawyer", "Taylor", "Alex", "Casey",
)
LAST_NAMES = (
    "Adams", "Bennett", "Campbell", "Davis", "Ellis", "Foster", "Garcia",
    "Hayes", "Irwin", "Johnson", "Kim", "Lewis", "Martinez", "Nguyen",
    "Owens", "Patel", "Reed", "Singh", "Turner", "Williams",
)


def get_database_url() -> str:
    """Return a SQLAlchemy async database URL from the configured environment."""
    database_url = os.getenv("PRIMARY_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set PRIMARY_DATABASE_URL or DATABASE_URL before running this script.")
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


def build_patient(index: int) -> Patient:
    """Create one deterministic, valid seed patient with a unique MRN."""
    birth_date = date(1940, 1, 1) + timedelta(days=(index * 37) % 24000)
    first_name = FIRST_NAMES[(index - 1) % len(FIRST_NAMES)]
    last_name = LAST_NAMES[((index - 1) // len(FIRST_NAMES)) % len(LAST_NAMES)]

    return Patient(
        first_name=first_name,
        last_name=last_name,
        date_of_birth=birth_date.isoformat(),
        phone=f"+1555{index:07d}",
        email=f"seed.patient.{index:04d}@example.test",
        mrn_encrypted=f"SEED-PATIENT-{index:06d}",
        language_code="en",
        resolution_method="MRN",
        partial_match=False,
        notification_opt_out=False,
    )


async def seed_patients() -> None:
    """Insert patients until the table contains at least 500 records."""
    engine = create_async_engine(get_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            current_count = await session.scalar(select(func.count(Patient.id)))
            required_count = max(0, MINIMUM_PATIENT_COUNT - (current_count or 0))

            if required_count == 0:
                print(f"Patient count: {current_count}")
                return

            start_index = (current_count or 0) + 1
            patients = [
                build_patient(index)
                for index in range(start_index, start_index + required_count)
            ]

            for offset in range(0, len(patients), BATCH_SIZE):
                session.add_all(patients[offset:offset + BATCH_SIZE])
                await session.flush()

            await session.commit()
            final_count = await session.scalar(select(func.count(Patient.id)))

        print(f"Patient count: {final_count}")
        if (final_count or 0) < MINIMUM_PATIENT_COUNT:
            raise RuntimeError("Unable to seed the requested minimum of 500 patients.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_patients())