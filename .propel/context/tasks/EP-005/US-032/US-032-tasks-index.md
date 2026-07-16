---
id: US-032-tasks-index
title: "Task Index — US-032: Alert Pharmacist for High-Risk Drug Classes at Discharge"
user_story: US-032
epic: EP-005
sprint: 2
total_tasks: 9
total_estimate: 26h
status: Draft
date: 2026-07-16
---

# Task Index — US-032: Alert Pharmacist for High-Risk Drug Classes at Discharge

> **Epic:** EP-005 — Medication Reconciliation Agent | **Sprint:** 2 | **Story Points:** 3
> **Total Tasks:** 9 | **Total Estimate:** 26h | **Status:** Draft

---

## Task Summary

| Task | Title | Layer | Est | Priority | Upstream |
|------|-------|-------|-----|----------|----------|
| [TASK-001](task_001_high_risk_drugs_yaml_config.md) | Create `config/high_risk_drugs.yaml` — High-Risk Drug Class Mapping | Backend / Config | 1h | Must Have | US-030/TASK-003 |
| [TASK-002](task_002_high_risk_drug_class_detector.md) | `HighRiskDrugClassDetector` Service — Discharge List Scanner | Backend | 4h | Must Have | TASK-001 |
| [TASK-003](task_003_extend_pharmacist_alert_orm_model.md) | Extend PharmacistAlert ORM Model — HIGH_RISK_DRUG_CLASS Alert Fields | Backend / Database | 3h | Must Have | US-031/TASK-005, US-031/TASK-006 |
| [TASK-004](task_004_alembic_migration_high_risk_drug_class.md) | Alembic Migration — Extend pharmacist_alerts Table | Backend / Database | 1h | Must Have | TASK-003, US-031/TASK-006 |
| [TASK-005](task_005_alert_resolve_endpoint.md) | `PATCH /api/v1/alerts/{id}/resolve` — Pharmacist-Only Alert Resolution Endpoint | Backend | 4h | Must Have | TASK-003, TASK-004, US-031/TASK-005 |
| [TASK-006](task_006_alert_sla_monitor.md) | `AlertSLAMonitor` — 24-Hour SLA Breach Detection and Charge Pharmacist Escalation | Backend | 4h | Must Have | TASK-003, TASK-004 |
| [TASK-007](task_007_wire_high_risk_detector_into_pipeline.md) | Wire `HighRiskDrugClassDetector` into Medication Reconciliation Agent Pipeline | Backend | 3h | Must Have | TASK-002, TASK-003, US-031/TASK-007 |
| [TASK-008](task_008_unit_tests_high_risk_drug_class.md) | Unit Tests — HighRiskDrugClassDetector, Alert Resolution RBAC, SLA Monitor | Quality Assurance | 4h | Must Have | TASK-002, TASK-005, TASK-006, TASK-007 |
| [TASK-009](task_009_code_review_dod_signoff.md) | Code Review and Definition of Done Sign-off | Quality Assurance | 2h | Must Have | TASK-001 through TASK-008 |

---

## Dependency Order

```
TASK-001 (YAML config)
    └── TASK-002 (HighRiskDrugClassDetector)
            └── TASK-007 (Wire into pipeline)

US-031/TASK-005 + US-031/TASK-006
    └── TASK-003 (Extend ORM model + schemas)
            └── TASK-004 (Alembic migration)
                    ├── TASK-005 (Resolve endpoint)
                    └── TASK-006 (SLA monitor)

TASK-002 + TASK-003 + US-031/TASK-007
    └── TASK-007 (Pipeline integration)

TASK-002 + TASK-005 + TASK-006 + TASK-007
    └── TASK-008 (Unit tests)
            └── TASK-009 (Code review / DoD sign-off)
```

---

## Acceptance Criteria Traceability

| US-032 AC Scenario | Tasks |
|-------------------|-------|
| Scenario 1 — Anticoagulant triggers mandatory HIGH_RISK_DRUG_CLASS alert | TASK-001, TASK-002, TASK-003, TASK-004, TASK-007 |
| Scenario 2 — Pharmacist resolution workflow | TASK-003, TASK-004, TASK-005 |
| Scenario 3 — 24h SLA breach → CHARGE_PHARMACIST_ESCALATION | TASK-003, TASK-004, TASK-006 |
| Scenario 4 — 403 Forbidden for non-pharmacist role | TASK-005, TASK-008 |

---

## Files to be Created / Modified

| Action | Path | Task |
|--------|------|------|
| Create | `backend/config/high_risk_drugs.yaml` | TASK-001 |
| Create | `backend/app/agents/medication_reconciliation/high_risk/__init__.py` | TASK-001 |
| Create | `backend/app/agents/medication_reconciliation/high_risk/config_loader.py` | TASK-001 |
| Create | `backend/app/agents/medication_reconciliation/high_risk/detector.py` | TASK-002 |
| Modify | `backend/app/models/pharmacist_alert.py` | TASK-003 |
| Modify | `backend/app/schemas/pharmacist_alert.py` | TASK-003 |
| Create | `backend/alembic/versions/<rev>_extend_pharmacist_alerts_high_risk_drug_class.py` | TASK-004 |
| Create | `backend/app/routers/alerts.py` | TASK-005 |
| Modify | `backend/app/main.py` | TASK-005 |
| Modify | `backend/app/core/auth/dependencies.py` | TASK-005 |
| Create | `backend/app/services/alert_sla_monitor.py` | TASK-006 |
| Create | `backend/app/jobs/run_sla_monitor.py` | TASK-006 |
| Modify | `infra/terraform/modules/cloud_run/main.tf` | TASK-006 |
| Modify | `backend/app/agents/medication_reconciliation/pipeline.py` | TASK-007 |
| Create | `backend/tests/unit/test_high_risk_drug_class_detector.py` | TASK-008 |
| Create | `backend/tests/unit/test_alert_resolve_endpoint.py` | TASK-008 |
| Create | `backend/tests/unit/test_alert_sla_monitor.py` | TASK-008 |
