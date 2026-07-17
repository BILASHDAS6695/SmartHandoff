---
id: TASK-003
title: "Implement `AlertResolutionModalComponent` — MatDialog with Resolution Controls"
user_story: US-051
epic: EP-009
sprint: 2
layer: Frontend — Feature Component
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-072, US-031]
---

# TASK-003: Implement `AlertResolutionModalComponent` — MatDialog with Resolution Controls

> **Story:** US-051 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Feature Component | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

When a pharmacist clicks a HIGH or MEDIUM severity badge in `MedicationReviewComponent`, a `MatDialog` modal opens showing the drug pair, RxNav interaction description (first 200 characters with "Read more" toggle), severity, and four resolution options via `MatRadioGroup`. On submit the alert status updates in real time (badge clears, `alert_resolved` SignalR event consumed), and a toast notification confirms completion.

This modal is opened programmatically via `MatDialog.open()` from `MedicationReviewComponent` — it does not have its own route.

---

## Acceptance Criteria Addressed

| US-051 AC | Requirement |
|---|---|
| **Scenario 2** | Modal shows drug pair, description, severity; resolution options (REVIEWED_ACCEPTABLE / DOSE_ADJUSTED / DRUG_CHANGED / DISCONTINUED); on submit badge clears and status updates in real time |

---

## Implementation Steps

### 1. Create `AlertResolutionModalComponent` in `features/medications/components/alert-resolution-modal/`

**`alert-resolution-modal.component.ts`**

```typescript
import {
  Component, OnInit, Inject, ChangeDetectionStrategy, signal, inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import {
  MatDialogRef,
  MAT_DIALOG_DATA,
  MatDialogModule,
} from '@angular/material/dialog';
import { MatRadioModule } from '@angular/material/radio';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { InteractionAlertApiService } from '../../services/interaction-alert-api.service';
import {
  InteractionAlert,
  AlertResolutionType,
} from '../../models/interaction-alert.model';

export interface AlertResolutionModalData {
  alertId: string;
}

/**
 * Modal dialog for resolving a drug interaction alert.
 * Opened by MedicationReviewComponent when a severity badge is clicked.
 *
 * On successful submission:
 *  - Calls PATCH /api/v1/alerts/{alertId}/resolve
 *  - Closes dialog with resolved alert payload (used by parent to clear badge)
 *  - Parent shows toast: "Alert resolved — medication review complete"
 */
@Component({
  selector: 'app-alert-resolution-modal',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatRadioModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './alert-resolution-modal.component.html',
  styleUrls: ['./alert-resolution-modal.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AlertResolutionModalComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly alertApi = inject(InteractionAlertApiService);
  private readonly dialogRef = inject<MatDialogRef<AlertResolutionModalComponent>>(MatDialogRef);

  readonly resolutionOptions: { value: AlertResolutionType; label: string }[] = [
    { value: 'REVIEWED_ACCEPTABLE', label: 'Reviewed — Acceptable Risk' },
    { value: 'DOSE_ADJUSTED', label: 'Dose Adjusted' },
    { value: 'DRUG_CHANGED', label: 'Drug Changed' },
    { value: 'DISCONTINUED', label: 'Discontinued' },
  ];

  alert = signal<InteractionAlert | null>(null);
  isLoading = signal(true);
  isSubmitting = signal(false);
  hasError = signal(false);
  descriptionExpanded = signal(false);

  readonly form = this.fb.group({
    resolutionType: this.fb.control<AlertResolutionType | null>(null, Validators.required),
    note: this.fb.control<string>('', Validators.maxLength(500)),
  });

  constructor(
    @Inject(MAT_DIALOG_DATA) readonly data: AlertResolutionModalData
  ) {}

  ngOnInit(): void {
    this.alertApi.getAlert(this.data.alertId).subscribe({
      next: (alert) => {
        this.alert.set(alert);
        this.isLoading.set(false);
      },
      error: () => {
        this.hasError.set(true);
        this.isLoading.set(false);
      },
    });
  }

  get descriptionText(): string {
    const full = this.alert()?.descriptionFull ?? '';
    if (this.descriptionExpanded()) return full;
    return this.alert()?.descriptionExcerpt ?? full.slice(0, 200);
  }

  get showReadMore(): boolean {
    return (this.alert()?.descriptionFull?.length ?? 0) > 200 && !this.descriptionExpanded();
  }

  toggleDescription(): void {
    this.descriptionExpanded.update((v) => !v);
  }

  onSubmit(): void {
    if (this.form.invalid || this.isSubmitting()) return;

    this.isSubmitting.set(true);
    const { resolutionType, note } = this.form.getRawValue();

    this.alertApi
      .resolveAlert(this.data.alertId, {
        resolutionType: resolutionType!,
        note: note || undefined,
      })
      .subscribe({
        next: (resolved) => {
          this.dialogRef.close(resolved);
        },
        error: () => {
          this.isSubmitting.set(false);
          this.hasError.set(true);
        },
      });
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }
}
```

