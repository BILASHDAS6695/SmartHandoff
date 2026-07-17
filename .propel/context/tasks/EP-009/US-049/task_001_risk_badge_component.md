---
id: TASK-001
title: "Implement Standalone `RiskBadgeComponent` with WCAG 2.1 AA Colour Tokens"
user_story: US-049
epic: EP-009
sprint: 2
layer: Frontend — Shared Component
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-071, NFR-034, UI-004]
---

# TASK-001: Implement Standalone `RiskBadgeComponent` with WCAG 2.1 AA Colour Tokens

> **Story:** US-049 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Shared Component | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

The patient list (US-049) and any future encounter-facing screen requires a single reusable risk badge. The badge must display `HIGH`, `MEDIUM`, `LOW`, and `UNSCORED` risk tiers with colour-coded CSS variables and meet WCAG 2.1 AA contrast ratios. As a standalone Angular component, it has no NgModule dependency and can be imported directly into feature components.

This component is the canonical risk tier display mechanism — it must NOT be re-implemented elsewhere in the codebase (DRY principle).

---

## Acceptance Criteria Addressed

| US-049 AC | Requirement |
|---|---|
| **Scenario 2** | `HIGH` → red badge, `MEDIUM` → yellow badge, `LOW` → green badge, `UNSCORED` → grey badge; WCAG 2.1 AA contrast |

---

## Implementation Steps

### 1. Define `RiskTier` Enum in `shared/models/risk-tier.enum.ts`

```typescript
/**
 * Risk stratification tiers as produced by the Follow-up Care Agent
 * (FR-052). Maps directly to the `risk_tier` field on the Encounter API
 * response. All display logic for this enum lives exclusively in RiskBadgeComponent.
 */
export enum RiskTier {
  HIGH = 'HIGH',
  MEDIUM = 'MEDIUM',
  LOW = 'LOW',
  UNSCORED = 'UNSCORED',
}
```

### 2. Create `RiskBadgeComponent` in `shared/components/risk-badge/`

**`risk-badge.component.ts`**

```typescript
import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RiskTier } from '../../models/risk-tier.enum';

/**
 * Displays a colour-coded risk tier badge.
 *
 * Usage: <app-risk-badge [tier]="encounter.risk_tier" />
 *
 * Colours are mapped via CSS custom properties defined in risk-badge.component.scss.
 * All four tiers meet WCAG 2.1 AA contrast ratio (≥4.5:1 for normal text).
 */
@Component({
  selector: 'app-risk-badge',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './risk-badge.component.html',
  styleUrls: ['./risk-badge.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskBadgeComponent {
  /** Risk tier value from encounter payload. Defaults to UNSCORED when absent. */
  @Input() tier: RiskTier | string = RiskTier.UNSCORED;

  readonly RiskTier = RiskTier;

  get badgeClass(): string {
    const map: Record<string, string> = {
      [RiskTier.HIGH]: 'risk-badge--high',
      [RiskTier.MEDIUM]: 'risk-badge--medium',
      [RiskTier.LOW]: 'risk-badge--low',
      [RiskTier.UNSCORED]: 'risk-badge--unscored',
    };
    return map[this.tier] ?? 'risk-badge--unscored';
  }

  get ariaLabel(): string {
    const labels: Record<string, string> = {
      [RiskTier.HIGH]: 'High risk',
      [RiskTier.MEDIUM]: 'Medium risk',
      [RiskTier.LOW]: 'Low risk',
      [RiskTier.UNSCORED]: 'Risk not scored',
    };
    return labels[this.tier] ?? 'Risk not scored';
  }
}
```

**`risk-badge.component.html`**

```html
<span
  class="risk-badge"
  [ngClass]="badgeClass"
  [attr.aria-label]="ariaLabel"
  role="img"
>
  {{ tier }}
</span>
```

**`risk-badge.component.scss`**

```scss
// CSS custom properties defined in global styles; declared here as fallbacks.
:host {
  --risk-high: #b71c1c;
  --risk-high-text: #ffffff;
  --risk-medium: #f57f17;
  --risk-medium-text: #000000;
  --risk-low: #1b5e20;
  --risk-low-text: #ffffff;
  --risk-unknown: #616161;
  --risk-unknown-text: #ffffff;
}

.risk-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  line-height: 1.6;

  &--high {
    background-color: var(--risk-high);
    color: var(--risk-high-text);
  }

  &--medium {
    background-color: var(--risk-medium);
    color: var(--risk-medium-text);
  }

  &--low {
    background-color: var(--risk-low);
    color: var(--risk-low-text);
  }

  &--unscored {
    background-color: var(--risk-unknown);
    color: var(--risk-unknown-text);
  }
}
```

### 3. Unit Tests — `risk-badge.component.spec.ts`

```typescript
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { RiskBadgeComponent } from './risk-badge.component';
import { RiskTier } from '../../models/risk-tier.enum';

describe('RiskBadgeComponent', () => {
  let fixture: ComponentFixture<RiskBadgeComponent>;
  let component: RiskBadgeComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RiskBadgeComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(RiskBadgeComponent);
    component = fixture.componentInstance;
  });

  it('should render HIGH badge with correct CSS class and aria-label', () => {
    component.tier = RiskTier.HIGH;
    fixture.detectChanges();
    const span: HTMLElement = fixture.nativeElement.querySelector('.risk-badge');
    expect(span.classList).toContain('risk-badge--high');
    expect(span.getAttribute('aria-label')).toBe('High risk');
  });

  it('should render MEDIUM badge with correct CSS class', () => {
    component.tier = RiskTier.MEDIUM;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.risk-badge--medium')).toBeTruthy();
  });

  it('should render LOW badge with correct CSS class', () => {
    component.tier = RiskTier.LOW;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.risk-badge--low')).toBeTruthy();
  });

  it('should default to UNSCORED badge for unknown tier', () => {
    component.tier = 'UNKNOWN_VALUE';
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.risk-badge--unscored')).toBeTruthy();
    expect(component.ariaLabel).toBe('Risk not scored');
  });
});
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `frontend/src/app/shared/models/risk-tier.enum.ts` |
| **Create** | `frontend/src/app/shared/components/risk-badge/risk-badge.component.ts` |
| **Create** | `frontend/src/app/shared/components/risk-badge/risk-badge.component.html` |
| **Create** | `frontend/src/app/shared/components/risk-badge/risk-badge.component.scss` |
| **Create** | `frontend/src/app/shared/components/risk-badge/risk-badge.component.spec.ts` |
| **Update** | `frontend/src/app/shared/components/index.ts` — re-export `RiskBadgeComponent` |

---

## Definition of Done

- [ ] `RiskBadgeComponent` is standalone (no NgModule dependency)
- [ ] All four tiers render with correct CSS classes and `aria-label` attributes
- [ ] CSS custom properties match `--risk-high: #B71C1C`, `--risk-medium: #F57F17`, `--risk-low: #1B5E20`, `--risk-unknown: #616161`
- [ ] `role="img"` and `aria-label` present on badge span for screen-reader accessibility
- [ ] All 4 unit tests pass (`ng test --include=**/risk-badge.component.spec.ts`)
- [ ] Component exported from `shared/components/index.ts` for DRY reuse

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-047 | Story | Angular project scaffold with Angular Material must exist |
| Angular Material 17 | Library | Already required by US-047; no additional dependency needed |
