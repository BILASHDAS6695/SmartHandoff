---
id: TASK-004
title: "Analytics Filter Bar — MatDateRangePicker, Unit Dropdown & URL Query Param Sync"
user_story: US-061
epic: EP-012
sprint: 2
layer: Frontend / Component
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-061/TASK-003]
---

# TASK-004: Analytics Filter Bar — MatDateRangePicker, Unit Dropdown & URL Query Param Sync

> **Story:** US-061 | **Epic:** EP-012 | **Sprint:** 2 | **Layer:** Frontend / Component | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-061 DoD requires:
- `MatDateRangePicker` as the date filter control
- Unit filter dropdown populated from the manager's accessible units (`app_user.units` — available in the JWT claims)
- Filter state reflected as URL query params `?from=&to=&unit=` so links are shareable and browser back/forward works
- All 5 charts update simultaneously within 2 seconds when any filter changes (AC Scenario 2)

This task implements `AnalyticsFilterBarComponent`, a standalone Angular component that:
1. Renders a reactive form with `MatDateRangePicker` (start/end) and a `MatSelect` unit dropdown
2. Pre-fills from URL query params on init (passed in as `@Input` from the shell)
3. Emits a `(filterChange)` output event that the `AnalyticsComponent` shell handles by updating URL params (triggering chart refresh via `route.queryParams`)
4. Fetches available unit options from the current user's JWT claims via `AuthService`

**Design references:**
- design.md §3.4 — `features/analytics/` — Angular Material components
- design.md §4.1 — Angular Material 17; `MatDateRangePicker`
- US-061 DoD — `MatDateRangePicker`; URL query params `?from=&to=&unit=`; unit dropdown from `app_user.units`
- US-061 AC Scenario 2 — all charts update within 2 s when filter applied

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Date range picker pre-set to last 30 days on initial navigation to `/analytics` |
| Scenario 2 | Applying a new filter emits `filterChange`, shell updates URL params, `kpiData$` re-fetches within 2 s |

---

## Implementation Steps

### 1. Create component files

```bash
touch smarthandoff-angular/src/app/features/analytics/filter-bar/analytics-filter-bar.component.ts
touch smarthandoff-angular/src/app/features/analytics/filter-bar/analytics-filter-bar.component.html
touch smarthandoff-angular/src/app/features/analytics/filter-bar/analytics-filter-bar.component.scss
```

### 2. Implement `AnalyticsFilterBarComponent`

```typescript
/**
 * Standalone filter bar for the analytics dashboard.
 *
 * Inputs:
 *   initialFilters — current filter state (from URL query params or defaults)
 *   availableUnits — unit options from app_user.units (JWT claims)
 *
 * Outputs:
 *   filterChange — emits KpiFilterParams when the manager submits new filter values
 *
 * Design refs:
 *   US-061 DoD — MatDateRangePicker; unit dropdown; URL query params
 *   US-061 AC Scenario 1 — pre-set to last 30 days
 *   US-061 AC Scenario 2 — simultaneous chart update on filter apply
 */
import { Component, EventEmitter, Input, OnInit, Output, inject } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatNativeDateModule } from '@angular/material/core';
import { MatSelectModule } from '@angular/material/select';

import { KpiFilterParams } from '../analytics.models';

@Component({
  selector: 'app-analytics-filter-bar',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatDatepickerModule,
    MatNativeDateModule,
    MatSelectModule,
    MatButtonModule,
  ],
  templateUrl: './analytics-filter-bar.component.html',
  styleUrl: './analytics-filter-bar.component.scss',
})
export class AnalyticsFilterBarComponent implements OnInit {
  @Input() initialFilters!: KpiFilterParams;
  /** Units the manager can access — derived from app_user.units in the JWT. */
  @Input() availableUnits: string[] = [];

  @Output() filterChange = new EventEmitter<KpiFilterParams>();

  private readonly fb = inject(FormBuilder);

  filterForm!: FormGroup;

  ngOnInit(): void {
    this.filterForm = this.fb.group({
      dateRange: this.fb.group({
        start: [this.parseDate(this.initialFilters.from), Validators.required],
        end: [this.parseDate(this.initialFilters.to), Validators.required],
      }),
      unit: [this.initialFilters.unit ?? null],
    });
  }

  /** Emit the current filter values as KpiFilterParams. */
  applyFilter(): void {
    if (this.filterForm.invalid) return;

    const { dateRange, unit } = this.filterForm.value;
    const filters: KpiFilterParams = {
      from: this.formatDate(dateRange.start),
      to: this.formatDate(dateRange.end),
      unit: unit ?? undefined,
    };
    this.filterChange.emit(filters);
  }

  private parseDate(iso: string): Date {
    return new Date(iso);
  }

  private formatDate(date: Date): string {
    return date.toISOString().split('T')[0];
  }
}
```

### 3. Create `analytics-filter-bar.component.html`