**`alert-resolution-modal.component.html`**

```html
<h2 mat-dialog-title id="alert-modal-title">Resolve Drug Interaction Alert</h2>

<mat-dialog-content aria-labelledby="alert-modal-title">

  <!-- Loading -->
  <div *ngIf="isLoading()" class="alert-modal__loading" aria-busy="true">
    <mat-spinner diameter="32"></mat-spinner>
    <span>Loading alert details…</span>
  </div>

  <!-- Error state -->
  <div *ngIf="hasError() && !isLoading()" role="alert" class="alert-modal__error">
    <span>Failed to load alert details. Please close and try again.</span>
  </div>

  <!-- Alert detail -->
  <ng-container *ngIf="alert() as a">
    <div class="alert-modal__detail">
      <p class="alert-modal__drug-pair">
        <strong>{{ a.drug1Name }}</strong> ↔ <strong>{{ a.drug2Name }}</strong>
      </p>
      <p class="alert-modal__severity" [attr.data-severity]="a.severity">
        Severity: <strong>{{ a.severity }}</strong>
      </p>
      <div class="alert-modal__description">
        <p>{{ descriptionText }}</p>
        <button
          *ngIf="showReadMore"
          mat-button
          type="button"
          (click)="toggleDescription()"
          aria-expanded="false"
        >
          Read more
        </button>
        <button
          *ngIf="descriptionExpanded()"
          mat-button
          type="button"
          (click)="toggleDescription()"
          aria-expanded="true"
        >
          Show less
        </button>
      </div>
    </div>

    <!-- Resolution form -->
    <form [formGroup]="form" (ngSubmit)="onSubmit()" id="resolution-form">
      <mat-radio-group
        formControlName="resolutionType"
        aria-label="Select resolution type"
        class="alert-modal__radio-group"
      >
        <mat-radio-button
          *ngFor="let option of resolutionOptions"
          [value]="option.value"
        >
          {{ option.label }}
        </mat-radio-button>
      </mat-radio-group>

      <mat-error *ngIf="form.get('resolutionType')?.touched && form.get('resolutionType')?.hasError('required')">
        Please select a resolution type.
      </mat-error>

      <mat-form-field appearance="outline" class="alert-modal__note-field">
        <mat-label>Clinician Note (optional)</mat-label>
        <textarea
          matInput
          formControlName="note"
          rows="3"
          maxlength="500"
          aria-label="Add a clinician note for this resolution"
          placeholder="Add context or rationale…"
        ></textarea>
        <mat-hint align="end">{{ form.get('note')?.value?.length ?? 0 }}/500</mat-hint>
      </mat-form-field>
    </form>
  </ng-container>

</mat-dialog-content>

<mat-dialog-actions align="end">
  <button mat-button type="button" (click)="onCancel()" [disabled]="isSubmitting()">
    Cancel
  </button>
  <button
    mat-raised-button
    color="primary"
    type="submit"
    form="resolution-form"
    [disabled]="form.invalid || isSubmitting()"
    aria-label="Submit alert resolution"
  >
    <mat-spinner *ngIf="isSubmitting()" diameter="16" class="alert-modal__btn-spinner"></mat-spinner>
    <span *ngIf="!isSubmitting()">Resolve Alert</span>
  </button>
</mat-dialog-actions>
```

