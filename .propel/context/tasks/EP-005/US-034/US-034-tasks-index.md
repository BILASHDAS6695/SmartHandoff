---
id: US-034-tasks-index
user_story: US-034
epic: EP-005
sprint: 2
generated: 2026-07-16
---

# US-034 Implementation Tasks Index

> **Story:** Enforce 24-Hour Reconciliation SLA with Escalation | **Epic:** EP-005 | **Sprint:** 2 | **Points:** 3

---

## Task Summary

| Task | Title | Layer | Est | Upstream |
|---|---|---|---|---|
| [TASK-001](task_001_alembic_migration_sla_escalation_sent_at.md) | Add `sla_escalation_sent_at` nullable timestamp to `agent_task` via Alembic migration | Backend — DB | 2 h | US-021/TASK-002, US-030 |
| [TASK-002](task_002_extend_sla_config_medrec_24h.md) | Extend SLA config YAML with `MEDICATION_RECONCILIATION` 24-hour threshold | Backend — Config | 1 h | US-021/TASK-001 |
| [TASK-003](task_003_medrec_sla_monitor_job.md) | Implement `MedRecSLAMonitor` — second APScheduler job on existing instance | Backend — Service | 3 h | TASK-001, TASK-002, US-021/TASK-003 |
| [TASK-004](task_004_charge_pharmacist_escalation_publisher.md) | Implement `ChargePharmacistEscalationPublisher` — Pub/Sub to `notification-requests` | Backend — Messaging | 2 h | US-021/TASK-004, TASK-002 |
| [TASK-005](task_005_override_endpoint.md) | Implement `PATCH /api/v1/encounters/{id}/tasks/{task_id}/override` endpoint | Backend — API | 3 h | TASK-001, US-030/TASK-005 |
| [TASK-006](task_006_unit_tests.md) | Write unit tests — 24h escalation, duplicate suppression, completed exclusion, override | Backend — Tests | 3 h | TASK-003, TASK-004, TASK-005 |
| [TASK-007](task_007_code_review_dod_signoff.md) | Code review and DoD sign-off | Cross-cutting | 1 h | TASK-001 → TASK-006 |

**Total estimated effort:** 15 h

---

## Dependency Order

```
TASK-001 (migration)
    │
    ├── TASK-002 (sla_config.yaml) ──┐
    │                                │
    │                                ▼
    └──────────────────────► TASK-003 (MedRecSLAMonitor)
                                     │
                             TASK-004 (publisher) ◄── TASK-002
                                     │
                             TASK-005 (override endpoint) ◄── TASK-001
                                     │
                             TASK-006 (unit tests)
                                     │
                             TASK-007 (code review + DoD)
```

---

## AC Scenario Coverage Matrix

| AC Scenario | TASK-001 | TASK-002 | TASK-003 | TASK-004 | TASK-005 | TASK-006 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Scenario 1: 24h SLA breach → escalation | | ✓ | ✓ | ✓ | | ✓ |
| Scenario 2: COMPLETED task → no escalation | | | ✓ | | | ✓ |
| Scenario 3: No duplicate escalation (`sla_escalation_sent_at`) | ✓ | | ✓ | | | ✓ |
| Scenario 4: Override clears flag, sets COMPLETED | ✓ | | | | ✓ | ✓ |