```html
<!--
  Filter bar template for the analytics dashboard.

  Accessibility:
    - Form has role="search" with aria-label identifying it as the KPI filter form
    - Date range group has aria-label for screen reader context
    - Apply button has aria-label
  Design refs:
    US-061 DoD — MatDateRangePicker; unit dropdown; URL query params
    web-accessibility-standards — WCAG 2.2 Level AA; keyboard navigation
-->
<form
  [formGroup]="filterForm"
  (ngSubmit)="applyFilter()"
  role="search"
  aria-label="KPI dashboard filter controls"
  class="filter-bar"
>
  <mat-form-field appearance="outline" class="date-range-field">
    <mat-label>Date range</mat-label>
    <mat-date-range-input
      [rangePicker]="rangePicker"
      formGroupName="dateRange"
      aria-label="Date range for KPI data"
    >
      <input matStartDate formControlName="start" placeholder="Start date" aria-label="Start date" />
      <input matEndDate formControlName="end" placeholder="End date" aria-label="End date" />
    </mat-date-range-input>
    <mat-hint>MM/DD/YYYY – MM/DD/YYYY</mat-hint>
    <mat-datepicker-toggle matIconSuffix [for]="rangePicker" aria-label="Open date range picker" />
    <mat-date-range-picker #rangePicker />
  </mat-form-field>

  <mat-form-field appearance="outline" class="unit-field">
    <mat-label>Unit</mat-label>
    <mat-select formControlName="unit" aria-label="Filter by hospital unit">
      <mat-option [value]="null">All units</mat-option>
      @for (unit of availableUnits; track unit) {
        <mat-option [value]="unit">{{ unit }}</mat-option>
      }
    </mat-select>
  </mat-form-field>

  <button
    mat-flat-button
    color="primary"
    type="submit"
    [disabled]="filterForm.invalid"
    aria-label="Apply KPI dashboard filters"
  >
    Apply
  </button>
</form>
```

### 4. Create `analytics-filter-bar.component.scss`

```scss
// Filter bar layout — horizontal flex, responsive wrap for narrow viewports
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: flex-start;
  padding: 1rem 0;
}

.date-range-field {
  min-width: 280px;
  flex: 1 1 280px;
}

.unit-field {
  min-width: 180px;
  flex: 0 1 180px;
}
```

### 5. Expose `availableUnits` from the shell component

In `AnalyticsComponent` (`analytics.component.ts`), inject `AuthService` to read the manager's units from the decoded JWT, then pass them to the filter bar:

```typescript
// Add to AnalyticsComponent
import { AuthService } from '@core/auth/auth.service';

export class AnalyticsComponent implements OnInit {
  // … existing properties …
  private readonly authService = inject(AuthService);

  readonly availableUnits = this.authService.currentUser()?.units ?? [];
}
```

### 6. Wire the filter bar into `analytics.component.html`

Replace the `<!-- app-analytics-filter-bar composed here in TASK-004 -->` placeholder:

```html
<app-analytics-filter-bar
  [initialFilters]="initialFilters"
  [availableUnits]="availableUnits"
  (filterChange)="onFilterChange($event)"
/>
```

Also expose `initialFilters` as a property initialised from defaults on the shell:

```typescript
// In AnalyticsComponent.ngOnInit(), after reading route.queryParams snapshot:
initialFilters: KpiFilterParams = (() => {
  const params = this.route.snapshot.queryParams;
  const defaults = this.apiService.defaultFilters();
  return {
    from: params['from'] ?? defaults.from,
    to: params['to'] ?? defaults.to,
    unit: params['unit'] ?? undefined,
  };
})();
```

---

## Validation Checklist

- [ ] Date range picker renders with start/end pre-filled from URL query params (or 30-day default)
- [ ] Unit dropdown lists all units from `availableUnits` input; first option is "All units" (null value)
- [ ] Clicking "Apply" emits `filterChange` with correctly formatted ISO date strings
- [ ] Invalid date range (end before start) keeps the Apply button disabled
- [ ] `filterChange` event triggers `router.navigate` in the shell, updating URL query params without full navigation
- [ ] WCAG 2.2 Level AA: all form controls have `aria-label`; keyboard tab order is logical
- [ ] Snapshot `initialFilters` prevents the date picker re-setting to defaults when charts re-render on `kpiData$` emission

---

## Files Created / Modified

| File | Action |
|------|--------|
| `smarthandoff-angular/src/app/features/analytics/filter-bar/analytics-filter-bar.component.ts` | Create |
| `smarthandoff-angular/src/app/features/analytics/filter-bar/analytics-filter-bar.component.html` | Create |
| `smarthandoff-angular/src/app/features/analytics/filter-bar/analytics-filter-bar.component.scss` | Create |
| `smarthandoff-angular/src/app/features/analytics/analytics.component.ts` | Modify — inject `AuthService`, expose `availableUnits` and `initialFilters` |
| `smarthandoff-angular/src/app/features/analytics/analytics.component.html` | Modify — add `<app-analytics-filter-bar>` |
