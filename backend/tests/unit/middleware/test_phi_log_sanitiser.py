"""Unit tests for PHI log sanitiser (US-058/TASK-005).

Tests cover:
  - redact_phi(): all 6 PHI field names from DoD (first_name, last_name, mrn,
    dob, phone, email); non-PHI fields preserved; email/phone inline patterns
  - PhiLoggingFilter: log records with PHI values have values replaced
  - PhiLoggingFilter: non-PHI log records pass through unchanged
  - PhiLoggingFilter: always returns True (never discards records)
  - PhiLoggingFilter: % args as dict and tuple are sanitised
"""
from __future__ import annotations

import io
import logging

import pytest

from app.middleware.phi_log_sanitiser import PhiLoggingFilter, redact_phi


class TestRedactPhi:
    def test_redacts_first_name_json(self):
        result = redact_phi('{"first_name": "Alice"}')
        assert "Alice" not in result
        assert "[REDACTED]" in result

    def test_redacts_last_name_json(self):
        result = redact_phi('{"last_name": "Smith"}')
        assert "Smith" not in result
        assert "[REDACTED]" in result

    def test_redacts_mrn_json(self):
        result = redact_phi('{"mrn": "MRN-987654"}')
        assert "MRN-987654" not in result
        assert "[REDACTED]" in result

    def test_redacts_dob_json(self):
        result = redact_phi('{"dob": "1980-05-15"}')
        assert "1980-05-15" not in result
        assert "[REDACTED]" in result

    def test_redacts_phone_json(self):
        result = redact_phi('{"phone": "555-867-5309"}')
        assert "555-867-5309" not in result
        assert "[REDACTED]" in result

    def test_redacts_email_json(self):
        result = redact_phi('{"email": "alice@hospital.com"}')
        assert "alice@hospital.com" not in result
        assert "[REDACTED-EMAIL]" in result

    def test_non_phi_fields_preserved(self):
        result = redact_phi('{"encounter_id": "abc-123", "status": "ADMITTED"}')
        assert "abc-123" in result
        assert "ADMITTED" in result

    def test_multiple_phi_fields_in_one_message(self):
        msg = '{"first_name": "Jane", "last_name": "Doe", "mrn": "MRN001"}'
        result = redact_phi(msg)
        assert "Jane" not in result
        assert "Doe" not in result
        assert "MRN001" not in result

    def test_inline_email_redacted(self):
        result = redact_phi("Patient email is jane@example.com please check")
        assert "jane@example.com" not in result
        assert "[REDACTED-EMAIL]" in result

    @pytest.mark.parametrize("phone", [
        "555-867-5309",
        "(555) 867-5309",
        "+15558675309",
        "555.867.5309",
    ])
    def test_phone_formats_redacted(self, phone: str):
        result = redact_phi(f"Contact: {phone}")
        assert phone not in result, f"Phone {phone!r} not redacted"
        assert "[REDACTED-PHONE]" in result

    def test_python_dict_repr_redacted(self):
        result = redact_phi("{'first_name': 'Bob', 'mrn': 'XYZ123'}")
        assert "Bob" not in result
        assert "XYZ123" not in result

    def test_empty_string_unchanged(self):
        assert redact_phi("") == ""

    def test_no_phi_string_unchanged(self):
        msg = "Encounter created successfully for bed ICU-4"
        assert redact_phi(msg) == msg


class TestPhiLoggingFilter:
    def _capture_log(self, message: str, level: int = logging.WARNING) -> str:
        """Emit a log record with the PHI filter and capture the raw message."""
        unique_name = f"test.phi.{id(message)}"
        test_logger = logging.getLogger(unique_name)
        test_logger.setLevel(logging.DEBUG)
        test_logger.propagate = False

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)
        test_logger.addFilter(PhiLoggingFilter())

        test_logger.log(level, message)
        return stream.getvalue()

    def test_phi_value_redacted_in_log_output(self):
        output = self._capture_log('Patient {"first_name": "Alice"} accessed')
        assert "Alice" not in output
        assert "[REDACTED]" in output

    def test_non_phi_log_passes_through(self):
        output = self._capture_log("Encounter 550e8400 status changed to ADMITTED")
        assert "550e8400" in output
        assert "ADMITTED" in output

    def test_filter_always_returns_true(self):
        """PhiLoggingFilter.filter() must always return True — never discards records."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='{"first_name": "Bob"}',
            args=(),
            exc_info=None,
        )
        phi_filter = PhiLoggingFilter()
        result = phi_filter.filter(record)
        assert result is True
        assert "Bob" not in record.msg

    def test_args_dict_redacted(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Patient %s",
            args={"first_name": "Carol"},
            exc_info=None,
        )
        phi_filter = PhiLoggingFilter()
        phi_filter.filter(record)
        assert isinstance(record.args, dict)
        assert "Carol" not in str(record.args)

    def test_args_tuple_redacted(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Values: %s %s",
            args=("alice@hospital.com", "some_value"),
            exc_info=None,
        )
        phi_filter = PhiLoggingFilter()
        phi_filter.filter(record)
        assert "alice@hospital.com" not in str(record.args)

    def test_extra_phi_field_on_record_redacted(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="log message",
            args=(),
            exc_info=None,
        )
        record.first_name = "Sensitive"  # type: ignore[attr-defined]
        phi_filter = PhiLoggingFilter()
        phi_filter.filter(record)
        assert record.first_name == "[REDACTED]"  # type: ignore[attr-defined]
