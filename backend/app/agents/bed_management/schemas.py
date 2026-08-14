"""Pydantic schemas for BedManagementAgent structured output.

Design refs:
    US-035 AC Scenarios 1, 2
    ADR-004  — structured Pydantic output enforced for all agents
"""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class BedStatus(str, Enum):
    """Bed occupancy status values.

    Accepts both uppercase and lowercase input so DB rows stored in either
    case can be parsed without error.
    """

    AVAILABLE = "AVAILABLE"
    VACANT = "VACANT"  # mv_bed_board legacy value
    OCCUPIED = "OCCUPIED"
    DIRTY = "DIRTY"
    CLEANING = "CLEANING"
    MAINTENANCE = "MAINTENANCE"
    RESERVED = "RESERVED"
    BLOCKED = "BLOCKED"

    @classmethod
    def _missing_(cls, value: object) -> "BedStatus | None":
        if isinstance(value, str):
            normalized = value.upper()
            if normalized in cls._value2member_map_:
                return cls._value2member_map_[normalized]
        return None


class BedStatusUpdateResult(BaseModel):
    """Structured output produced after each bed status transition."""

    bed_id: str = Field(..., description="UUID of the bed record updated")
    previous_status: BedStatus
    new_status: BedStatus
    encounter_id: str = Field(..., description="Encounter UUID that triggered the update")
    event_type: str = Field(..., description="HL7 ADT event type: A01, A02, or A03")
    housekeeping_notification_published: bool = False
    mv_refresh_triggered: bool = False


def is_terminal_status(status: BedStatus) -> bool:
    """Check if a bed status represents a terminal state.
    
    Args:
        status: The BedStatus to check.
    
    Returns:
        True if the status is terminal (MAINTENANCE, RESERVED), False otherwise.
    """
    return status in {BedStatus.MAINTENANCE, BedStatus.RESERVED}


class BedInventoryEntry(BaseModel):
    """Single bed entry parsed from bed_inventory.yaml.
    
    Design refs:
        US-035 AC Scenario 4 — bed inventory seeding from YAML config
    """

    unit: str
    room: str
    bed_number: str
    bed_type: Literal["MEDICAL", "SURGICAL", "ICU", "STEP_DOWN", "ISOLATION"]
    isolation_required: bool = False
    gender_designation: Literal["ANY", "MALE", "FEMALE"] = "ANY"

    @field_validator("unit", "room", "bed_number")
    @classmethod
    def non_empty(cls, v: str) -> str:
        """Validate that string fields are non-empty."""
        if not v.strip():
            raise ValueError("Field must be non-empty")
        return v.strip()


class BedInventoryConfig(BaseModel):
    """Root model for bed_inventory.yaml.
    
    Design refs:
        US-035 AC Scenario 4 — 200 bed records from YAML config
    """

    units: list[dict]  # parsed into BedInventoryEntry list by seeder

    def flat_beds(self) -> list[BedInventoryEntry]:
        """Return a flat list of BedInventoryEntry across all units.
        
        Returns:
            Flattened list of bed entries from all units.
        """
        entries: list[BedInventoryEntry] = []
        for unit_block in self.units:
            unit_name = unit_block["unit"]
            for bed in unit_block.get("beds", []):
                entries.append(BedInventoryEntry(unit=unit_name, **bed))
        return entries


class HousekeepingNotificationPayload(BaseModel):
    """Payload published to the ``notification-requests`` Pub/Sub topic.

    Contains no PHI — only bed coordinates and event metadata.
    Idempotency key is a deterministic hash of ``bed_id + encounter_id``
    to prevent duplicate housekeeping requests if the agent retries A03.

    Design refs:
        US-035 AC Scenario 2 — housekeeping notification within 5 seconds
        AIR-040              — idempotency key prevents duplicate sends
        BR-020               — no PHI in Pub/Sub payloads
    """

    notification_type: Literal["HOUSEKEEPING_REQUIRED"] = "HOUSEKEEPING_REQUIRED"
    bed_id: str
    unit: str
    room: str
    bed_number: str
    encounter_id: str
    idempotency_key: str

    @classmethod
    def build(
        cls,
        bed_id: str,
        unit: str,
        room: str,
        bed_number: str,
        encounter_id: str,
    ) -> HousekeepingNotificationPayload:
        """Construct the payload with a deterministic idempotency key.

        The key is SHA-256(bed_id + ":" + encounter_id), truncated to 32 hex chars.
        
        Args:
            bed_id: UUID string of the bed requiring cleaning.
            unit: Hospital unit identifier.
            room: Room number.
            bed_number: Bed identifier within room.
            encounter_id: Encounter UUID that triggered A03.
        
        Returns:
            HousekeepingNotificationPayload with deterministic idempotency_key.
        """
        raw = f"{bed_id}:{encounter_id}"
        idempotency_key = hashlib.sha256(raw.encode()).hexdigest()[:32]
        return cls(
            bed_id=bed_id,
            unit=unit,
            room=room,
            bed_number=bed_number,
            encounter_id=encounter_id,
            idempotency_key=idempotency_key,
        )
