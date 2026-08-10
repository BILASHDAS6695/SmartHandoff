import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';

export interface ApproveDocumentModalData {
  patientName: string;
  documentTitle: string;
  editCount: number;
}

/**
 * ApproveDocumentModalComponent — confirms signing off on a document.
 */
@Component({
  selector: 'sh-approve-document-modal',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule],
  templateUrl: './approve-document-modal.component.html',
  styleUrl: './approve-document-modal.component.scss',
})
export class ApproveDocumentModalComponent {
  readonly data: ApproveDocumentModalData = inject(MAT_DIALOG_DATA);
  private readonly dialogRef = inject(MatDialogRef<ApproveDocumentModalComponent>);

  cancel(): void {
    this.dialogRef.close(false);
  }

  approve(): void {
    this.dialogRef.close(true);
  }
}
