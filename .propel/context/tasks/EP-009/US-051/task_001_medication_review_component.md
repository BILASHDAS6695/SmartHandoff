---
id: TASK-001
title: "Implement `MedicationReviewComponent` — Three-Column MatTable with Severity Badges"
user_story: US-051
epic: EP-009
sprint: 2
layer: Frontend — Feature Component
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-072, UI-005, US-030]
---

# TASK-001: Implement `MedicationReviewComponent` — Three-Column MatTable with Severity Badges

> **Story:** US-051 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Feature Component | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

Pharmacist Phil navigates to `/patients/{id}/medications` and expects a three-column reconciliation view showing Pre-Admit, Inpatient, and Discharge medication columns side-by-side. Each drug row must display drug name, dose, frequency, and a severity badge for any detected interactions. The severity badge reuses the existing `<app-risk-badge>` component (from US-049) with a `severity` variant so no new badge component is created (DRY).

This is the primary view for the pharmacist role and must load within the Angular lazy-loaded `medications` feature module.

---

## Acceptance Criteria Addressed

| US-051 AC | Requirement |
|---|---|
| **Scenario 1** | Three columns: "Pre-Admit", "Inpatient", "Discharge"; each drug row shows name, dose, frequency, severity badge (RED=HIGH, YELLOW=MEDIUM, GREY=none) |

---

## Implementation Steps

### 1. Define Data Models in `features/medications/models/`

**`medication-row.model.ts`**

```typescript
/**
 * Represents a single medication row in the reconciliation view.
 * Populated from the Medication Reconciliation API (US-030).
 */
export interface MedicationRow {
  /** Unique medication identifier from FHIR MedicationRequest.id */
  id: string;
  drugName: string;
  dose: string;
  frequency: string;
  /** Interaction severity for this drug. Null when no interaction detected. */
  interactionSeverity: InteractionSeverity | null;
  /** ID of the interaction alert, used to open resolution modal */
  alertId: string | null;
}

export type InteractionSeverity = 'HIGH' | 'MEDIUM' | 'LOW' | null;

/**
 * Three-panel reconciliation payload from GET /api/v1/patients/{id}/medications/reconciliation.
 */
export interface MedicationReconciliation {
  encounterId: string;
  preAdmit: MedicationRow[];
  inpatient: MedicationRow[];
  discharge: MedicationRow[];
}
```

### 2. Create `MedicationReviewComponent` in `features/medications/components/medication-review/`

**`medication-review.component.ts`**

```typescript
import {
  Component, OnInit, Input, ChangeDetectionStrategy, signal, inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MedicationApiService } from '../../services/medication-api.service';
import { MedicationReconciliation, MedicationRow } from '../../models/medication-row.model';
import { RiskBadgeComponent } from '../../../../shared/components/risk-badge/risk-badge.component';

/**
 * Three-panel medication reconciliation table for the pharmacist role.
 * Displays Pre-Admit / Inpatient / Discharge columns side-by-side.
 * Reuses <app-risk-badge> with severity input for interaction badges.
 *
 * Route: /patients/:patientId/medications
 */
@Component({
  selector: 'app-medication-review',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatProgressSpinnerModule,
    MatButtonModule,
    MatIconModule,
    RiskBadgeComponent,
  ],
  templateUrl: './medication-review.component.html',
  styleUrls: ['./medication-review.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MedicationReviewComponent implements OnInit {
  @Input({ required: true }) patientId!: string;

  private readonly medicationApi = inject(MedicationApiService);

  readonly displayedColumns = ['drugName', 'dose', 'frequency', 'severity'];

  reconciliation = signal<MedicationReconciliation | null>(null);
  isLoading = signal(true);
  hasError = signal(false);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading.set(true);
    this.hasError.set(false);
    this.medicationApi.getReconciliation(this.patientId).subscribe({
      next: (data) => {
        this.reconciliation.set(data);
        this.isLoading.set(false);
      },
      error: () => {
        this.hasError.set(true);
        this.isLoading.set(false);
      },
    });
  }

  /** Emits alertId upward so parent can open AlertResolutionModal */
  onBadgeClick(row: MedicationRow): void {
    if (row.alertId) {
      // Handled via output or router event — wired in TASK-003
    }
  }
}
```

