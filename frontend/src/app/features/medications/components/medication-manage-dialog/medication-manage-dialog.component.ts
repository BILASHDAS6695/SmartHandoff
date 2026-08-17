import { Component, inject, signal, computed, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import {
  MedicationApiService,
  MedicationCreateRequest,
  MedicationReconciliationResult,
  MedicationUpdateRequest,
} from '../../services/medication-api.service';
import { ToastService } from '../../../../core/notifications/toast.service';

export interface MedicationManageDialogData {
  encounterId: string;
  patientName?: string;
  medication?: MedicationReconciliationResult | null;
}

/**
 * Dialog to add or edit a medication for an encounter.
 *
 * Opened from the physician dashboard "Physician Reviews" card and from the
 * patient detail Medications tab.
 */
@Component({
  selector: 'app-medication-manage-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './medication-manage-dialog.component.html',
  styleUrls: ['./medication-manage-dialog.component.scss'],
})
export class MedicationManageDialogComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly medicationApi = inject(MedicationApiService);
  private readonly dialogRef = inject(MatDialogRef<MedicationManageDialogComponent>);
  private readonly toast = inject(ToastService);
  readonly data: MedicationManageDialogData = inject(MAT_DIALOG_DATA);

  readonly isSaving = signal(false);

  readonly isEdit = computed(() => !!this.data.medication);
  readonly dialogTitle = computed(() =>
    this.isEdit() ? 'Edit Medication' : 'Add Medication',
  );

  form!: FormGroup;

  readonly categories: Array<{
    value: 'CONTINUED' | 'NEW' | 'STOPPED' | 'DOSE_CHANGED';
    label: string;
  }> = [
    { value: 'CONTINUED', label: 'Continued' },
    { value: 'NEW', label: 'New' },
    { value: 'STOPPED', label: 'Stopped' },
    { value: 'DOSE_CHANGED', label: 'Dose Changed' },
  ];

  readonly severities: Array<{
    value: 'HIGH' | 'MEDIUM' | 'LOW';
    label: string;
  }> = [
    { value: 'HIGH', label: 'High' },
    { value: 'MEDIUM', label: 'Medium' },
    { value: 'LOW', label: 'Low' },
  ];

  ngOnInit(): void {
    const med = this.data.medication;
    this.form = this.fb.group({
      name: [med?.name ?? '', [Validators.required, Validators.maxLength(255)]],
      rxnorm_cui: [med?.rxnorm_cui ?? ''],
      dose: [med?.dose ?? ''],
      route: [med?.route ?? ''],
      frequency: [med?.frequency ?? ''],
      pre_admit: [med?.pre_admit ?? false],
      inpatient: [med?.inpatient ?? false],
      discharge: [med?.discharge ?? false],
      reconciliation_category: [med?.reconciliation_category ?? ''],
      interaction_severity: [med?.interaction_severity ?? ''],
    });
  }

  onCancel(): void {
    this.dialogRef.close();
  }

  onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    this.isSaving.set(true);
    const raw = this.form.value;
    const payload = {
      ...raw,
      reconciliation_category: raw.reconciliation_category || null,
      interaction_severity: raw.interaction_severity || null,
    };

    if (this.isEdit() && this.data.medication) {
      const updatePayload: MedicationUpdateRequest = payload;
      this.medicationApi
        .updateMedication(this.data.medication.id, updatePayload)
        .subscribe({
          next: (medication) => {
            this.isSaving.set(false);
            this.toast.success('Medication updated');
            this.dialogRef.close({ action: 'updated', medication });
          },
          error: (err: Error) => {
            this.isSaving.set(false);
            this.toast.error(err.message ?? 'Failed to update medication');
          },
        });
    } else {
      const createPayload: MedicationCreateRequest = {
        ...payload,
        encounter_id: this.data.encounterId,
      };
      this.medicationApi.createMedication(createPayload).subscribe({
        next: (medication) => {
          this.isSaving.set(false);
          this.toast.success('Medication added');
          this.dialogRef.close({ action: 'created', medication });
        },
        error: (err: Error) => {
          this.isSaving.set(false);
          this.toast.error(err.message ?? 'Failed to add medication');
        },
      });
    }
  }
}
