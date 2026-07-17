---
id: TASK-005
title: "Mobile-First SCSS Layout — Single-Column Stacked Sections below 768px"
user_story: US-053
epic: EP-010
sprint: 2
layer: Frontend / Angular
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-053/TASK-002, US-053/TASK-004]
---

# TASK-005: Mobile-First SCSS Layout — Single-Column Stacked Sections below 768px

> **Story:** US-053 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / Angular | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-053 AC Scenario 3 specifies that on a **375 px viewport** (iPhone SE / Android compact) the
five sections must be clearly demarcated and stacked in a single column. The DoD additionally
mandates touch targets ≥ 44 px for the language switcher and all interactive elements.

This task completes the `discharge-instructions.component.scss` with the full responsive layout
and ensures compliance with NFR-033 (mobile-first), NFR-034 (Angular Material WCAG AA), and
US-053 DoD accessibility requirements.

**Design references:**
- US-053 AC Scenario 3 — 375 px viewport; single-column stacked layout; section demarcation
- US-053 DoD — touch target ≥44 px; mobile-first responsive; single-column below 768 px
- design.md §4.1 — NFR-033 mobile-first; NFR-034 WCAG 2.1 AA
- NFR-001 — <2 s page load: CSS must not block rendering (no @import from CDN)

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 3 | 375 px viewport: sections single-column stacked; icons and headings clearly demarcated |

---

## Implementation Steps

### 1. Complete `discharge-instructions.component.scss`

```scss
// Discharge Instructions Component — US-053 mobile-first responsive layout
// Design refs:
//   US-053 AC Scenario 3 — 375 px single-column stacked layout
//   US-053 DoD           — touch targets ≥44 px; mobile-first below 768 px
//   NFR-033              — mobile-first approach; primary patient devices: iOS/Android
//   NFR-034              — Angular Material WCAG 2.1 AA baseline

// ─── Breakpoints ────────────────────────────────────────────────────────────
$bp-mobile: 375px;
$bp-tablet: 768px;

// ─── Page container ─────────────────────────────────────────────────────────
.instructions-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 16px;
  font-family: var(--mat-body-font-family, Roboto, sans-serif);

  // Loading / error states centred
  .loading-container {
    display: flex;
    justify-content: center;
    padding: 48px 0;
  }

  .error-banner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    border-radius: 4px;
    background-color: #fdecea;
    color: #b71c1c;
    margin-bottom: 16px;
  }
}

// ─── Page header + language switcher ────────────────────────────────────────
.instructions-header {
  display: flex;
  flex-direction: column;        // Stack on mobile
  gap: 12px;
  margin-bottom: 24px;

  @media (min-width: $bp-tablet) {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

.instructions-title {
  font-size: 1.5rem;
  font-weight: 700;
  margin: 0;
  color: var(--mat-text-primary, rgba(0 0 0 / 87%));

  @media (max-width: $bp-mobile) {
    font-size: 1.25rem;
  }
}

// Language switcher — touch targets ≥44 px (US-053 DoD; WCAG 2.5.5)
.language-switcher {
  align-self: flex-start;

  ::ng-deep .mat-button-toggle {
    min-width: 44px;
    min-height: 44px;
    line-height: 44px;
    font-weight: 600;
    font-size: 0.875rem;
  }

  ::ng-deep .mat-button-toggle-checked {
    background-color: var(--mat-primary-500, #1976d2);
    color: #ffffff;
  }
}

// ─── Sections container — single-column stack on mobile ─────────────────────
.sections-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

// ─── Individual section card ─────────────────────────────────────────────────
.instruction-section {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid rgba(0 0 0 / 12%);
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0 0 0 / 10%);

  // Section header row: icon + heading side by side
  .section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;

    mat-icon {
      color: var(--mat-primary-500, #1976d2);
      font-size: 24px;
      width: 24px;
      height: 24px;
      flex-shrink: 0;
    }
  }

  .section-title {
    font-size: 1.125rem;
    font-weight: 600;
    margin: 0;
    color: var(--mat-text-primary, rgba(0 0 0 / 87%));

    @media (max-width: $bp-mobile) {
      font-size: 1rem;
    }
  }

  mat-divider {
    margin-bottom: 12px;
  }

  .section-body {
    font-size: 1rem;
    line-height: 1.6;
    color: var(--mat-text-secondary, rgba(0 0 0 / 60%));
    margin: 0;
  }
}

// ─── Medication list ──────────────────────────────────────────────────────────
.medication-list {
  list-style: none;
  padding: 0;
  margin: 0;

  .medication-item {
    padding: 8px 0;
    border-bottom: 1px solid rgba(0 0 0 / 6%);
    font-size: 0.9375rem;
    line-height: 1.5;

    &:last-child {
      border-bottom: none;
    }

    .med-notes {
      display: block;
      font-size: 0.875rem;
      color: var(--mat-text-hint, rgba(0 0 0 / 38%));
      margin-top: 2px;
    }
  }
}

// ─── Follow-up appointment list ──────────────────────────────────────────────
.followup-list {
  list-style: none;
  padding: 0;
  margin: 0;

  .followup-item {
    padding: 8px 0;
    font-size: 0.9375rem;
    border-bottom: 1px solid rgba(0 0 0 / 6%);

    &:last-child {
      border-bottom: none;
    }

    .followup-contact {
      display: block;
      font-size: 0.875rem;
      color: var(--mat-primary-500, #1976d2);
      margin-top: 2px;
    }
  }
}

// ─── Warning list ────────────────────────────────────────────────────────────
.warning-list {
  list-style: none;
  padding: 0;
  margin: 0;

  .warning-item {
    padding: 6px 0;
    font-size: 0.9375rem;
    font-weight: 500;
    line-height: 1.5;

    &::before {
      content: '• ';
      color: var(--color-danger, #d32f2f);
      font-weight: 700;
    }
  }
}

// ─── Warning section overrides (applied by WarningSectionDirective) ──────────
// Rules defined in TASK-004 are referenced here for completeness.
// .warning-section rules live in this file alongside general section styles.
```

### 2. Verify 375 px layout manually

Test on physical devices per US-053 DoD:

| Device | Browser | Viewport | Expected |
|---|---|---|---|
| iPhone SE (3rd gen) | iOS Safari 16+ | 375 × 667 | Single-column; all 5 sections visible; no horizontal scroll |
| Pixel 6a | Android Chrome 120+ | 360 × 800 | Single-column; language switcher below title |
| iPad (landscape) | Safari | 1024 × 768 | Two-column optional OR single-column max-width centred |

---

## Validation

```bash
# Lighthouse mobile audit (no install required via Chrome DevTools)
# Target: Performance ≥90, Accessibility ≥95 on mobile preset

# axe DevTools browser extension
# Navigate to http://localhost:4200/portal/instructions
# Run accessibility scan — expect 0 violations

# Chrome DevTools → Device toolbar → iPhone SE (375px)
# Assert: sections stacked vertically, no overflow, icons visible
# Assert: language switcher buttons ≥44px tap targets (DevTools ruler)
```

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-053/TASK-002 | Task | Component HTML structure must exist before SCSS can be validated |
| US-053/TASK-004 | Task | `.warning-section` rules extend the base `.instruction-section` rules in this file |
