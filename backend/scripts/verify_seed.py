"""Quick verification that seed data exists."""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.document import Document
from app.models.medication import Medication

ENCOUNTER_ID = uuid.UUID("e9d6a8e1-0234-4a3b-bc39-b07d98008858")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


async def main() -> None:
    engine = create_async_engine(_database_url(), poolclass=NullPool, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        med_result = await session.execute(
            select(Medication).where(Medication.encounter_id == ENCOUNTER_ID)
        )
        meds = med_result.scalars().all()
        print(f"Medications: {len(meds)}")
        for m in meds:
            print(f"  - {m.drug_name} | {m.reconciliation_category.value if m.reconciliation_category else None} | sources={m.sources}")

        doc_result = await session.execute(
            select(Document).where(Document.encounter_id == ENCOUNTER_ID)
        )
        docs = doc_result.scalars().all()
        print(f"Documents: {len(docs)}")
        for d in docs:
            print(f"  - {d.document_type} | {d.status} | content preview: {str(d.content)[:80]}...")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