**`alert-resolution-modal.component.scss`**

```scss
.alert-modal {
  &__loading {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 0;
  }

  &__error {
    color: var(--mat-sys-error);
    padding: 8px 0;
  }

  &__drug-pair {
    font-size: 16px;
    margin-bottom: 8px;
  }

  &__severity {
    margin-bottom: 12px;

    &[data-severity='HIGH'] strong { color: var(--color-risk-high); }
    &[data-severity='MEDIUM'] strong { color: var(--color-risk-medium); }
    &[data-severity='LOW'] strong { color: var(--color-risk-low); }
  }

  &__description {
    background: var(--mat-sys-surface-variant);
    border-radius: 4px;
    padding: 12px;
    margin-bottom: 16px;
    font-size: 14px;
    line-height: 1.5;
  }

  &__radio-group {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 16px;
  }

  &__note-field {
    width: 100%;
  }

  &__btn-spinner {
    display: inline-block;
    vertical-align: middle;
  }
}
```

### 2. Wire Modal Opening in `MedicationReviewComponent`

Add to `medication-review.component.ts` (extends TASK-001):

```typescript
import { MatDialog } from '@angular/material/dialog';
import { AlertResolutionModalComponent } from '../alert-resolution-modal/alert-resolution-modal.component';
import { ToastService } from '../../../../core/services/toast.service';

// Inject in the class body:
private readonly dialog = inject(MatDialog);
private readonly toast = inject(ToastService);

onBadgeClick(row: MedicationRow): void {
  if (!row.alertId) return;

  const ref = this.dialog.open(AlertResolutionModalComponent, {
    width: '560px',
    data: { alertId: row.alertId },
    disableClose: true,
    ariaLabel: 'Resolve drug interaction alert',
  });

  ref.afterClosed().subscribe((resolved) => {
    if (resolved) {
      // Clear badge on the resolved row
      const rec = this.reconciliation();
      if (!rec) return;
      const clearBadge = (rows: MedicationRow[]) =>
        rows.map((r) =>
          r.alertId === resolved.alertId
            ? { ...r, interactionSeverity: null, alertId: null }
            : r
        );
      this.reconciliation.set({
        ...rec,
        preAdmit: clearBadge(rec.preAdmit),
        inpatient: clearBadge(rec.inpatient),
        discharge: clearBadge(rec.discharge),
      });
      this.toast.show('Alert resolved — medication review complete', 'success');
    }
  });
}
```

---

## Files to Create / Modify

| Action | File |
|--------|------|
| CREATE | `src/app/features/medications/components/alert-resolution-modal/alert-resolution-modal.component.ts` |
| CREATE | `src/app/features/medications/components/alert-resolution-modal/alert-resolution-modal.component.html` |
| CREATE | `src/app/features/medications/components/alert-resolution-modal/alert-resolution-modal.component.scss` |
| MODIFY | `src/app/features/medications/components/medication-review/medication-review.component.ts` — add `MatDialog` open logic |

---

## Validation Checklist

- [ ] Modal opens when severity badge with non-null `alertId` is clicked
- [ ] Drug pair names, description excerpt, and severity render correctly
- [ ] "Read more" button expands full description; "Show less" collapses it
- [ ] Four `MatRadioButton` options render: REVIEWED_ACCEPTABLE, DOSE_ADJUSTED, DRUG_CHANGED, DISCONTINUED
- [ ] Clinician note textarea enforces 500-character limit with live counter
- [ ] Submit button disabled until a resolution type is selected
- [ ] On success: dialog closes, badge clears on the resolved row, toast fires with correct message
- [ ] On API error: error message shown inline; dialog remains open for retry
- [ ] Cancel button closes dialog without changes
- [ ] `disableClose: true` prevents accidental dismissal via backdrop click
- [ ] Modal is keyboard-navigable and focus-trapped (Angular Material default)

---

## Dependencies

| Dependency | Notes |
|---|---|
| TASK-001 (this story) | `MedicationReviewComponent` must exist to trigger modal |
| TASK-002 (this story) | `InteractionAlertApiService` required |
| US-048 | `ToastService` established in core services |
