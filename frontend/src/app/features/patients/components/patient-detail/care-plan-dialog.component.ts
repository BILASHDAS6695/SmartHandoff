import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  MatDialogModule,
  MatDialogRef,
  MAT_DIALOG_DATA,
} from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';

export interface CarePlanSection {
  title: string;
  items: string[];
}

export interface CarePlanDialogData {
  patientName: string;
  sections: CarePlanSection[];
}

/**
 * CarePlanDialogComponent — Readmission risk care plan modal.
 *
 * Wireframe ref: SCR-004 Patient Detail "View Care Plan" link.
 */
@Component({
  selector: 'app-care-plan-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title id="care-plan-title">Care Plan — {{ data.patientName }}</h2>
    <mat-dialog-content>
      @for (section of data.sections; track section.title) {
        <div class="care-plan-section">
          <h4>{{ section.title }}</h4>
          <ul>
            @for (item of section.items; track item) {
              <li>{{ item }}</li>
            }
          </ul>
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-raised-button color="primary" mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .care-plan-section {
        margin-bottom: 16px;
      }
      .care-plan-section h4 {
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        color: #6b7280;
        margin: 0 0 8px;
      }
      .care-plan-section ul {
        padding-left: 18px;
        margin: 0;
      }
      .care-plan-section li {
        margin-bottom: 6px;
        font-size: 13px;
        line-height: 1.5;
      }
    `,
  ],
})
export class CarePlanDialogComponent {
  private readonly dialogRef = inject<MatDialogRef<CarePlanDialogComponent>>(MatDialogRef);
  readonly data: CarePlanDialogData = inject(MAT_DIALOG_DATA);
}
