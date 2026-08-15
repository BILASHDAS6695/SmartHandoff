"""Soft-delete duplicate encounters and migrate related records.

Run from the backend directory:
    set -a && source .env && set -a && ./venv/bin/python cleanup_duplicate_encounters.py

Logic:
- Groups active encounters by (patient_id, unit, created_at::date).
- For each group with >1 row, picks a canonical encounter:
  1. Prefer ADMITTED / TRANSFERRED status.
  2. Prefer the encounter with the most related records (documents, medications, beds).
  3. Prefer the most recently created.
- Moves documents, medications, and bed.current_encounter_id references to the canonical encounter.
- Soft-deletes the duplicate encounters (sets deleted_at).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.bed import Bed
from app.models.document import Document
from app.models.encounter import Encounter
from app.models.medication import Medication

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


async def cleanup(session: AsyncSession) -> int:
    """Remove duplicate encounters; return number soft-deleted."""
    dup_groups = await session.execute(
        select(Encounter.patient_id, func.date(Encounter.created_at))
        .where(Encounter.deleted_at.is_(None))
        .group_by(Encounter.patient_id, func.date(Encounter.created_at))
        .having(func.count(Encounter.id) > 1)
    )
    groups = dup_groups.all()
    logger.info("Found %s duplicate encounter groups", len(groups))

    total_deleted = 0

    for patient_id, dt in groups:
        result = await session.execute(
            select(Encounter)
            .where(Encounter.patient_id == patient_id)
            .where(func.date(Encounter.created_at) == dt)
            .where(Encounter.deleted_at.is_(None))
            .order_by(Encounter.created_at.desc())
        )
        encounters = result.scalars().all()
        if len(encounters) < 2:
            continue

        async def score(enc: Encounter) -> tuple[int, int, datetime]:
            doc_count = (
                await session.execute(
                    select(func.count(Document.id)).where(Document.encounter_id == enc.id)
                )
            ).scalar() or 0
            med_count = (
                await session.execute(
                    select(func.count(Medication.id)).where(Medication.encounter_id == enc.id)
                )
            ).scalar() or 0
            bed_count = (
                await session.execute(
                    select(func.count(Bed.id)).where(Bed.current_encounter_id == enc.id)
                )
            ).scalar() or 0
            status_score = 2 if enc.status in ("ADMITTED", "TRANSFERRED") else (
                1 if enc.status == "DISCHARGED" else 0
            )
            return status_score, doc_count + med_count + bed_count, enc.created_at

        scored = [(enc, await score(enc)) for enc in encounters]
        scored.sort(key=lambda item: item[1], reverse=True)

        canonical = scored[0][0]
        duplicates = [item[0] for item in scored[1:]]
        duplicate_ids = [dup.id for dup in duplicates]

        logger.info(
            "Keeping %s (%s, %s), deleting %s duplicates",
            canonical.id,
            canonical.status,
            canonical.created_at,
            len(duplicates),
        )

        # Migrate related records to the canonical encounter.
        if duplicate_ids:
            await session.execute(
                update(Document)
                .where(Document.encounter_id.in_(duplicate_ids))
                .values(encounter_id=canonical.id)
            )
            await session.execute(
                update(Medication)
                .where(Medication.encounter_id.in_(duplicate_ids))
                .values(encounter_id=canonical.id)
            )
            await session.execute(
                update(Bed)
                .where(Bed.current_encounter_id.in_(duplicate_ids))
                .values(current_encounter_id=canonical.id)
            )

        # Soft-delete duplicates.
        for dup in duplicates:
            dup.deleted_at = _utc_now()
            total_deleted += 1

    await session.commit()
    return total_deleted


async def main() -> None:
    from app.core.config import settings

    engine = create_async_engine(str(settings.primary_database_url))
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        deleted = await cleanup(session)
        logger.info("Soft-deleted %s duplicate encounters", deleted)

    await engine.dispose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
