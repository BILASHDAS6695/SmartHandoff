---
id: TASK-007
title: "Code Review & DoD Sign-Off — US-053 Discharge Instructions with Language Switcher"
user_story: US-053
epic: EP-010
sprint: 2
layer: Review / QA
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-053/TASK-001, US-053/TASK-002, US-053/TASK-003, US-053/TASK-004, US-053/TASK-005, US-053/TASK-006]
---

# TASK-007: Code Review & DoD Sign-Off — US-053 Discharge Instructions with Language Switcher

> **Story:** US-053 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Review / QA | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This is the gate task for US-053. It verifies that all implementation tasks (TASK-001 through
TASK-006) are complete, the Definition of Done is satisfied, and the work is ready for pull
request review and merge.

A second engineer reviews all changes before this task is marked Done.

---

## Definition of Done Checklist

### Component

- [ ] `DischargeInstructionsComponent` renders five sections (medications, activity, diet, follow-up, warning signs) mapped from `Document.translations` JSONB
- [ ] Component declared `standalone: true` with `ChangeDetectionStrategy.OnPush`
- [ ] HTTP call uses `takeUntilDestroyed()` — no subscription leaks
- [ ] On HTTP error: error message displayed in a `role="alert"` container
- [ ] On HTTP loading: `<mat-spinner>` displayed with `aria-busy="true"`
- [ ] Component registered at `/portal/instructions` route in patient-portal routing module

### Language Switcher

- [ ] `LanguageSwitcherService` injected with component-scoped `providers: [LanguageSwitcherService]`
- [ ] `activeLanguage` is a writable `signal<SupportedLanguage>` initialised from JWT `preferred_language` claim
- [ ] `currentContent` is a `computed` signal derived from `translations[activeLanguage()] ?? translations['en']`
- [ ] Language switch requires zero new HTTP calls — pure signal reactivity
- [ ] `MatButtonToggle` group renders only languages present in `Document.translations`
- [ ] Active language button visually distinct (background + colour change)
- [ ] Language switcher `aria-label="Select language for discharge instructions"` set

### Section Icons

- [ ] Angular Material `mat-icon` used for all five sections
- [ ] Icons: `medication` (medications), `directions_walk` (activity), `restaurant` (diet), `calendar_today` (follow-up), `warning` (warning signs)
- [ ] All `mat-icon` elements have `aria-hidden="true"` (decorative; heading text provides label)

### Warning Signs Directive

- [ ] `WarningSectionDirective` (`appWarningSection`) applied to warning signs `<section>`
- [ ] Host class binding `warning-section` applied via `@HostBinding` (no inline styles)
- [ ] `role="region"` and `aria-live="polite"` set on warning section host
- [ ] `.warning-section` SCSS rule applies: red border (`#d32f2f`), amber background (`#fff8e1`)
- [ ] Colour contrast ≥ 4.5:1 for all text within warning section (WCAG 1.4.3)
- [ ] Colour not the sole indicator of meaning (icon + "⚠ Call 911" text present — WCAG 1.4.1)

### Mobile / Responsive

- [ ] Single-column stacked layout below 768 px — no horizontal scroll at 375 px
- [ ] All interactive elements (language switcher toggle buttons) have touch target ≥ 44 × 44 px
- [ ] Page tested on iOS Safari 16+ (iPhone SE 375 px) and Android Chrome 120+ (Pixel 360 px)

### Accessibility

- [ ] `axe-core` WCAG 2.1 AA scan in unit tests: **0 violations**
- [ ] All `<section>` elements have `aria-labelledby` referencing heading `id`
- [ ] Page `<main>` has `aria-labelledby="instructions-heading"`
- [ ] No colour-only communication of state (WCAG 1.4.1)
- [ ] Keyboard navigation: language toggle buttons focusable and operable with Enter/Space

### Tests

- [ ] All unit tests pass: `npx jest --testPathPattern="discharge-instructions|language-switcher|warning-section"`
- [ ] `LanguageSwitcherService` spec: 5 tests — init, switch, fallback to EN, unsupported lang, available languages
- [ ] `WarningSectionDirective` spec: 3 tests — class binding, role, aria-live
- [ ] `DischargeInstructionsComponent` spec: 5 tests — section count, French content on load, warning class, icons, axe-core

### Code Quality

- [ ] TypeScript strict mode: `npx tsc --noEmit` exits 0
- [ ] No `any` type usage in component, service, or directive files
- [ ] No `BehaviorSubject` or `Subject` — Signals only for reactive state (US-053 Technical Notes)
- [ ] No PHI logged in console or network requests (discharge content is PHI)
- [ ] Barrel `index.ts` exports component, service, directive, and types

---

## Review Checklist (Reviewer)

- [ ] Component uses `ChangeDetectionStrategy.OnPush` — no unnecessary re-renders
- [ ] `LanguageSwitcherService` provided at component level (not root) — no cross-portal state leak
- [ ] Warning section SCSS uses CSS custom properties (not hardcoded hex) for theme-overridability
- [ ] `takeUntilDestroyed()` used for HTTP subscription — no `ngOnDestroy` boilerplate
- [ ] `MatButtonToggle` `(change)` handler calls service `switchLanguage` — template does not mutate signal directly
- [ ] `axe-core` test imports and runs in Angular `TestBed` context — not against static HTML
- [ ] No `::ng-deep` overuse — only used for Angular Material component internals where scoped SCSS is insufficient

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-053/TASK-001 through TASK-006 | Tasks | All implementation tasks must be complete before sign-off |
