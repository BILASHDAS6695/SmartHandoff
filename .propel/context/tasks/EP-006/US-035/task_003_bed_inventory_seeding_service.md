---
id: TASK-003
title: "Bed Inventory Seeding Service — Idempotent YAML-Driven Startup Population"
user_story: US-035
epic: EP-006
sprint: 2
layer: Backend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Backend Engineer
upstream: [US-006, US-035/TASK-002]
---

# TASK-003: Bed Inventory Seeding Service — Idempotent YAML-Driven Startup Population

> **Story:** US-035 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Backend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-035 AC Scenario 4 requires that on first deploy, 200 bed records are created from a YAML configuration file, the `mv_bed_board` materialised view is populated, and the operation is idempotent (re-running on restart does not create duplicates). The seeding must run at Cloud Run service startup before the agent begins consuming Pub/Sub messages.

**Design references:**
- US-035 AC Scenario 4 — `INSERT ... ON CONFLICT DO NOTHING` from `config/bed_inventory.yaml`
- US-035 DoD — "Bed inventory seeding on startup: idempotent"
- design.md §9.2 — `bed-mgmt-agent` Cloud Run min-instances=1; startup must be fast

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 4 | 200 bed records created from config; mv_bed_board populated; no duplicates on restart |

---

## Implementation Steps

### 1. Create `config/bed_inventory.yaml`

```yaml
# Bed inventory configuration — sourced by BedInventorySeeder on service startup.
# Fields: unit, room, bed_number, bed_type, isolation_required, gender_designation
# Bed types: MEDICAL, SURGICAL, ICU, STEP_DOWN, ISOLATION
# Gender designation: ANY, MALE, FEMALE
#
# Design ref: US-035 AC Scenario 4 — 200 beds across 5 units

units:
  - unit: "3A"
    beds:
      - room: "301"
        bed_number: "A"
        bed_type: MEDICAL
        isolation_required: false
        gender_designation: ANY
      - room: "301"
        bed_number: "B"
        bed_type: MEDICAL
        isolation_required: false
        gender_designation: ANY
      # ... (40 beds total for unit 3A)

  - unit: "3B"
    beds:
      # ... (40 beds total for unit 3B)

  - unit: "4A"
    beds:
      # ... (40 beds total for unit 4A)

  - unit: "4B"
    beds:
      # ... (40 beds total for unit 4B)

  - unit: "ICU"
    beds:
      # ... (40 beds total for ICU)
```

> **Note:** The full YAML with all 200 beds must be authored per the hospital's physical layout. This stub defines the schema; populate with actual bed data from Hospital IT.

### 2. Create `backend/app/agents/bed_management/schemas.py` additions

Add Pydantic model for YAML validation (add to existing `schemas.py` from TASK-001):

```python
from pydantic import BaseModel, field_validator
from typing import Literal


class BedInventoryEntry(BaseModel):
    """Single bed entry parsed from bed_inventory.yaml."""

    unit: str
    room: str
    bed_number: str
    bed_type: Literal["MEDICAL", "SURGICAL", "ICU", "STEP_DOWN", "ISOLATION"]
    isolation_required: bool = False
    gender_designation: Literal["ANY", "MALE", "FEMALE"] = "ANY"

    @field_validator("unit", "room", "bed_number")
    @classmethod
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must be non-empty")
        return v.strip()


class BedInventoryConfig(BaseModel):
    """Root model for bed_inventory.yaml."""

    units: list[dict]  # parsed into BedInventoryEntry list by seeder

    def flat_beds(self) -> list[BedInventoryEntry]:
        """Return a flat list of BedInventoryEntry across all units."""
        entries: list[BedInventoryEntry] = []
        for unit_block in self.units:
            unit_name = unit_block["unit"]
            for bed in unit_block.get("beds", []):
                entries.append(BedInventoryEntry(unit=unit_name, **bed))
        return entries
```

### 3. Implement `backend/app/agents/bed_management/seeder.py`

