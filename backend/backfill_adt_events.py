"""One-time backfill: create adt_event rows for all existing encounters.

This script populates the empty adt_event table from existing encounter data
and broadcasts each event to SignalR so the dashboard shows real ADT history.

Usage (local dev):
    cd backend
    python backfill_adt_events.py
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from app.db.session import create_db_engines, get_db_session_context
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.services.adt_event_publisher import AdtEventPublisher


async def main() -> None:
    create_db_engines()
    publisher = AdtEventPublisher()

    async with get_db_session_context() as db:
        stmt = select(Encounter, Patient).join(Patient, Encounter.patient_id == Patient.id)
        rows = (await db.execute(stmt)).all()

        print(f"Backfilling {len(rows)} encounter(s)...")
        created = 0
        for encounter, patient in rows:
            await publisher.publish_for_encounter(
                db,
                encounter,
                patient,
                event_timestamp=encounter.created_at,
            )
            created += 1
            if created % 20 == 0:
                await db.commit()
                print(f"  ...{created} events committed")

        await db.commit()
        print(f"Backfill complete: {created} ADT events created.")


if __name__ == "__main__":
    asyncio.run(main())
