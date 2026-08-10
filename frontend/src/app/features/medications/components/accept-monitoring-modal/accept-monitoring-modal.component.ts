import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

export interface MonitoringPlanResult {
  plan: string;
}

@Component({
  selector: 'app-accept-monitoring-modal',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
  ],
  template: `
    <h2 mat-dialog-title>Accept with Monitoring Plan</h2>
    <mat-dialog-content>
      <p class="monitoring-subtitle">
        <strong>Warfarin + Aspirin</strong> — Major interaction
      </p>
      <mat-form-field appearance="outline" class="monitoring-field">
        <mat-label>Monitoring plan</mat-label>
        <textarea
          matInput
          [(ngModel)]="plan"
          rows="4"
          placeholder="e.g., Check INR within 48h; counsel patient on bleeding precautions."
        ></textarea>
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button
        mat-raised-button
        color="primary"
        [disabled]="!plan.trim()"
        (click)="confirm()"
      >
        Accept & Resolve Alert
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    .monitoring-subtitle {
      margin: 0 0 12px;
      color: #4b5563;
      font-size: 14px;
    }
    .monitoring-field {
      width: 100%;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AcceptMonitoringModalComponent {
  private readonly dialogRef = inject(MatDialogRef<AcceptMonitoringModalComponent>);

  plan = '';

  confirm(): void {
    const trimmed = this.plan.trim();
    if (!trimmed) return;
    this.dialogRef.close({ plan: trimmed } as MonitoringPlanResult);
  }
}
