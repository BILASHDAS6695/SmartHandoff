---
id: TASK-004
title: "Create `notification-service/tests/test_sendgrid_template_schemas.py` — Unit Tests for Pydantic Substitution Schema Validation"
user_story: US-066
epic: EP-013
sprint: 2
layer: Backend / Testing
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-004: Create `notification-service/tests/test_sendgrid_template_schemas.py` — Unit Tests for Pydantic Substitution Schema Validation

> **Story:** US-066 | **Epic:** EP-013 | **Sprint:** 2 | **Layer:** Backend / Testing | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-066 DoD specifies:

> *"Unit tests: Pydantic schema validation for each template's substitution variables"*

This task authors pytest unit tests covering:

1. **Happy path** — valid substitution data constructs each schema without error
2. **PHI minimisation** — schemas with patient-facing templates reject `last_name`, `mrn`, `dob` fields
3. **Required field validation** — missing required fields raise `ValidationError`
4. **URL validation** — `portal_link` and `dashboard_link` reject malformed URLs
5. **Pattern validation** — `urgency_level` and `priority` enum patterns reject invalid values
6. **Frozen model** — attempting to mutate a schema after construction raises `ValidationError`
7. **Registry completeness** — `TEMPLATE_SCHEMA_REGISTRY` contains exactly 6 entries

Tests are parameterised via `pytest.mark.parametrize` to avoid per-template boilerplate (DRY principle).

Design decisions:

| Decision | Rationale |
|----------|-----------|
| `pytest.mark.parametrize` over 6 template schemas | Single test function covers all schemas; adding a 7th template automatically requires adding test data (catches omissions) |
| Explicit PHI field assertions (not just absence check) | Must confirm that `last_name`, `mrn`, `dob` are NOT in `model_fields` — prevents future accidental additions |
| `pytest.raises(ValidationError)` for invalid data | Confirms Pydantic v2 validation is active, not silently passing invalid payloads |
| No mocking of SendGrid API | Unit tests for schemas only; upload script integration tested separately in CI |
| `model_config frozen=True` mutation test | Guards against accidental removal of `frozen=True` from `BaseTemplateSchema` |

Design refs: US-066 DoD, TASK-001, pytest best practices.

---

## Acceptance Criteria Addressed

| US-066 AC | Requirement |
|---|---|
| **DoD** | Unit tests exist for Pydantic schema validation of all 6 template types |
| **DoD** | PHI minimisation is programmatically verified (no `mrn`, `dob`, `last_name` on patient schemas) |

---

## Implementation Steps

### 1. Scaffold test directory

```bash
mkdir -p notification-service/tests
touch notification-service/tests/__init__.py
```

### 2. Create `notification-service/tests/test_sendgrid_template_schemas.py`

