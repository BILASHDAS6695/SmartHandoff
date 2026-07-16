---
id: US-033-tasks-index
title: "Task Index — US-033: Generate Patient-Readable Medication Change Summary"
user_story: US-033
epic: EP-005
sprint: 2
status: Draft
date: 2026-07-16
---

# Task Index — US-033: Generate Patient-Readable Medication Change Summary

> **Epic:** EP-005 — Medication Reconciliation Agent | **Sprint:** 2 | **Story Points:** 3  
> **Status:** Draft | **Date:** 2026-07-16

---

## Summary

Breaks down US-033 into 7 implementation tasks across Backend (AI/ML), Integration, Testing, and QA layers. The story delivers a `MedicationSummaryGenerator` that converts reconciliation results into a plain-language patient summary, enriched with RxNav brand names, stored in the `document` table, and translated via the EP-004 pipeline.

---

## Task Breakdown

| Task | Title | Layer | Est | Upstream |
|------|-------|-------|-----|----------|
| [TASK-001](task_001_brand_name_cache_rxnav_client.md) | Brand Name Redis Cache Layer + RxNav `getDisplayTerms` Client | Backend | 3 h | US-001 |
| [TASK-002](task_002_medication_summary_pydantic_schema.md) | Medication Summary Pydantic Output Schema | Backend | 1 h | — |
| [TASK-003](task_003_medication_summary_generator.md) | `MedicationSummaryGenerator` Class + Gemini Flash Prompt | Backend / AI | 4 h | TASK-001, TASK-002, US-030 |
| [TASK-004](task_004_document_storage_integration.md) | Document Storage Integration — `medications_section` in Patient Instructions | Backend | 2 h | TASK-003 |
| [TASK-005](task_005_translation_pipeline_integration.md) | Translation Pipeline Integration — Reuse US-027 | Backend / AI | 2 h | TASK-003, US-027 |
| [TASK-006](task_006_unit_tests_medication_summary.md) | Unit Tests — Summary Generator: All Categories, Brand Name Enrichment, Translation | Testing | 3 h | TASK-001, TASK-002, TASK-003, TASK-004, TASK-005 |
| [TASK-007](task_007_code_review_dod_signoff.md) | Code Review and Definition of Done Sign-off — US-033 | Quality Assurance | 1 h | All |

**Total Estimate:** 16 h (2 dev-days)

---

## Dependency Graph

```
US-030 (reconciliation result)
    └── TASK-001 (brand name cache + RxNav client)
        └── TASK-002 (Pydantic schema)
            └── TASK-003 (MedicationSummaryGenerator + Gemini Flash)
                ├── TASK-004 (document storage)
                ├── TASK-005 (translation — reuses US-027)
                └── TASK-006 (unit tests)
                    └── TASK-007 (code review / DoD)
```

---

## AC → Task Traceability

| AC Scenario | Task(s) |
|-------------|---------|
| Scenario 1 — Plain-English summary with new/stopped/changed sections | TASK-003 |
| Scenario 2 — Medical terms replaced with brand names + plain descriptions | TASK-001, TASK-003 |
| Scenario 3 — Summary stored in `Document.medications_section` | TASK-004 |
| Scenario 4 — Spanish translation via EP-004 pipeline | TASK-005 |
