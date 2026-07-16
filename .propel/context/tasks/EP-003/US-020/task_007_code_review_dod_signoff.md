---
id: TASK-007
title: "Code Review and Definition of Done Sign-Off for US-020 — Transition Coordinator Agent"
user_story: US-020
epic: EP-003
sprint: 2
layer: Quality
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-020/TASK-001, US-020/TASK-002, US-020/TASK-003, US-020/TASK-004, US-020/TASK-005, US-020/TASK-006]
---

# TASK-007: Code Review and Definition of Done Sign-Off for US-020 — Transition Coordinator Agent

> **Story:** US-020 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Quality | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This is the final gate task for US-020. Before the story can be marked `Done`, a peer code review must confirm all acceptance criteria are satisfied and the Definition of Done checklist is fully ticked. This task documents what the reviewer must validate and the sign-off artifact to produce.

---

## Code Review Checklist

### Functional Correctness

- [ ] **SC-1** — `get_task_types_for_event("ADT^A01")` returns exactly 5 task types matching the DoD list: `DOCUMENTATION`, `MEDICATION_RECONCILIATION`, `BED_MANAGEMENT`, `FOLLOW_UP_CARE`, `PATIENT_COMMUNICATION`
- [ ] **SC-2** — `get_task_types_for_event("ADT^A02")` does NOT include `DISCHARGE_SUMMARY`
- [ ] **SC-3** — SIGTERM handler sets `asyncio.Event` (not `sys.exit()` directly); subscriber `nack`s mid-flight message; process exits ≤30 s
- [ ] **SC-4** — DLQ subscription in Terraform has `max_delivery_attempts = 5`; Cloud Monitoring alert fires on backlog > 0

### Architecture Compliance

- [ ] `TransitionCoordinatorAgent.process_event()` executes a single `INSERT … ON CONFLICT DO NOTHING` — not N individual inserts
- [ ] `ADTSubscriber` uses `FlowControl(max_messages=10)` — verified in TASK-001 code
- [ ] `LLMRetryWrapper._DEFAULT_DELAYS` covers at least 4 attempts — no LLM calls in coordinator hot path
- [ ] `BaseAgentSubscriber` is abstract; `process_task()` is `@abstractmethod`
- [ ] `shared-libs/agent_base/` installable as a local editable package

### Security & PHI Compliance (BR-020, ADR-007)

- [ ] No PHI fields (`mrn`, `first_name`, `last_name`, `dob`) appear in any `logger.*` call
- [ ] Only `encounter_id` (UUID) and `event_type` (enum string) appear in structured logs
- [ ] Pub/Sub message attributes use `patient_mrn_hash` (SHA-256), not raw MRN
- [ ] Dockerfile runs as non-root `appuser`

### Performance Evidence

- [ ] Performance test output attached to PR showing p95 <2 s under 50 concurrent events
- [ ] `COORDINATOR_LATENCY` Prometheus histogram confirms sub-2s p95 in CI run

### Terraform IaC

- [ ] `terraform validate` passes with no errors for all 3 environments
- [ ] `terraform plan` shows exactly 5 new resources (DLQ topic, 2 subscriptions, 2 IAM bindings) + 1 alert policy
- [ ] No hardcoded project IDs in Terraform — all via `var.project_id`

### Test Coverage

- [ ] All 4 US-020 acceptance scenarios have at least one passing test
- [ ] `pytest tests/unit/ -v` passes with 0 failures
- [ ] Performance test evidence attached (p50, p95, max values logged to CI)

---

## Sign-Off Procedure

1. Reviewer runs `pytest tests/unit/ -v` locally — all pass
2. Reviewer runs `terraform validate` and `terraform plan` — clean
3. Reviewer completes the checklist above — all boxes ticked
4. Reviewer leaves approval comment: `"US-020 DoD: VERIFIED — <date> — <reviewer-name>"`
5. Story status updated from `Draft` → `Done`

---

## Files Reviewed in This Task

| File | Review Focus |
|------|-------------|
| `coordinator-agent/app/pubsub/adt_subscriber.py` | FlowControl, ACK/NACK, shutdown_event |
| `coordinator-agent/app/coordinator/task_mapping.py` | SC-1, SC-2 mapping correctness |
| `coordinator-agent/app/coordinator/agent.py` | Atomic INSERT, idempotency, Prometheus metrics |
| `coordinator-agent/app/main.py` | SIGTERM handler, health endpoints, engine dispose |
| `infra/terraform/modules/pubsub/main.tf` | DLQ policy, IAM, alert definition |
| `shared-libs/agent_base/agent_base/` | ABC contract, retry wrapper, structured output |
| `coordinator-agent/tests/unit/` | Coverage of all 4 scenarios |
| `coordinator-agent/tests/performance/` | p95 assertion, concurrent execution |

---

## Definition of Done Checklist (Story-Level)

- [ ] `TransitionCoordinatorAgent` class with Pub/Sub pull subscription (`asyncio`-based)
- [ ] Task creation logic: event type → task type mapping registered in coordinator config
- [ ] `AgentTask` ORM records created in a single DB transaction for atomicity
- [ ] SIGTERM handler: sets `shutdown_event`; processing loop drains current message and exits
- [ ] Pub/Sub DLQ subscription configured in Terraform (`max_delivery_attempts=5`)
- [ ] `LangChain` base agent class extracted as a shared library in `shared-libs/agent_base/`
- [ ] Performance test: task creation latency p95 <2 seconds under 50 concurrent ADT events
- [ ] Code reviewed and approved
