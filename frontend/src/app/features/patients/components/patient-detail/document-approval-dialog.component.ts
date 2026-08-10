import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  MatDialogModule,
  MatDialogRef,
  MAT_DIALOG_DATA,
} from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';

export interface DocumentApprovalDialogData {
  title: string;
  meta: string;
  aiAssisted?: boolean;
}

/**
 * DocumentApprovalDialogComponent — AI-assisted discharge summary approval modal.
 *
 * Wireframe ref: SCR-004 Patient Detail "Pending Approvals" card.
 */
@Component({
  selector: 'app-document-approval-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title id="doc-approval-title">Review &amp; Approve — {{ data.title }}</h2>
    <mat-dialog-content>
      <p class="meta">{{ data.meta }}</p>
      @if (data.aiAssisted) {
        <div class="ai-badge">✨ AI-Assisted — Review Required</div>
      }
      <div class="document-preview">
        <h4>Discharge Summary Draft</h4>
        <p><strong>Patient:</strong> Smith, John</p>
        <p><strong>DOB:</strong> 1975-03-15 | <strong>MRN:</strong> ●●●●●●</p>
        <p><strong>Admission Date:</strong> 2026-07-10</p>
        <p><strong>Primary Diagnosis:</strong> Congestive Heart Failure exacerbation</p>
        <p><strong>Hospital Course:</strong> Patient admitted for CHF exacerbation. IV diuresis initiated with improvement. Anticoagulation bridged for mechanical valve.</p>
        <p><strong>Discharge Medications:</strong></p>
        <ul>
          <li>Warfarin 5mg QD — monitor INR within 48h</li>
          <li>Aspirin 81mg QD</li>
          <li>Metformin 500mg BD — verify discharge Rx</li>
          <li>Furosemide 40mg QD</li>
        </ul>
        <p><strong>Follow-up:</strong> Primary care within 7 days; cardiology within 14 days.</p>
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [mat-dialog-close]="{ action: 'reject' }">Reject</button>
      <button mat-raised-button color="primary" [mat-dialog-close]="{ action: 'approve' }">Approve</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .meta {
        font-size: 12px;
        color: #6b7280;
        margin: 0 0 12px;
      }
      .ai-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 5px 12px;
        border-radius: 8px;
        background: #f0fdfa;
        border: 1px solid #2dd4bf;
        color: #0d9488;
        font-size: 11px;
        font-weight: 600;
        margin-bottom: 16px;
      }
      .document-preview {
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 16px;
        background: #f9fafb;
        font-size: 13px;
        line-height: 1.5;
      }
      .document-preview h4 {
        margin: 0 0 12px;
        font-size: 14px;
      }
      .document-preview p {
        margin: 0 0 8px;
      }
      .document-preview ul {
        margin: 0 0 8px;
        padding-left: 18px;
      }
      .document-preview li {
        margin-bottom: 4px;
      }
    `,
  ],
})
export class DocumentApprovalDialogComponent {
  private readonly dialogRef = inject<MatDialogRef<DocumentApprovalDialogComponent>>(
    MatDialogRef,
  );
  readonly data: DocumentApprovalDialogData = inject(MAT_DIALOG_DATA);
}
