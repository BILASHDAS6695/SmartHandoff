"""Shared pytest fixtures for bq-export unit tests.

All test data is synthetic — no real PHI values used in any fixture.
"""
from __future__ import annotations

import datetime

import pytest


SYNTHETIC_SALT = "test-salt-2026-07"

SYNTHETIC_ENCOUNTER_ROW = {
    "encounter_id": "ENC-001-SYNTHETIC",
    "admit_date": datetime.date(2026, 7, 14),
    "discharge_date": datetime.date(2026, 7, 16),
    "primary_diagnosis_code": "J18.9",
    "risk_score": 0.72,
    "risk_tier": "HIGH",
    "unit": "ICU-3",
    "los_days": 2.0,
    "discharge_disposition": "HOME",
    "readmitted_30d": False,
}

# A row that incorrectly contains a PHI column — used to test the guard
SYNTHETIC_ROW_WITH_PHI = {
    **SYNTHETIC_ENCOUNTER_ROW,
    "first_name": "SYNTHETIC_FNAME",  # PHI — must be blocked
}


@pytest.fixture
def synthetic_row() -> dict:
    """Return a copy of the synthetic encounter row."""
    return dict(SYNTHETIC_ENCOUNTER_ROW)


@pytest.fixture
def synthetic_row_with_phi() -> dict:
    """Return a copy of the synthetic row with PHI column."""
    return dict(SYNTHETIC_ROW_WITH_PHI)


@pytest.fixture
def synthetic_salt() -> str:
    """Return the synthetic salt for testing."""
    return SYNTHETIC_SALT
