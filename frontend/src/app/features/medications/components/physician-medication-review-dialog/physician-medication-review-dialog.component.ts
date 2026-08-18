import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import {
  MedicationApiService,
  MedicationReconciliationResult,
} from '../../services/medication-api.service';
import { PhysicianAlertsApiService } from '../../../../core/api/physician-alerts-api.service';
import { PhysicianAlert } from '../../../../core/models/physician-alert.model';
import { ToastService } from '../../../../core/notifications/toast.service';
import { MedicationManageDialogComponent } from '../medication-manage-dialog/medication-manage-dialog.component';

export interface PhysicianMedicationReviewDialogData {
  alert: PhysicianAlert;
  patientName: string;
}

type EncounterStage = 'PRE_ADMIT' | 'INPATIENT' | 'DISCHARGE';

@Component({
  selector: 'app-physician-medication-review-dialog',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule,
    MatDialogModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './physician-medication-review-dialog.component.html',
  styleUrls: ['./physician-medication-review-dialog.component.scss'],
})
export class PhysicianMedicationReviewDialogComponent implements OnInit {
  private readonly medicationApi = inject(MedicationApiService);
  private readonly physicianAlertsApi = inject(PhysicianAlertsApiService);
  private readonly dialogRef = inject(MatDialogRef<PhysicianMedicationReviewDialogComponent>);
  private readonly dialog = inject(MatDialog);
  private readonly toast = inject(ToastService);
  readonly data: PhysicianMedicationReviewDialogData = inject(MAT_DIALOG_DATA);

  readonly medications = signal<MedicationReconciliationResult[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly approvingStage = signal<EncounterStage | null>(null);
  readonly stageOptions: ReadonlyArray<{ value: EncounterStage; label: string }> = [
    { value: 'PRE_ADMIT', label: 'Pre-admit' },
    { value: 'INPATIENT', label: 'Inpatient' },
    { value: 'DISCHARGE', label: 'Discharge' },
  ];

  readonly totalMedicationCount = computed(() => this.medications().length);

  ngOnInit(): void {
    this.loadMedications();
  }

  private loadMedications(): void {
    this.loading.set(true);
    this.error.set(null);
    this.medicationApi.getReconciliation(this.data.alert.encounter_id).subscribe({
      next: (response) => {
        this.medications.set(response.medications ?? []);
        this.loading.set(false);
      },
      error: (error: Error) => {
        this.error.set(error.message || 'Failed to load encounter medications.');
        this.loading.set(false);
      },
    });
  }

  manageMedication(medication: MedicationReconciliationResult | null = null): void {
    const ref = this.dialog.open(MedicationManageDialogComponent, {
      width: '640px',
      maxWidth: '95vw',
      data: {
        encounterId: this.data.alert.encounter_id,
        patientName: this.data.patientName,
        medication,
      },
    });

    ref.afterClosed().subscribe((result) => {
      if (result?.action) {
        this.loadMedications();
      }
    });
  }

  hasStage(medication: MedicationReconciliationResult, stage: EncounterStage): boolean {
    switch (stage) {
      case 'PRE_ADMIT':
        return medication.pre_admit;
      case 'INPATIENT':
        return medication.inpatient;
      case 'DISCHARGE':
        return medication.discharge;
    }
  }

  approveStage(stage: EncounterStage): void {
    if (this.approvingStage()) return;

    this.approvingStage.set(stage);
    this.physicianAlertsApi.resolveAlert(this.data.alert.id, {
      resolution_type: 'REVIEWED_ACCEPTABLE',
      resolution_note: `${stage.replace('_', ' ').toLowerCase()} medication stage approved.`,
    }).subscribe({
      next: () => {
        this.toast.success(`${stage.replace('_', ' ')} medication review approved.`);
        this.dialogRef.close({ action: 'approved', stage });
      },
      error: (error: Error) => {
        this.approvingStage.set(null);
        this.toast.error(error.message || 'Failed to approve medication review.');
      },
    });
  }

  close(): void {
    this.dialogRef.close();
  }
}
