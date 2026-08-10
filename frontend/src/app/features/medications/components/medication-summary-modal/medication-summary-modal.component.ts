import { Component, Inject, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatListModule } from '@angular/material/list';

export interface MedicationSummaryData {
  patientName: string;
  rows: { drug: string; instruction: string }[];
}

@Component({
  selector: 'app-medication-summary-modal',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule, MatListModule],
  template: `
    <h2 mat-dialog-title>Patient Medication Summary</h2>
    <mat-dialog-content>
      <p class="summary-subtitle"><strong>{{ data.patientName }}</strong> — Discharge Medication List</p>
      <mat-list>
        <mat-list-item *ngFor="let row of data.rows">
          <span matListItemTitle>{{ row.drug }}</span>
          <span matListItemLine>{{ row.instruction }}</span>
        </mat-list-item>
      </mat-list>
      <p class="summary-note">A printable PDF has been generated. Download will start on confirm.</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Close</button>
      <button mat-raised-button color="primary" (click)="download()">Download PDF</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .summary-subtitle {
      margin: 0 0 12px;
      color: #4b5563;
      font-size: 14px;
    }
    .summary-note {
      margin: 16px 0 0;
      color: #6b7280;
      font-size: 13px;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MedicationSummaryModalComponent {
  constructor(
    readonly dialogRef: MatDialogRef<MedicationSummaryModalComponent>,
    @Inject(MAT_DIALOG_DATA) readonly data: MedicationSummaryData
  ) {}

  download(): void {
    this.dialogRef.close(true);
  }
}
