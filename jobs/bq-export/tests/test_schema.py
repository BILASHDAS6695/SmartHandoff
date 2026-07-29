"""Unit tests for the BigQuery schema and PHI blocklist guard.

Design refs:
    US-062 AC Scenario 2 — PHI columns absent from schema
    US-062 DoD — BigQuery schema fields defined
"""
from __future__ import annotations

import pytest

from app.schema import (
    ENCOUNTERS_DEIDENTIFIED_SCHEMA,
    _PHI_COLUMNS_BLOCKLIST,
    assert_no_phi,
)

# All PHI fields that must NEVER appear in the schema
PHI_FIELDS = ["mrn", "first_name", "last_name", "dob", "phone", "email",
              "patient_id", "encounter_id"]

# All safe fields that MUST be present in the schema per US-062 DoD
REQUIRED_SAFE_FIELDS = [
    "encounter_id_hash", "admit_date", "discharge_date",
    "primary_diagnosis_code", "risk_score", "risk_tier",
    "unit", "los_days", "discharge_disposition", "readmitted_30d",
]


class TestSchemaFields:
    """Test cases for BigQuery schema field validation."""

    @pytest.fixture
    def schema_field_names(self):
        """Extract all field names from the schema."""
        return [field.name for field in ENCOUNTERS_DEIDENTIFIED_SCHEMA]

    def test_all_required_safe_fields_present(self, schema_field_names):
        """All required safe fields must be present in the schema."""
        for field in REQUIRED_SAFE_FIELDS:
            assert field in schema_field_names, (
                f"Required safe field '{field}' missing from ENCOUNTERS_DEIDENTIFIED_SCHEMA"
            )

    @pytest.mark.parametrize("phi_field", PHI_FIELDS)
    def test_phi_field_absent_from_schema(self, schema_field_names, phi_field):
        """No PHI fields must appear in the schema."""
        assert phi_field not in schema_field_names, (
            f"PHI field '{phi_field}' must NOT appear in ENCOUNTERS_DEIDENTIFIED_SCHEMA"
        )

    def test_schema_has_exactly_ten_fields(self, schema_field_names):
        """Schema must have exactly 10 fields per US-062 DoD."""
        assert len(schema_field_names) == 10, (
            f"Schema should have exactly 10 fields per US-062 DoD, got {len(schema_field_names)}"
        )


class TestAssertNoPhi:
    """Test cases for the PHI guard function."""

    @pytest.mark.parametrize("phi_field", PHI_FIELDS)
    def test_raises_on_each_phi_field(self, phi_field):
        """assert_no_phi must raise ValueError for any PHI field."""
        with pytest.raises(ValueError, match="PHI columns detected"):
            assert_no_phi(["encounter_id_hash", "admit_date", phi_field])

    def test_passes_on_clean_schema(self):
        """assert_no_phi should not raise for a clean schema."""
        assert_no_phi(REQUIRED_SAFE_FIELDS)  # must not raise

    def test_error_message_includes_field_name(self):
        """Error message must include the PHI field name detected."""
        with pytest.raises(ValueError, match="mrn"):
            assert_no_phi(["admit_date", "mrn"])


class TestPhiBlocklist:
    """Test the PHI blocklist constant."""

    def test_blocklist_contains_all_expected_phi_fields(self):
        """The blocklist must contain all known PHI field names."""
        for phi_field in PHI_FIELDS:
            assert phi_field in _PHI_COLUMNS_BLOCKLIST, (
                f"PHI field '{phi_field}' not in _PHI_COLUMNS_BLOCKLIST"
            )