**`medication-review.component.html`**

```html
<!-- Loading state -->
<div *ngIf="isLoading()" class="med-review__loading" aria-busy="true" aria-label="Loading medication reconciliation">
  <mat-spinner diameter="40"></mat-spinner>
</div>

<!-- Error state -->
<div *ngIf="hasError() && !isLoading()" class="med-review__error" role="alert">
  <mat-icon aria-hidden="true">error_outline</mat-icon>
  <span>Failed to load medication reconciliation data.</span>
  <button mat-stroked-button color="warn" (click)="load()">Retry</button>
</div>

<!-- Three-panel reconciliation table -->
<ng-container *ngIf="reconciliation() as rec">
  <div class="med-review__panels">

    <!-- Pre-Admit Panel -->
    <section class="med-review__panel" aria-labelledby="pre-admit-heading">
      <h2 id="pre-admit-heading" class="med-review__panel-title">Pre-Admit</h2>
      <table mat-table [dataSource]="rec.preAdmit" class="med-review__table" aria-label="Pre-Admit medications">
        <ng-container matColumnDef="drugName">
          <th mat-header-cell *matHeaderCellDef>Drug</th>
          <td mat-cell *matCellDef="let row">{{ row.drugName }}</td>
        </ng-container>
        <ng-container matColumnDef="dose">
          <th mat-header-cell *matHeaderCellDef>Dose</th>
          <td mat-cell *matCellDef="let row">{{ row.dose }}</td>
        </ng-container>
        <ng-container matColumnDef="frequency">
          <th mat-header-cell *matHeaderCellDef>Frequency</th>
          <td mat-cell *matCellDef="let row">{{ row.frequency }}</td>
        </ng-container>
        <ng-container matColumnDef="severity">
          <th mat-header-cell *matHeaderCellDef>Interaction</th>
          <td mat-cell *matCellDef="let row">
            <app-risk-badge
              *ngIf="row.interactionSeverity"
              [tier]="row.interactionSeverity"
              [attr.aria-label]="row.interactionSeverity + ' severity interaction'"
              (click)="onBadgeClick(row)"
              style="cursor: pointer"
            />
            <span *ngIf="!row.interactionSeverity" class="med-review__no-interaction" aria-label="No interaction detected">—</span>
          </td>
        </ng-container>
        <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
        <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
      </table>
    </section>

    <!-- Inpatient Panel -->
    <section class="med-review__panel" aria-labelledby="inpatient-heading">
      <h2 id="inpatient-heading" class="med-review__panel-title">Inpatient</h2>
      <table mat-table [dataSource]="rec.inpatient" class="med-review__table" aria-label="Inpatient medications">
        <ng-container matColumnDef="drugName">
          <th mat-header-cell *matHeaderCellDef>Drug</th>
          <td mat-cell *matCellDef="let row">{{ row.drugName }}</td>
        </ng-container>
        <ng-container matColumnDef="dose">
          <th mat-header-cell *matHeaderCellDef>Dose</th>
          <td mat-cell *matCellDef="let row">{{ row.dose }}</td>
        </ng-container>
        <ng-container matColumnDef="frequency">
          <th mat-header-cell *matHeaderCellDef>Frequency</th>
          <td mat-cell *matCellDef="let row">{{ row.frequency }}</td>
        </ng-container>
        <ng-container matColumnDef="severity">
          <th mat-header-cell *matHeaderCellDef>Interaction</th>
          <td mat-cell *matCellDef="let row">
            <app-risk-badge
              *ngIf="row.interactionSeverity"
              [tier]="row.interactionSeverity"
              (click)="onBadgeClick(row)"
              style="cursor: pointer"
            />
            <span *ngIf="!row.interactionSeverity" class="med-review__no-interaction" aria-label="No interaction detected">—</span>
          </td>
        </ng-container>
        <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
        <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
      </table>
    </section>

    <!-- Discharge Panel -->
    <section class="med-review__panel" aria-labelledby="discharge-heading">
      <h2 id="discharge-heading" class="med-review__panel-title">Discharge</h2>
      <table mat-table [dataSource]="rec.discharge" class="med-review__table" aria-label="Discharge medications">
        <ng-container matColumnDef="drugName">
          <th mat-header-cell *matHeaderCellDef>Drug</th>
          <td mat-cell *matCellDef="let row">{{ row.drugName }}</td>
        </ng-container>
        <ng-container matColumnDef="dose">
          <th mat-header-cell *matHeaderCellDef>Dose</th>
          <td mat-cell *matCellDef="let row">{{ row.dose }}</td>
        </ng-container>
        <ng-container matColumnDef="frequency">
          <th mat-header-cell *matHeaderCellDef>Frequency</th>
          <td mat-cell *matCellDef="let row">{{ row.frequency }}</td>
        </ng-container>
        <ng-container matColumnDef="severity">
          <th mat-header-cell *matHeaderCellDef>Interaction</th>
          <td mat-cell *matCellDef="let row">
            <app-risk-badge
              *ngIf="row.interactionSeverity"
              [tier]="row.interactionSeverity"
              (click)="onBadgeClick(row)"
              style="cursor: pointer"
            />
            <span *ngIf="!row.interactionSeverity" class="med-review__no-interaction" aria-label="No interaction detected">—</span>
          </td>
        </ng-container>
        <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
        <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
      </table>
    </section>

  </div>
</ng-container>
```

