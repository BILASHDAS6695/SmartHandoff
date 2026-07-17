---
id: TASK-003
title: "Build `PatientListComponent` with MatTable, Virtual Scroll, Skeleton Loaders, and RBAC Unit Filter"
user_story: US-049
epic: EP-009
sprint: 2
layer: Frontend — Feature Component
estimate: 5h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-071, FR-074, UI-004]
---

# TASK-003: Build `PatientListComponent` with MatTable, Virtual Scroll, Skeleton Loaders, and RBAC Unit Filter

> **Story:** US-049 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Feature Component | **Est:** 5 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

`PatientListComponent` is the primary view for floor nurses at `/patients`. It renders a `MatTable` with CDK Virtual Scroll for lists exceeding 50 rows, a debounced 300 ms search input, a unit filter dropdown populated from the nurse's JWT `units[]` claim, `MatPaginator` at 25 rows per page, skeleton loaders during async fetch, and an error state with retry button. Risk badges are delegated entirely to `RiskBadgeComponent` (TASK-001). JWT claim extraction is delegated to `AuthService` from US-047.

---

## Acceptance Criteria Addressed

| US-049 AC | Requirement |
|---|---|
| **Scenario 1** | Unit filter defaults to nurse's primary unit from JWT; API call always includes `unit` param |
| **Scenario 2** | Risk badge rendered via `<app-risk-badge [tier]="row.risk_tier">` |
| **Scenario 4** | Search input debounced 300 ms; skeleton loaders shown during loading state |

---

## Implementation Steps

### 1. Component Scaffold — `patient-list.component.ts`

```typescript
import {
  Component,
  OnInit,
  OnDestroy,
  inject,
  signal,
  computed,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { Router } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { ScrollingModule } from '@angular/cdk/scrolling';
import {
  Subject,
  debounceTime,
  distinctUntilChanged,
  switchMap,
  catchError,
  of,
  takeUntil,
  startWith,
  combineLatest,
} from 'rxjs';

import { RiskBadgeComponent } from '../../../shared/components/risk-badge/risk-badge.component';
import { PatientApiService } from '../services/patient-api.service';
import { PatientSummary } from '../models/patient.model';
import { AuthService } from '../../../core/auth/auth.service';

/** Columns displayed in MatTable */
const DISPLAYED_COLUMNS = [
  'risk_tier',
  'last_name',
  'first_name',
  'mrn_masked',
  'room_number',
  'admission_date',
  'actions',
];

@Component({
  selector: 'app-patient-list',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatInputModule,
    MatSelectModule,
    MatProgressBarModule,
    MatButtonModule,
    MatIconModule,
    ScrollingModule,
    RiskBadgeComponent,
  ],
  templateUrl: './patient-list.component.html',
  styleUrls: ['./patient-list.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PatientListComponent implements OnInit, OnDestroy {
  private readonly patientApi = inject(PatientApiService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly destroy$ = new Subject<void>();

  readonly displayedColumns = DISPLAYED_COLUMNS;

  // --- State signals ---
  readonly patients = signal<PatientSummary[]>([]);
  readonly totalCount = signal<number>(0);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);

  // --- Form controls ---
  readonly searchControl = new FormControl<string>('', { nonNullable: true });
  readonly unitControl = new FormControl<string>('', { nonNullable: true });

  /** Units available to this nurse from JWT claim */
  readonly availableUnits = signal<string[]>([]);

  currentPage = 0;
  pageSize = 25;

  /** True when >50 rows — enables CDK Virtual Scroll */
  readonly useVirtualScroll = computed(() => this.totalCount() > 50);

  ngOnInit(): void {
    const units = this.authService.getUnitClaims();
    this.availableUnits.set(units);
    this.unitControl.setValue(units[0] ?? '');

    combineLatest([
      this.searchControl.valueChanges.pipe(
        startWith(''),
        debounceTime(300),
        distinctUntilChanged(),
      ),
      this.unitControl.valueChanges.pipe(startWith(units[0] ?? '')),
    ])
      .pipe(
        takeUntil(this.destroy$),
        switchMap(([search, unit]) => {
          this.loading.set(true);
          this.error.set(null);
          this.currentPage = 0;
          return this.patientApi
            .getPatients({ unit, search, page: 1, page_size: this.pageSize })
            .pipe(
              catchError(err => {
                this.error.set('Failed to load patients. Please try again.');
                this.loading.set(false);
                return of(null);
              }),
            );
        }),
      )
      .subscribe(response => {
        if (response) {
          this.patients.set(response.items);
          this.totalCount.set(response.total);
        }
        this.loading.set(false);
      });
  }

  onPageChange(event: PageEvent): void {
    this.currentPage = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loading.set(true);
    this.error.set(null);

    this.patientApi
      .getPatients({
        unit: this.unitControl.value,
        search: this.searchControl.value,
        page: event.pageIndex + 1,
        page_size: event.pageSize,
      })
      .pipe(
        catchError(() => {
          this.error.set('Failed to load patients. Please try again.');
          this.loading.set(false);
          return of(null);
        }),
        takeUntil(this.destroy$),
      )
      .subscribe(response => {
        if (response) {
          this.patients.set(response.items);
          this.totalCount.set(response.total);
        }
        this.loading.set(false);
      });
  }

  retry(): void {
    this.searchControl.updateValueAndValidity({ emitEvent: true });
  }

  navigateToDetail(encounterId: string): void {
    this.router.navigate(['/patients', encounterId]);
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
```

