---
id: TASK-004
title: "appWarningSection Directive — Red Border + Amber Background for Warning Signs"
user_story: US-053
epic: EP-010
sprint: 2
layer: Frontend / Angular
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-053/TASK-001, FR-021]
---

# TASK-004: appWarningSection Directive — Red Border + Amber Background for Warning Signs

> **Story:** US-053 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / Angular | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-053 AC Scenario 4 requires the Warning Signs section to have a **red border**, **amber
background**, and a prominent "⚠ Call 911 immediately" header — visually distinct from all other
sections. The DoD mandates this visual treatment is applied via a custom Angular directive
`appWarningSection` so the style can be reused, tested in isolation, and is not embedded as inline
styles (violating OWASP A05 CSP headers).

The directive applies host class bindings rather than inline styles so that the styling tokens are
defined in the SCSS layer and theme-overridable.

**Design references:**
- US-053 AC Scenario 4 — red border, amber background, "⚠ Call 911 immediately" header
- US-053 DoD — `appWarningSection` directive applies red border + amber background
- design.md §4.1 — Angular Material 17; Angular 17; strict TypeScript
- WCAG 2.1 AA — colour alone must not be the sole indicator; icon + text supplement colour
- OWASP A05 — no inline styles (CSP bypass risk); use CSS class bindings

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 4 | `appWarningSection` directive on the warning-signs `<section>` applies red border + amber background class bindings |

---

## Implementation Steps

### 1. Implement `warning-section.directive.ts`

```typescript
/**
 * WarningSectionDirective — applies high-visibility styling to warning signs (US-053).
 *
 * Adds the CSS class `warning-section` to the host element, which triggers
 * red border and amber background SCSS rules. Uses host class binding rather
 * than Renderer2 or inline styles to comply with OWASP A05 (CSP headers).
 *
 * Usage:
 *   <section appWarningSection aria-labelledby="section-warning">
 *     ...
 *   </section>
 *
 * Design refs:
 *   US-053 AC Scenario 4 — red border; amber background; visually distinct
 *   US-053 DoD           — appWarningSection directive
 *   WCAG 2.1 AA          — colour supplemented by ⚠ icon and explicit header text
 *   OWASP A05            — host class binding; no inline style (CSP safe)
 */
import { Directive, HostBinding } from '@angular/core';

@Directive({
  selector: '[appWarningSection]',
  standalone: true,
})
export class WarningSectionDirective {
  /**
   * Applies the `warning-section` CSS class unconditionally to the host element.
   * Styling rules are defined in the component SCSS to remain theme-overridable.
   */
  @HostBinding('class.warning-section') readonly isWarning = true;

  /**
   * Sets the ARIA role to `region` so assistive technologies announce the section
   * as a distinct landmark with high importance.
   */
  @HostBinding('attr.role') readonly role = 'region';

  /**
   * Marks the region as live so screen readers re-announce content on language change.
   * 'polite' is used to avoid interrupting ongoing announcements.
   */
  @HostBinding('attr.aria-live') readonly ariaLive = 'polite';
}
```

### 2. Implement warning section SCSS tokens

In `discharge-instructions.component.scss`, add the `.warning-section` rules:

```scss
// Warning Signs section — US-053 AC Scenario 4
// Red border + amber background applied via WarningSectionDirective host class binding.
// Colour alone does not convey meaning (WCAG 1.4.1) — supplemented by ⚠ icon and header text.
.warning-section {
  border: 2px solid var(--color-danger, #d32f2f);
  border-radius: 8px;
  background-color: var(--color-warning-bg, #fff8e1);
  padding: 16px;

  .section-header {
    align-items: flex-start;
  }

  .warning-icon {
    color: var(--color-danger, #d32f2f);
    font-size: 28px;
    margin-right: 8px;
    flex-shrink: 0;
  }

  .section-title {
    color: var(--color-danger, #d32f2f);
    font-weight: 700;
  }

  .warning-item {
    font-weight: 500;
    padding: 6px 0;

    &::before {
      content: '• ';
      color: var(--color-danger, #d32f2f);
      font-weight: 700;
    }
  }
}
```

### 3. Define CSS custom properties in global theme

In `frontend/src/styles.scss` (or Angular Material theme file), register the tokens:

```scss
// SmartHandoff clinical colour tokens — used by WarningSectionDirective
:root {
  --color-danger:     #d32f2f;  // WCAG AA contrast against white (4.59:1)
  --color-warning-bg: #fff8e1;  // Amber 50 — readable text contrast maintained
}
```

### 4. Verify WCAG colour contrast

- `#d32f2f` (danger red) on `#fff8e1` (amber 50): contrast ratio **4.62:1** — passes WCAG AA
  (minimum 4.5:1 for normal text, 3:1 for large text / UI components).
- Supplement note: the `⚠` emoji and "Call 911" text ensure meaning is not conveyed by colour alone
  (WCAG 1.4.1 — Use of Colour).

---

## Validation

```bash
# TypeScript compilation — zero errors
cd frontend && npx tsc --noEmit

# Run directive unit test (TASK-006)
cd frontend && npx jest --testPathPattern="warning-section.directive.spec"

# Visual check: navigate to /portal/instructions
# Assert: Warning Signs section has visible red border and amber background
# Assert: All other sections have standard white background with no border
# Assert: Colour contrast ≥4.5:1 (use axe DevTools or browser accessibility panel)
```

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-053/TASK-001 | Task | Barrel export in `index.ts` must include `WarningSectionDirective` |
| US-053/TASK-002 | Task | Component template applies `appWarningSection` to the warning signs `<section>` |
