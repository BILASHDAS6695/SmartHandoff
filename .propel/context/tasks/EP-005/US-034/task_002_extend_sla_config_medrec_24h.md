---
id: TASK-002
title: "Extend SLA Config YAML with `MEDICATION_RECONCILIATION` 24-Hour Threshold"
user_story: US-034
epic: EP-005
sprint: 2
layer: Backend
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-021/TASK-001]
---

# TASK-002: Extend SLA Config YAML with `MEDICATION_RECONCILIATION` 24-Hour Threshold

> **Story:** US-034 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Backend | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-021/TASK-001 established `sla-monitor/app/config/sla_config.yaml` as the single source of truth for per-agent SLA thresholds. The current `MEDICATION_RECONCILIATION` entry uses the general agent SLA (60 minutes). US-034 introduces a **distinct** medication reconciliation admissions SLA: **24 hours from `encounter.admit_time`** (BR-002, CMS Conditions of Participation).

This differs from the generic 30-minute task SLA tracked by US-021 — it measures elapsed time from **admit_time** (not `AgentTask.created_at`) and has a 1440-minute (24-hour) window.

**Design decision:** Rather than overloading the existing `MEDICATION_RECONCILIATION` entry, add a separate named entry `MEDICATION_RECONCILIATION_ADMISSION` with a dedicated `reference_field` key. The `MedRecSLAMonitor` (TASK-003) reads this entry. The existing `SLAConfig` loader (US-021/TASK-001) is extended minimally — one new optional field — to stay DRY.

**Design references:**
- US-021/TASK-001 — `sla_config.yaml` + `SLAConfig` Pydantic loader
- US-034 Technical Notes — `admit_time` sourced from `encounter.admit_time`
- BR-002 — CMS 24-hour medication reconciliation mandate

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | SLA monitor knows the 24-hour window to compare against `encounter.admit_time` |
| DoD | SLA threshold stored in config — not hardcoded in monitor logic |

---

## Implementation Steps

### 1. Add `MEDICATION_RECONCILIATION_ADMISSION` entry to `sla_config.yaml`

Open `sla-monitor/app/config/sla_config.yaml` and add the new entry to the `agents` block. **Do not modify existing entries.**

```yaml
agents:
  # ... existing entries unchanged ...

  # US-034: Admission-time SLA for medication reconciliation (BR-002 / CMS CoP).
  # Unlike task-creation SLAs above, this threshold is measured from encounter.admit_time.
  MEDICATION_RECONCILIATION_ADMISSION:
    threshold_minutes: 1440          # 24 hours
    reference_field: admit_time      # field on Encounter model used as SLA start
    escalation_type: CHARGE_PHARMACIST_ESCALATION
    priority: HIGH
    description: >
      CMS Conditions of Participation require medication reconciliation to be
      completed within 24 hours of admission. Escalate to charge pharmacist
      when MEDICATION_RECONCILIATION AgentTask remains non-COMPLETED 24 hours
      after encounter.admit_time.
```

### 2. Extend `SLAConfig` Pydantic model in `sla_loader.py`

Open `sla-monitor/app/config/sla_loader.py` and add a `reference_field` optional field to the per-agent entry model. Apply a **surgical addition only** — do not change existing fields.

```python
class AgentSLAEntry(BaseModel):
    """Single agent SLA configuration entry."""

    threshold_minutes: int
    reference_field: str = "created_at"  # US-034: admit_time for admission SLAs
    escalation_type: str = "SUPERVISOR_ESCALATION"
    priority: str = "NORMAL"
    description: str = ""
```

If `AgentSLAEntry` already has some but not all of these fields, add only the missing ones.

### 3. Add convenience accessor to `SLAConfig`

In the same `sla_loader.py`, add a method to retrieve the medication admission SLA entry cleanly:

```python
class SLAConfig:
    """Loaded SLA configuration."""

    # ... existing methods unchanged ...

    def med_reconciliation_admission_entry(self) -> AgentSLAEntry:
        """Return the MEDICATION_RECONCILIATION_ADMISSION SLA entry.

        Raises:
            KeyError: If the entry is missing from sla_config.yaml.
        """
        return self.agents["MEDICATION_RECONCILIATION_ADMISSION"]
```

### 4. Validate the YAML loads correctly

Add a quick smoke-test assertion to the existing config unit tests in `sla-monitor/tests/unit/test_sla_config.py`:

```python
def test_medication_reconciliation_admission_entry_loaded(tmp_yaml_config):
    """US-034: MEDICATION_RECONCILIATION_ADMISSION must be present with 1440-minute threshold."""
    config = load_sla_config(tmp_yaml_config)
    entry = config.med_reconciliation_admission_entry()
    assert entry.threshold_minutes == 1440
    assert entry.reference_field == "admit_time"
    assert entry.escalation_type == "CHARGE_PHARMACIST_ESCALATION"
    assert entry.priority == "HIGH"
```

---

## Files Changed

| File | Change |
|---|---|
| `sla-monitor/app/config/sla_config.yaml` | Add `MEDICATION_RECONCILIATION_ADMISSION` entry (surgical addition) |
| `sla-monitor/app/config/sla_loader.py` | Add `reference_field` to `AgentSLAEntry`; add `med_reconciliation_admission_entry()` to `SLAConfig` |
| `sla-monitor/tests/unit/test_sla_config.py` | Smoke-test assertion for new entry |

---

## Definition of Done Checklist

- [ ] `MEDICATION_RECONCILIATION_ADMISSION` entry present in `sla_config.yaml` with `threshold_minutes=1440`, `reference_field=admit_time`, `escalation_type=CHARGE_PHARMACIST_ESCALATION`, `priority=HIGH`
- [ ] `AgentSLAEntry` model has `reference_field` with default `"created_at"`
- [ ] `SLAConfig.med_reconciliation_admission_entry()` accessor exists and raises `KeyError` on missing config
- [ ] Config smoke-test passes
- [ ] No existing SLA entries or thresholds modified
