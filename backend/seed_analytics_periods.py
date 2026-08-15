#!/usr/bin/env python3
"""Seed discharged encounters across the last 90 days so analytics period filters show different data."""

import asyncio
import os
import uuid
import random
from datetime import datetime, timedelta, timezone

import asyncpg

UNITS = ["ICU", "ED", "CARD", "CCU", "MED", "PEDS", "SURG", "GENERAL", "NEURO", "OB", "ONC"]
MEDS = [
    ("Lisinopril", "10mg", "oral", "daily"),
    ("Metformin", "500mg", "oral", "daily"),
    ("Atorvastatin", "20mg", "oral", "daily"),
    ("Amoxicillin", "500mg", "oral", "twice daily"),
    ("Ibuprofen", "400mg", "oral", "as needed"),
    ("Aspirin", "81mg", "oral", "daily"),
    ("Metoprolol", "25mg", "oral", "daily"),
    ("Omeprazole", "20mg", "oral", "daily"),
]

# Document statuses that are NOT filtered out by the analytics query.
DOCUMENT_STATUS = "approved"


async def connect():
    return await asyncpg.connect(
        database="smarthandoff",
        user="postgres",
        password="SmartHandoff@123",
        host="127.0.0.1",
        port=9432,
    )


async def random_patient(conn):
    row = await conn.fetchrow("SELECT id FROM patient WHERE deleted_at IS NULL ORDER BY RANDOM() LIMIT 1")
    return row["id"]


async def seed_discharges(conn, day_min, day_max, count):
    """Create `count` discharged encounters with discharge dates spread across [day_min, day_max] days ago."""
    today = datetime.now(timezone.utc).date()
    created = 0

    for i in range(count):
        patient_id = await random_patient(conn)
        days_ago = random.randint(day_min, day_max)
        discharge_date = datetime.combine(today - timedelta(days=days_ago), datetime.min.time()).replace(
            hour=random.randint(8, 18), minute=random.randint(0, 59), tzinfo=timezone.utc
        )
        admit_date = discharge_date - timedelta(days=random.randint(1, 7), hours=random.randint(1, 12))
        unit = random.choice(UNITS)
        encounter_id = uuid.uuid4()
        risk_score = round(random.uniform(0.1, 0.9), 2)
        risk_tier = "HIGH" if risk_score > 0.7 else "MEDIUM" if risk_score > 0.3 else "LOW"

        await conn.execute(
            """
            INSERT INTO encounter (
                id, patient_id, unit, status, admit_date, discharge_date,
                risk_score, risk_tier, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            encounter_id, patient_id, unit, "DISCHARGED", admit_date, discharge_date,
            risk_score, risk_tier, admit_date, discharge_date,
        )

        # Discharge documents: completed a few hours before discharge.
        doc_completed_at = discharge_date - timedelta(hours=random.randint(2, 12))
        for doc_type, title in [
            ("discharge_summary", "Discharge Summary"),
            ("patient_instructions", "Discharge Instructions"),
        ]:
            await conn.execute(
                """
                INSERT INTO document (
                    id, encounter_id, document_type, content, status,
                    language_code, generation_type, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, 'en', 'LLM', $6, $7)
                """,
                uuid.uuid4(), encounter_id, doc_type,
                f"{title} - {discharge_date.strftime('%Y-%m-%d')}. "
                "Patient discharged in stable condition. Follow up with primary care recommended.",
                "approved", doc_completed_at, doc_completed_at,
            )

        # Medications: 80% fully reconciled, 20% incomplete.
        fully_reconciled = random.random() < 0.8
        for _ in range(random.randint(1, 3)):
            name, dose, route, frequency = random.choice(MEDS)
            if fully_reconciled:
                med_status = "reconciled"
            else:
                med_status = "reconciled" if random.random() < 0.5 else "pending"
            await conn.execute(
                """
                INSERT INTO medication (
                    id, encounter_id, drug_name, dose, route, frequency,
                    reconciliation_status, source, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'discharge', $8, $9)
                """,
                uuid.uuid4(), encounter_id, name, dose, route, frequency,
                med_status, discharge_date, discharge_date,
            )

        # 25% readmission: create a follow-up encounter admitted 5-25 days after discharge.
        if random.random() < 0.25:
            readmit_date = discharge_date + timedelta(days=random.randint(5, 25))
            await conn.execute(
                """
                INSERT INTO encounter (
                    id, patient_id, unit, status, admit_date, risk_score, risk_tier,
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                uuid.uuid4(), patient_id, unit, "ADMITTED", readmit_date,
                round(random.uniform(0.1, 0.9), 2), "MEDIUM", readmit_date, readmit_date,
            )

        created += 1

    return created


async def main():
    conn = await connect()
    try:
        # Add data for two windows so Last 7, 30, and 90 days all differ.
        c8_30 = await seed_discharges(conn, day_min=8, day_max=30, count=18)
        c31_90 = await seed_discharges(conn, day_min=31, day_max=90, count=28)
        print(f"Seeded {c8_30} discharges for 8-30 days ago and {c31_90} discharges for 31-90 days ago.")

        for days in [7, 30, 90]:
            count = await conn.fetchval(
                f"""SELECT COUNT(*) FROM encounter
                    WHERE deleted_at IS NULL AND status='DISCHARGED'
                      AND discharge_date >= CURRENT_DATE - INTERVAL '{days} days'"""
            )
            print(f"Last {days} days discharges: {count}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