```python
"""BedInventorySeeder — idempotent startup population of the bed table.

Reads ``config/bed_inventory.yaml`` and inserts bed records using
``INSERT INTO bed ... ON CONFLICT (unit, room, bed_number) DO NOTHING``
to guarantee idempotency across service restarts.

After successful seeding, triggers a synchronous mv_bed_board refresh so
the materialised view is populated before the agent starts consuming events.

Design refs:
    US-035 AC Scenario 4 — idempotent seeding; mv_bed_board populated on first deploy
    US-035 DoD           — INSERT ... ON CONFLICT DO NOTHING from YAML config
    design.md §6.4 DR-020 — MRN deduplication pattern (same ON CONFLICT principle)
"""
from __future__ import annotations

import logging
import pathlib
import uuid
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.bed_management.schemas import BedInventoryConfig, BedInventoryEntry, BedStatus
from app.agents.bed_management.refresh_service import BedBoardRefreshService

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = pathlib.Path("config/bed_inventory.yaml")


class BedInventorySeeder:
    """Seeds the ``bed`` table from a YAML configuration file.

    Args:
        session_factory: Async SQLAlchemy write session factory.
        refresh_service: ``BedBoardRefreshService`` for post-seed mv refresh.
        config_path: Path to ``bed_inventory.yaml``; defaults to
            ``config/bed_inventory.yaml`` relative to the working directory.
    """

    def __init__(
        self,
        session_factory: Any,
        refresh_service: BedBoardRefreshService,
        config_path: pathlib.Path = _DEFAULT_CONFIG_PATH,
    ) -> None:
        self._session_factory = session_factory
        self._refresh_service = refresh_service
        self._config_path = config_path

    async def seed(self) -> int:
        """Seed the bed table and return the number of rows inserted.

        Returns:
            Number of new bed rows inserted (0 if all rows already existed).
        """
        config = self._load_config()
        beds = config.flat_beds()
        logger.info("Seeding %d beds from %s", len(beds), self._config_path)

        inserted = 0
        async with self._session_factory() as session:
            inserted = await self._insert_beds(session, beds)
            await session.commit()

        logger.info("Seeding complete: %d new beds inserted", inserted)

        # Always refresh the materialised view after seeding (sync — blocks startup
        # until the view is ready, satisfying AC Scenario 4)
        await self._refresh_service.refresh_sync()
        return inserted

    async def _insert_beds(
        self, session: AsyncSession, beds: list[BedInventoryEntry]
    ) -> int:
        """Execute bulk idempotent INSERT for all bed entries.

        Uses ``ON CONFLICT (unit, room, bed_number) DO NOTHING`` — requires a
        unique constraint on ``(unit, room, bed_number)`` in the ``bed`` table
        (established by US-006 migration).

        Returns:
            Total number of rows actually inserted.
        """
        total_inserted = 0
        for entry in beds:
            result = await session.execute(
                text(
                    """
                    INSERT INTO bed
                        (id, unit, room, bed_number, bed_type,
                         status, isolation_required, gender_designation)
                    VALUES
                        (:id, :unit, :room, :bed_number, :bed_type,
                         :status, :isolation_required, :gender_designation)
                    ON CONFLICT (unit, room, bed_number) DO NOTHING
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "unit": entry.unit,
                    "room": entry.room,
                    "bed_number": entry.bed_number,
                    "bed_type": entry.bed_type,
                    "status": BedStatus.VACANT.value,
                    "isolation_required": entry.isolation_required,
                    "gender_designation": entry.gender_designation,
                },
            )
            total_inserted += result.rowcount
        return total_inserted

    def _load_config(self) -> BedInventoryConfig:
        """Load and validate the YAML config file.

        Raises:
            FileNotFoundError: If the config file does not exist.
            pydantic.ValidationError: If the YAML structure is invalid.
        """
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Bed inventory config not found: {self._config_path}"
            )
        raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8"))
        return BedInventoryConfig(**raw)
```

### 4. Wire seeder into the agent service startup

Update `backend/app/agents/bed_management/main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.agents.bed_management.seeder import BedInventorySeeder
from app.agents.bed_management.refresh_service import BedBoardRefreshService
from app.core.dependencies import get_write_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run seeder before the agent pull loop begins."""
    refresh_service = BedBoardRefreshService(write_session_factory=get_write_db)
    seeder = BedInventorySeeder(
        session_factory=get_write_db,
        refresh_service=refresh_service,
    )
    await seeder.seed()
    yield  # Agent pull loop starts here
```

---

## File Checklist

| File | Action |
|------|--------|
| `config/bed_inventory.yaml` | Create (stub — populate with hospital bed data) |
| `backend/app/agents/bed_management/schemas.py` | Update — add `BedInventoryEntry`, `BedInventoryConfig` |
| `backend/app/agents/bed_management/seeder.py` | Create |
| `backend/app/agents/bed_management/main.py` | Update — add lifespan seeding |

---

## Validation

- [ ] Running `seed()` on an empty DB inserts 200 rows and returns `200`
- [ ] Running `seed()` a second time on a populated DB inserts 0 rows (idempotent)
- [ ] All inserted beds have initial `status=VACANT`
- [ ] `_load_config()` raises `FileNotFoundError` if YAML is missing
- [ ] After seeding, `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_bed_board` completes without error
- [ ] No PHI logged — only row counts and file paths

---

## Definition of Done

- [ ] `BedInventorySeeder` implemented with idempotent `ON CONFLICT DO NOTHING` insert
- [ ] YAML config schema validated via Pydantic `BedInventoryConfig`
- [ ] Post-seed synchronous mv_bed_board refresh wired
- [ ] Seeder invoked in agent startup lifespan
- [ ] Code peer-reviewed before merge
