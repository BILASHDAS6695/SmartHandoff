import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatRadioModule } from '@angular/material/radio';

export interface RejectDocumentResult {
  reason: string;
  note: string;
}

@Component({
  selector: 'sh-reject-document-modal',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatRadioModule,
  ],
  template: `
    <h2 mat-dialog-title>Reject & Return Document</h2>
    <mat-dialog-content>
      <p class="reject-subtitle">This will return the discharge summary to the queue for revision.</p>

      <label class="reason-label">Reason for rejection</label>
      <mat-radio-group [(ngModel)]="reason" class="reason-group">
        <mat-radio-button value="Incomplete information">Incomplete information</mat-radio-button>
        <mat-radio-button value="Clinical inaccuracy">Clinical inaccuracy</mat-radio-button>
        <mat-radio-button value="Missing signature">Missing signature</mat-radio-button>
        <mat-radio-button value="Other">Other</mat-radio-button>
      </mat-radio-group>

      <mat-form-field appearance="outline" class="note-field">
        <mat-label>Additional note (optional)</mat-label>
        <textarea matInput [(ngModel)]="note" rows="3" placeholder="Add details for the reviser…"></textarea>
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-raised-button color="warn" [disabled]="!reason" (click)="confirm()">Reject & Return</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .reject-subtitle {
      margin: 0 0 16px;
      color: #4b5563;
      font-size: 14px;
    }
    .reason-label {
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: #111827;
      margin-bottom: 8px;
    }
    .reason-group {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-bottom: 16px;
    }
    .note-field {
      width: 100%;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RejectDocumentModalComponent {
  private readonly dialogRef = inject(MatDialogRef<RejectDocumentModalComponent>);

  reason = '';
  note = '';

  confirm(): void {
    if (!this.reason) return;
    this.dialogRef.close({ reason: this.reason, note: this.note.trim() } as RejectDocumentResult);
  }
}