### 2. Template — `patient-list.component.html`

```html
<div class="patient-list-container">
  <!-- Toolbar: search + unit filter -->
  <div class="patient-list__toolbar">
    <mat-form-field appearance="outline" class="search-field">
      <mat-label>Search patients</mat-label>
      <input
        matInput
        [formControl]="searchControl"
        placeholder="Last name, first name…"
        aria-label="Search patients by name"
        autocomplete="off"
      />
      <mat-icon matSuffix>search</mat-icon>
    </mat-form-field>

    <mat-form-field appearance="outline" class="unit-filter">
      <mat-label>Unit</mat-label>
      <mat-select [formControl]="unitControl" aria-label="Filter by unit">
        @for (unit of availableUnits(); track unit) {
          <mat-option [value]="unit">{{ unit }}</mat-option>
        }
      </mat-select>
    </mat-form-field>
  </div>

  <!-- Loading bar -->
  @if (loading()) {
    <mat-progress-bar mode="indeterminate" aria-label="Loading patients"></mat-progress-bar>
  }

  <!-- Skeleton loaders — shown while loading and no data yet -->
  @if (loading() && patients().length === 0) {
    <div class="skeleton-rows" aria-busy="true" aria-label="Loading patient list">
      @for (i of [1,2,3,4,5]; track i) {
        <div class="skeleton-row">
          <div class="skeleton skeleton--badge"></div>
          <div class="skeleton skeleton--text-wide"></div>
          <div class="skeleton skeleton--text-narrow"></div>
          <div class="skeleton skeleton--text-narrow"></div>
        </div>
      }
    </div>
  }

  <!-- Error state -->
  @if (error()) {
    <div class="patient-list__error" role="alert">
      <mat-icon color="warn">error_outline</mat-icon>
      <span>{{ error() }}</span>
      <button mat-stroked-button color="warn" (click)="retry()">
        <mat-icon>refresh</mat-icon> Retry
      </button>
    </div>
  }

  <!-- Data table -->
  @if (!loading() || patients().length > 0) {
    @if (!error()) {
      <table
        mat-table
        [dataSource]="patients()"
        class="patient-table"
        aria-label="Patient list"
      >
        <!-- Risk Tier Column -->
        <ng-container matColumnDef="risk_tier">
          <th mat-header-cell *matHeaderCellDef>Risk</th>
          <td mat-cell *matCellDef="let row">
            <app-risk-badge [tier]="row.risk_tier" />
          </td>
        </ng-container>

        <!-- Last Name Column -->
        <ng-container matColumnDef="last_name">
          <th mat-header-cell *matHeaderCellDef>Last Name</th>
          <td mat-cell *matCellDef="let row">{{ row.last_name }}</td>
        </ng-container>

        <!-- First Name Column -->
        <ng-container matColumnDef="first_name">
          <th mat-header-cell *matHeaderCellDef>First Name</th>
          <td mat-cell *matCellDef="let row">{{ row.first_name }}</td>
        </ng-container>

        <!-- MRN Column -->
        <ng-container matColumnDef="mrn_masked">
          <th mat-header-cell *matHeaderCellDef>MRN</th>
          <td mat-cell *matCellDef="let row">{{ row.mrn_masked }}</td>
        </ng-container>

        <!-- Room Column -->
        <ng-container matColumnDef="room_number">
          <th mat-header-cell *matHeaderCellDef>Room</th>
          <td mat-cell *matCellDef="let row">{{ row.room_number }}</td>
        </ng-container>

        <!-- Admission Date Column -->
        <ng-container matColumnDef="admission_date">
          <th mat-header-cell *matHeaderCellDef>Admitted</th>
          <td mat-cell *matCellDef="let row">
            {{ row.admission_date | date : 'MMM d, y' }}
          </td>
        </ng-container>

        <!-- Actions Column -->
        <ng-container matColumnDef="actions">
          <th mat-header-cell *matHeaderCellDef></th>
          <td mat-cell *matCellDef="let row">
            <button
              mat-icon-button
              color="primary"
              (click)="navigateToDetail(row.encounter_id)"
              [attr.aria-label]="'View details for ' + row.last_name + ', ' + row.first_name"
            >
              <mat-icon>chevron_right</mat-icon>
            </button>
          </td>
        </ng-container>

        <tr mat-header-row *matHeaderRowDef="displayedColumns; sticky: true"></tr>
        <tr
          mat-row
          *matRowDef="let row; columns: displayedColumns"
          class="patient-row"
          (click)="navigateToDetail(row.encounter_id)"
          (keyup.enter)="navigateToDetail(row.encounter_id)"
          tabindex="0"
          [attr.aria-label]="row.last_name + ' ' + row.first_name + ' risk ' + row.risk_tier"
        ></tr>

        <!-- No data row -->
        <tr class="mat-row" *matNoDataRow>
          <td class="mat-cell no-data-cell" [attr.colspan]="displayedColumns.length">
            No patients found for the selected unit and search criteria.
          </td>
        </tr>
      </table>

      <mat-paginator
        [length]="totalCount()"
        [pageSize]="pageSize"
        [pageSizeOptions]="[25, 50, 100]"
        (page)="onPageChange($event)"
        aria-label="Patient list pagination"
      ></mat-paginator>
    }
  }
</div>
```

