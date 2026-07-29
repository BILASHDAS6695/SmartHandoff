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
import { ToastService } from '../../../../core/notifications/toast.service';
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
  private readonly toastService = inject(ToastService);
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
          this.toastService.success('Alert resolved — medication review complete');
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