**`medication-review.component.scss`**

```scss
.med-review {
  &__loading,
  &__error {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 24px;
    justify-content: center;
  }

  &__panels {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    padding: 16px;

    @media (max-width: 960px) {
      grid-template-columns: 1fr;
    }
  }

  &__panel {
    border: 1px solid var(--mat-divider-color);
    border-radius: 8px;
    overflow: hidden;
  }

  &__panel-title {
    font-size: 14px;
    font-weight: 600;
    padding: 12px 16px;
    margin: 0;
    background: var(--mat-table-header-container-height);
    border-bottom: 1px solid var(--mat-divider-color);
  }

  &__table {
    width: 100%;
  }

  &__no-interaction {
    color: var(--mat-sys-outline);
  }
}
```

### 3. Register Route in `medications` Feature Module

In `features/medications/medications.routes.ts`:

```typescript
import { Routes } from '@angular/router';

export const MEDICATION_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./components/medication-review/medication-review.component').then(
        (m) => m.MedicationReviewComponent
      ),
  },
];
```

In `app.routes.ts` (already established by US-047):

```typescript
{
  path: 'patients/:patientId/medications',
  loadChildren: () =>
    import('./features/medications/medications.routes').then((m) => m.MEDICATION_ROUTES),
  canActivate: [AuthGuard, RoleGuard],
  data: { roles: ['pharmacist', 'physician'] },
},
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| CREATE | `src/app/features/medications/models/medication-row.model.ts` |
| CREATE | `src/app/features/medications/components/medication-review/medication-review.component.ts` |
| CREATE | `src/app/features/medications/components/medication-review/medication-review.component.html` |
| CREATE | `src/app/features/medications/components/medication-review/medication-review.component.scss` |
| CREATE | `src/app/features/medications/medications.routes.ts` |
| MODIFY | `src/app/app.routes.ts` — add medications lazy route with role guard |

---

## Validation Checklist

- [ ] Three columns render with correct headings: "Pre-Admit", "Inpatient", "Discharge"
- [ ] Each row displays drug name, dose, frequency
- [ ] `<app-risk-badge>` renders for rows with `interactionSeverity` set; dash renders when null
- [ ] Badge click triggers `onBadgeClick()` with non-null `alertId`
- [ ] Loading spinner renders while API in flight
- [ ] Error state with Retry button renders on API failure
- [ ] Route is accessible only to `pharmacist` and `physician` roles
- [ ] Grid collapses to single column on screens < 960px
- [ ] No `console.error` in browser during normal load

---

## Dependencies

| Dependency | Notes |
|---|---|
| TASK-002 (this story) | `MedicationApiService` must exist before component wires up |
| US-047 | Angular scaffold, `app.routes.ts`, `AuthGuard`, `RoleGuard` |
| US-049 | `RiskBadgeComponent` already implemented — import directly |
| US-030 | Medication Reconciliation API endpoint operational |