### 3. Styles — `patient-list.component.scss`

```scss
.patient-list-container {
  padding: 16px;
  max-width: 1200px;
  margin: 0 auto;
}

.patient-list__toolbar {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 8px;

  .search-field {
    flex: 1 1 300px;
  }

  .unit-filter {
    flex: 0 1 160px;
  }
}

.patient-table {
  width: 100%;
}

.patient-row {
  cursor: pointer;

  &:hover {
    background-color: rgba(0, 0, 0, 0.04);
  }

  &:focus {
    outline: 2px solid #1976d2;
    outline-offset: -2px;
  }
}

.no-data-cell {
  padding: 32px;
  text-align: center;
  color: rgba(0, 0, 0, 0.54);
}

// --- Skeleton loader styles ---
.skeleton-rows {
  padding: 8px 0;
}

.skeleton-row {
  display: flex;
  gap: 16px;
  padding: 12px 16px;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.skeleton {
  background: linear-gradient(90deg, #e0e0e0 25%, #eeeeee 50%, #e0e0e0 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
  border-radius: 4px;

  &--badge {
    width: 70px;
    height: 22px;
    border-radius: 12px;
  }

  &--text-wide {
    width: 160px;
    height: 16px;
  }

  &--text-narrow {
    width: 80px;
    height: 16px;
  }
}

@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.patient-list__error {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background-color: #fff3e0;
  border: 1px solid #ffb300;
  border-radius: 4px;
  margin-bottom: 16px;
}
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `frontend/src/app/features/patients/components/patient-list/patient-list.component.ts` |
| **Create** | `frontend/src/app/features/patients/components/patient-list/patient-list.component.html` |
| **Create** | `frontend/src/app/features/patients/components/patient-list/patient-list.component.scss` |
| **Update** | `frontend/src/app/features/patients/patients.routes.ts` — add `{ path: '', component: PatientListComponent }` |

---

## Definition of Done

- [ ] `PatientListComponent` is standalone; imports `RiskBadgeComponent` directly
- [ ] Search input uses `debounceTime(300)` + `distinctUntilChanged()`; no direct API call per keystroke
- [ ] Unit dropdown populated from `AuthService.getUnitClaims()` — not hardcoded
- [ ] Skeleton loaders (5 rows) shown while `loading() === true && patients().length === 0`
- [ ] Error state with retry button shown on API failure; `role="alert"` on error container
- [ ] `MatPaginator` configured with `pageSize=25`, `pageSizeOptions=[25,50,100]`
- [ ] `*matNoDataRow` row displayed when result set is empty
- [ ] Table rows are keyboard-navigable (`tabindex="0"`, `keyup.enter` handler)
- [ ] Component destroyed cleanly: `takeUntil(destroy$)` prevents memory leaks

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `RiskBadgeComponent` must exist |
| TASK-002 | Task | `PatientApiService` must exist |
| US-047 | Story | `AuthService.getUnitClaims()` must expose `units[]` from decoded JWT |
| US-048 | Story | SignalR service consumed in TASK-004 (separate task) |
