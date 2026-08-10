import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  MatDialogModule,
  MatDialogRef,
  MAT_DIALOG_DATA,
} from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';

export interface AlertActionDialogData {
  title: string;
  severity?: string;
  risk?: string;
  description: string;
  checklist: string[];
  confirmLabel: string;
}

/**
 * AlertActionDialogComponent — Critical alert interrupt modal (UXR-006).
 *
 * Wireframe ref: SCR-004 Patient Detail "Active Alerts" cards.
 * Supports both "Resolve" (drug interaction) and "Review" (missing med) flows.
 */
@Component({
  selector: 'app-alert-action-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatCheckboxModule,
  ],
  template: `
    <h2 mat-dialog-title id="alert-modal-title">{{ data.title }}</h2>
    <mat-dialog-content>
      @if (data.severity || data.risk) {
        <p>
          @if (data.severity) {<strong>Severity:</strong> {{ data.severity }} | }
          @if (data.risk) {<strong>Risk:</strong> {{ data.risk }}}
        </p>
      }
      <p>{{ data.description }}</p>
      <ul class="checklist">
        @for (item of data.checklist; track item; let i = $index) {
          <li>
            <mat-checkbox [(ngModel)]="checked[i]">{{ item }}</mat-checkbox>
          </li>
        }
      </ul>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [mat-dialog-close]="null">Cancel</button>
      <button
        mat-raised-button
        color="primary"
        [disabled]="!allChecked"
        [mat-dialog-close]="{ confirmed: true, allChecked: allChecked }"
      >
        {{ data.confirmLabel }}
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .checklist {
        list-style: none;
        padding: 0;
        margin: 12px 0 0;
      }
      .checklist li {
        margin-bottom: 8px;
      }
    `,
  ],
})
export class AlertActionDialogComponent {
  private readonly dialogRef = inject<MatDialogRef<AlertActionDialogComponent>>(
    MatDialogRef,
  );
  readonly data: AlertActionDialogData = inject(MAT_DIALOG_DATA);

  checked: boolean[] = [];

  constructor() {
    this.checked = new Array(this.data.checklist.length).fill(false);
  }

  get allChecked(): boolean {
    return this.checked.every((v) => v);
  }
}
