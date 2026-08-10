import { Component, Inject, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

export interface ApproveDocumentData {
  patientName: string;
  documentTitle: string;
  editCount: number;
}

@Component({
  selector: 'sh-approve-document-modal',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule, MatIconModule],
  template: `
    <h2 mat-dialog-title>Approve & Sign Document</h2>
    <mat-dialog-content>
      <p class="approve-subtitle">
        You are about to electronically sign the <strong>{{ data.documentTitle }}</strong> for
        <strong>{{ data.patientName }}</strong>.
      </p>
      <ul class="approve-checklist">
        <li><mat-icon>check</mat-icon> I have reviewed the AI-generated content and edits.</li>
        <li><mat-icon>check</mat-icon> {{ data.editCount }} edit(s) will be saved with this version.</li>
        <li><mat-icon>check</mat-icon> This action is final and will lock the document.</li>
      </ul>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-raised-button color="primary" (click)="confirm()">Approve & Sign</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .approve-subtitle {
      margin: 0 0 16px;
      color: #4b5563;
      font-size: 14px;
    }
    .approve-checklist {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .approve-checklist li {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #111827;
    }
    .approve-checklist mat-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      color: #16a34a;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApproveDocumentModalComponent {
  constructor(
    readonly dialogRef: MatDialogRef<ApproveDocumentModalComponent>,
    @Inject(MAT_DIALOG_DATA) readonly data: ApproveDocumentData,
  ) {}

  confirm(): void {
    this.dialogRef.close(true);
  }
}
