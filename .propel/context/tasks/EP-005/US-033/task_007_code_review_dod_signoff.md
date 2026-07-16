---
id: TASK-007
title: "Code Review and Definition of Done Sign-off — US-033"
user_story: US-033
epic: EP-005
sprint: 2
layer: Quality Assurance
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: Backend Engineer
upstream: [US-033/TASK-001, US-033/TASK-002, US-033/TASK-003, US-033/TASK-004, US-033/TASK-005, US-033/TASK-006]
---

# TASK-007: Code Review and Definition of Done Sign-off — US-033

> **Story:** US-033 | **Epic:** EP-005 | **Sprint:** 2 | **Layer:** Quality Assurance | **Est:** 1 h  
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

This task verifies that all six implementation tasks for US-033 satisfy the Definition of Done, pass a structured code review against project standards, and are ready for sprint demo. No new code is written — this is a review and validation gate.

**Design references:**
- US-033 Definition of Done checklist
- design.md — security, HIPAA, logging, RBAC, PHI standards
- `.github/instructions/` — security-standards-owasp, backend-development-standards, code-documentation-standards

---

## Review Checklist

### Functional Completeness

- [ ] `MedicationSummaryGenerator` class exists and accepts a reconciliation result dict
- [ ] Gemini Flash model used: `gemini-1.5-flash` (not Pro)
- [ ] Prompt instructs plain language at 6th-grade reading level
- [ ] Output validated against `MedicationSummaryOutput` Pydantic schema
- [ ] Output schema contains all four keys: `new`, `stopped`, `changed`, `continued`
- [ ] Brand name lookup uses RxNav `getDisplayTerms` (BN synonym endpoint)
- [ ] Brand name Redis cache key: `drug-brand:{rxcui}`, TTL = 604 800 s (7 days)
- [ ] `medications_section` written to `document` table as JSONB
- [ ] Translation triggered only when `patient.preferred_language != "en"` and not `None`
- [ ] Translation stored under `Document.translations.{lang_code}`
- [ ] US-027 `TranslationService` reused — no duplicate Gemini translation logic

### Code Quality

- [ ] All new modules have module-level docstrings with `Design refs` pointing to US-033 AC Scenarios and design.md sections
- [ ] No magic strings — model name, TTL, key prefix use named constants
- [ ] No silent exception swallowing — `RxNavBrandNameError` logged at WARNING; `ValueError` from Gemini logged at ERROR
- [ ] No N+1 queries — single `SELECT` + single `flush()` per document write
- [ ] HTTP clients use `timeout` parameter on all RxNav calls
- [ ] `model_copy(update=...)` used in translator (Pydantic v2 — not `copy(update=...)`)

### Security (OWASP / HIPAA)

- [ ] No PHI in Redis cache keys or values — only RxCUI strings and brand name text
- [ ] No PHI in `medications_section` beyond drug names and instructions (no patient identifiers)
- [ ] Drug names are **not** PHI — no encryption applied to brand name cache
- [ ] `document.medications_section` JSONB column does not store patient identifiers
- [ ] No RxNav API key in source code — RxNav is a public API requiring no authentication

### DRY Compliance

- [ ] `get_redis` dependency factory from US-031 TASK-001 reused — no new Redis client factory created
- [ ] Translation logic exclusively from US-027 `TranslationService` — no new Gemini translation prompt duplicated
- [ ] `BrandNameCache` pattern mirrors `DrugInteractionCache` structure — no redundant cache wrapper logic

### Test Coverage

- [ ] `test_all_reconciliation_categories_present` → PASS
- [ ] `test_brand_name_enrichment_called_for_all_medications` → PASS
- [ ] `test_invalid_gemini_json_raises_value_error` → PASS
- [ ] `test_new_medication_has_required_fields` → PASS
- [ ] `test_cache_miss_calls_rxnav_and_stores_result` → PASS
- [ ] `test_cache_hit_suppresses_rxnav_call` → PASS
- [ ] `test_generic_drug_no_brand_returns_none` → PASS
- [ ] `test_rxnav_error_returns_none_gracefully` → PASS
- [ ] `test_write_persists_medications_section` → PASS
- [ ] `test_write_raises_for_unknown_document_id` → PASS
- [ ] `test_spanish_translation_translates_text_fields` → PASS
- [ ] `test_stopped_reason_translated_when_present` → PASS
- [ ] `test_translation_service_not_called_for_none_reason` → PASS

### Migration

- [ ] `alembic upgrade head` applied to dev environment without errors
- [ ] `alembic downgrade -1` tested and reverts `medications_section` column cleanly
- [ ] `document.medications_section` column present with JSONB type and correct comment

---

## Definition of Done — Final Sign-off

- [ ] All TASK-001 through TASK-006 items marked Done
- [ ] All 13 unit tests passing in CI with `pytest -v`
- [ ] Code reviewed and approved by at least one peer
- [ ] No `# TODO`, `# FIXME`, or `# HACK` comments left in submitted code
- [ ] Story US-033 status updated to `Done` in sprint board