```python
"""Unit tests — SendGrid Dynamic Template Pydantic substitution schemas.

Covers:
    - Happy-path construction for all 6 templates
    - Required field validation (missing fields raise ValidationError)
    - PHI minimisation: patient-facing schemas must not expose last_name/mrn/dob
    - URL validation: AnyHttpUrl fields reject malformed URLs
    - Pattern validation: urgency_level, priority fields reject invalid values
    - Frozen model: mutation after construction raises ValidationError
    - Registry completeness: TEMPLATE_SCHEMA_REGISTRY has exactly 6 entries

Design refs: US-066 DoD, TASK-001 (schemas).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.sendgrid_templates import (
    AppointmentReminderSchema,
    CareTeamEscalationSchema,
    EDBoardingAlertSchema,
    HousekeepingNotificationSchema,
    MedicationReminderSchema,
    PatientPortalLinkSchema,
    TEMPLATE_SCHEMA_REGISTRY,
)

# ---------------------------------------------------------------------------
# Happy-path fixtures — valid substitution data for each template
# ---------------------------------------------------------------------------

VALID_PATIENT_PORTAL_LINK = {
    "first_name": "Sarah",
    "portal_link": "https://portal.smarthandoff.example.com/link/abc123",
    "discharge_date": "2026-07-20",
    "hospital_name": "City General Hospital",
    "hospital_phone": "+12025551234",
}

VALID_APPOINTMENT_REMINDER = {
    "first_name": "James",
    "appointment_date": "Monday 21 July at 10:00 AM",
    "provider_name": "Dr. Ana Torres",
    "clinic_name": "City General Outpatient Clinic",
    "clinic_address": "100 Health Ave, Suite 200, Springfield",
    "clinic_phone": "+12025559876",
}

VALID_MEDICATION_REMINDER = {
    "first_name": "Maria",
    "drug_name": "Metformin",
    "dose": "500mg",
    "frequency": "twice daily",
    "instructions": "with food",
    "care_team_phone": "+12025550001",
}

VALID_CARE_TEAM_ESCALATION = {
    "encounter_id": "ENC-00123",
    "urgency_level": "HIGH",
    "escalation_reason": "Patient reported chest pain via chatbot requiring immediate review.",
    "unit_name": "Ward 4B",
    "escalated_at": "2026-07-16T09:30:00Z",
    "dashboard_link": "https://app.smarthandoff.example.com/encounters/ENC-00123",
}

VALID_ED_BOARDING_ALERT = {
    "encounter_id": "ENC-00456",
    "boarding_hours": 6.5,
    "predicted_discharge_hours": 2.0,
    "unit_name": "Emergency Department",
    "alert_triggered_at": "2026-07-16T11:00:00Z",
    "dashboard_link": "https://app.smarthandoff.example.com/beds",
}

VALID_HOUSEKEEPING_NOTIFICATION = {
    "encounter_id": "ENC-00789",
    "bed_identifier": "Ward 4B - Bed 12",
    "unit_name": "Ward 4B",
    "discharge_confirmed_at": "2026-07-16T14:00:00Z",
    "priority": "ROUTINE",
}


# ---------------------------------------------------------------------------
# 1. Registry completeness
# ---------------------------------------------------------------------------

class TestTemplateSchemaRegistry:
    """TEMPLATE_SCHEMA_REGISTRY must map exactly 6 template names."""

    EXPECTED_KEYS = {
        "patient_portal_link",
        "appointment_reminder",
        "medication_reminder",
        "care_team_escalation",
        "ed_boarding_alert",
        "housekeeping_notification",
    }

    def test_registry_has_exactly_six_entries(self) -> None:
        assert len(TEMPLATE_SCHEMA_REGISTRY) == 6

    def test_registry_contains_all_expected_keys(self) -> None:
        assert set(TEMPLATE_SCHEMA_REGISTRY.keys()) == self.EXPECTED_KEYS


# ---------------------------------------------------------------------------
# 2. Happy-path construction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "schema_cls, valid_data",
    [
        (PatientPortalLinkSchema, VALID_PATIENT_PORTAL_LINK),
        (AppointmentReminderSchema, VALID_APPOINTMENT_REMINDER),
        (MedicationReminderSchema, VALID_MEDICATION_REMINDER),
        (CareTeamEscalationSchema, VALID_CARE_TEAM_ESCALATION),
        (EDBoardingAlertSchema, VALID_ED_BOARDING_ALERT),
        (HousekeepingNotificationSchema, VALID_HOUSEKEEPING_NOTIFICATION),
    ],
)
def test_valid_substitution_data_constructs_schema(schema_cls, valid_data) -> None:
    """Valid substitution data must construct each schema without raising ValidationError."""
    instance = schema_cls(**valid_data)
    assert instance.template_name == schema_cls.__fields__["template_name"].default


# ---------------------------------------------------------------------------
# 3. PHI minimisation — patient-facing templates
# ---------------------------------------------------------------------------

PHI_FIELDS = {"last_name", "mrn", "dob"}
PATIENT_FACING_SCHEMAS = [
    PatientPortalLinkSchema,
    AppointmentReminderSchema,
    MedicationReminderSchema,
]


@pytest.mark.parametrize("schema_cls", PATIENT_FACING_SCHEMAS)
def test_patient_facing_schema_does_not_expose_phi_fields(schema_cls) -> None:
    """Patient-facing schemas must not declare last_name, mrn, or dob fields (US-066 DoD)."""
    declared_fields = set(schema_cls.model_fields.keys())
    phi_present = declared_fields & PHI_FIELDS
    assert not phi_present, (
        f"{schema_cls.__name__} exposes PHI field(s): {phi_present}. "
        "Remove per US-066 DoD PHI minimisation policy."
    )


# ---------------------------------------------------------------------------
# 4. Required field validation — missing fields raise ValidationError
# ---------------------------------------------------------------------------

class TestRequiredFieldValidation:

    def test_patient_portal_link_missing_first_name_raises(self) -> None:
        data = {k: v for k, v in VALID_PATIENT_PORTAL_LINK.items() if k != "first_name"}
        with pytest.raises(ValidationError) as exc_info:
            PatientPortalLinkSchema(**data)
        assert "first_name" in str(exc_info.value)

    def test_medication_reminder_missing_drug_name_raises(self) -> None:
        data = {k: v for k, v in VALID_MEDICATION_REMINDER.items() if k != "drug_name"}
        with pytest.raises(ValidationError) as exc_info:
            MedicationReminderSchema(**data)
        assert "drug_name" in str(exc_info.value)

    def test_care_team_escalation_missing_encounter_id_raises(self) -> None:
        data = {k: v for k, v in VALID_CARE_TEAM_ESCALATION.items() if k != "encounter_id"}
        with pytest.raises(ValidationError) as exc_info:
            CareTeamEscalationSchema(**data)
        assert "encounter_id" in str(exc_info.value)

    def test_ed_boarding_alert_missing_boarding_hours_raises(self) -> None:
        data = {k: v for k, v in VALID_ED_BOARDING_ALERT.items() if k != "boarding_hours"}
        with pytest.raises(ValidationError) as exc_info:
            EDBoardingAlertSchema(**data)
        assert "boarding_hours" in str(exc_info.value)

    def test_housekeeping_notification_missing_bed_identifier_raises(self) -> None:
        data = {k: v for k, v in VALID_HOUSEKEEPING_NOTIFICATION.items() if k != "bed_identifier"}
        with pytest.raises(ValidationError) as exc_info:
            HousekeepingNotificationSchema(**data)
        assert "bed_identifier" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. URL validation
# ---------------------------------------------------------------------------

class TestURLValidation:

    def test_portal_link_rejects_non_https_url(self) -> None:
        data = {**VALID_PATIENT_PORTAL_LINK, "portal_link": "not-a-url"}
        with pytest.raises(ValidationError):
            PatientPortalLinkSchema(**data)

    def test_dashboard_link_rejects_malformed_url(self) -> None:
        data = {**VALID_CARE_TEAM_ESCALATION, "dashboard_link": "ftp://not-valid"}
        # ftp:// is not AnyHttpUrl — should raise ValidationError
        with pytest.raises(ValidationError):
            CareTeamEscalationSchema(**data)


# ---------------------------------------------------------------------------
# 6. Pattern validation — urgency_level and priority
# ---------------------------------------------------------------------------

class TestPatternValidation:

    def test_urgency_level_rejects_invalid_value(self) -> None:
        data = {**VALID_CARE_TEAM_ESCALATION, "urgency_level": "MEDIUM"}
        with pytest.raises(ValidationError):
            CareTeamEscalationSchema(**data)

    def test_urgency_level_accepts_critical(self) -> None:
        data = {**VALID_CARE_TEAM_ESCALATION, "urgency_level": "CRITICAL"}
        instance = CareTeamEscalationSchema(**data)
        assert instance.urgency_level == "CRITICAL"

    def test_priority_rejects_invalid_value(self) -> None:
        data = {**VALID_HOUSEKEEPING_NOTIFICATION, "priority": "LOW"}
        with pytest.raises(ValidationError):
            HousekeepingNotificationSchema(**data)

    def test_priority_accepts_urgent(self) -> None:
        data = {**VALID_HOUSEKEEPING_NOTIFICATION, "priority": "URGENT"}
        instance = HousekeepingNotificationSchema(**data)
        assert instance.priority == "URGENT"


# ---------------------------------------------------------------------------
# 7. Frozen model — mutation raises ValidationError
# ---------------------------------------------------------------------------

def test_frozen_schema_raises_on_mutation() -> None:
    """All schemas inherit frozen=True from BaseTemplateSchema — mutations must raise."""
    instance = PatientPortalLinkSchema(**VALID_PATIENT_PORTAL_LINK)
    with pytest.raises((ValidationError, TypeError)):
        # Pydantic v2 frozen models raise ValidationError on __setattr__
        instance.first_name = "Mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 8. Optional field behaviour
# ---------------------------------------------------------------------------

class TestOptionalFields:

    def test_patient_portal_link_without_discharge_date_is_valid(self) -> None:
        data = {k: v for k, v in VALID_PATIENT_PORTAL_LINK.items() if k != "discharge_date"}
        instance = PatientPortalLinkSchema(**data)
        assert instance.discharge_date is None

    def test_medication_reminder_without_instructions_is_valid(self) -> None:
        data = {k: v for k, v in VALID_MEDICATION_REMINDER.items() if k != "instructions"}
        instance = MedicationReminderSchema(**data)
        assert instance.instructions is None

    def test_ed_boarding_alert_without_predicted_hours_is_valid(self) -> None:
        data = {
            k: v for k, v in VALID_ED_BOARDING_ALERT.items()
            if k != "predicted_discharge_hours"
        }
        instance = EDBoardingAlertSchema(**data)
        assert instance.predicted_discharge_hours is None
```

---

## Validation Checklist

- [ ] All 8 test classes/functions pass with `pytest -v`
- [ ] `test_patient_facing_schema_does_not_expose_phi_fields` passes for all 3 patient schemas
- [ ] `test_registry_has_exactly_six_entries` passes — confirms all 6 schemas are registered
- [ ] Mutation test confirms `frozen=True` is active on all schemas
- [ ] URL validation tests confirm `AnyHttpUrl` rejects non-HTTP(S) values
- [ ] Pattern tests confirm `urgency_level` and `priority` reject out-of-enum values

---

## Files Created

| File | Purpose |
|------|---------|
| `notification-service/tests/__init__.py` | Test package |
| `notification-service/tests/test_sendgrid_template_schemas.py` | Pydantic schema unit tests |

---

## Dependencies

| Dependency | Direction | Notes |
|---|---|---|
| TASK-001 | Upstream | Tests import all 6 schemas from `app.schemas.sendgrid_templates` |
