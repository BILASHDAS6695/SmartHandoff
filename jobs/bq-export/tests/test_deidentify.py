"""Unit tests for the de-identification pipeline.

Tests are pure and require no external services (no Cloud SQL, no BigQuery).
All assertions use synthetic data only.

Design refs:
    US-062 AC Scenario 2 — PHI fields absent
    US-062 AC Scenario 3 — deterministic idempotent hash
    US-062 Technical Notes — SHA-256(encounter_id + salt)
"""
from __future__ import annotations

import hashlib

import pytest

from app.deidentify import deidentify_batch, deidentify_row, hash_encounter_id


class TestHashEncounterId:
    """Test cases for SHA-256 hashing of encounter IDs."""

    def test_returns_64_char_hex_string(self, synthetic_salt):
        """Hash output must be a 64-character lowercase hex string."""
        result = hash_encounter_id("ENC-001", synthetic_salt)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic_same_inputs_same_output(self, synthetic_salt):
        """Same encounter_id + salt must always produce the same hash (idempotency)."""
        h1 = hash_encounter_id("ENC-001", synthetic_salt)
        h2 = hash_encounter_id("ENC-001", synthetic_salt)
        assert h1 == h2

    def test_different_salts_produce_different_hashes(self):
        """Different salts must produce different hashes for the same encounter_id."""
        h1 = hash_encounter_id("ENC-001", "salt-2026-06")
        h2 = hash_encounter_id("ENC-001", "salt-2026-07")
        assert h1 != h2

    def test_different_encounter_ids_produce_different_hashes(self, synthetic_salt):
        """Different encounter IDs must produce different hashes."""
        h1 = hash_encounter_id("ENC-001", synthetic_salt)
        h2 = hash_encounter_id("ENC-002", synthetic_salt)
        assert h1 != h2

    def test_pipe_separator_prevents_collision(self, synthetic_salt):
        """'ENC|001' + 'salt' must differ from 'ENC' + '001salt'."""
        h1 = hash_encounter_id("ENC|001", synthetic_salt)
        h2 = hash_encounter_id("ENC", f"001{synthetic_salt}")
        assert h1 != h2

    def test_matches_manual_sha256(self, synthetic_salt):
        """Hash output must match manual SHA-256 computation."""
        enc_id = "ENC-001"
        expected = hashlib.sha256(
            f"{enc_id}|{synthetic_salt}".encode("utf-8")
        ).hexdigest()
        assert hash_encounter_id(enc_id, synthetic_salt) == expected


class TestDeidentifyRow:
    """Test cases for de-identifying a single encounter row."""

    def test_encounter_id_removed_from_output(self, synthetic_row, synthetic_salt):
        """Raw encounter_id must be removed from the output dict."""
        result = deidentify_row(synthetic_row, synthetic_salt)
        assert "encounter_id" not in result

    def test_encounter_id_hash_present_in_output(self, synthetic_row, synthetic_salt):
        """encounter_id_hash must be present and be a 64-char hex string."""
        result = deidentify_row(synthetic_row, synthetic_salt)
        assert "encounter_id_hash" in result
        assert len(result["encounter_id_hash"]) == 64

    def test_safe_fields_preserved(self, synthetic_row, synthetic_salt):
        """All safe fields from the input must be preserved in output."""
        result = deidentify_row(synthetic_row, synthetic_salt)
        safe_fields = {
            "admit_date", "discharge_date", "primary_diagnosis_code",
            "risk_score", "risk_tier", "unit", "los_days",
            "discharge_disposition", "readmitted_30d",
        }
        for field in safe_fields:
            assert field in result, f"Expected safe field '{field}' missing from output"

    def test_phi_guard_raises_on_phi_column(self, synthetic_row_with_phi, synthetic_salt):
        """assert_no_phi() must raise ValueError if PHI column is present."""
        with pytest.raises(ValueError, match="PHI columns detected"):
            deidentify_row(synthetic_row_with_phi, synthetic_salt)

    def test_does_not_mutate_input_row(self, synthetic_row, synthetic_salt):
        """deidentify_row must not mutate the input dict."""
        original_keys = set(synthetic_row.keys())
        deidentify_row(synthetic_row, synthetic_salt)
        assert set(synthetic_row.keys()) == original_keys

    def test_idempotent_hash_on_repeated_calls(self, synthetic_row, synthetic_salt):
        """Re-running de-identification for the same row + salt yields the same hash."""
        h1 = deidentify_row(dict(synthetic_row), synthetic_salt)["encounter_id_hash"]
        h2 = deidentify_row(dict(synthetic_row), synthetic_salt)["encounter_id_hash"]
        assert h1 == h2

    def test_raises_key_error_if_encounter_id_missing(self, synthetic_salt):
        """deidentify_row must raise KeyError if encounter_id is missing."""
        row_without_id = {
            "admit_date": "2026-07-14",
            "unit": "ICU-3",
        }
        with pytest.raises(KeyError):
            deidentify_row(row_without_id, synthetic_salt)


class TestDeidentifyBatch:
    """Test cases for de-identifying a batch of encounter rows."""

    def test_all_rows_processed(self, synthetic_row, synthetic_salt):
        """All rows without missing ID should be de-identified."""
        batch = [dict(synthetic_row) for _ in range(5)]
        result = deidentify_batch(batch, synthetic_salt)
        assert len(result) == 5

    def test_rows_missing_encounter_id_are_skipped(self, synthetic_row, synthetic_salt):
        """Rows missing encounter_id should be skipped, not abort."""
        row_no_id = {k: v for k, v in synthetic_row.items() if k != "encounter_id"}
        batch = [dict(synthetic_row), row_no_id]
        result = deidentify_batch(batch, synthetic_salt)
        # Only the valid row is processed; missing-ID row is skipped
        assert len(result) == 1

    def test_empty_batch_returns_empty_list(self, synthetic_salt):
        """Empty batch should return empty list."""
        assert deidentify_batch([], synthetic_salt) == []
