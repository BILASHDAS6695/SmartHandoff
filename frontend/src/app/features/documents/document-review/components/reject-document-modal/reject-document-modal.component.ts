import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

/**
 * RejectDocumentModalComponent — confirms returning a document to the queue.
 */
@Component({
  selector: 'sh-reject-document-modal',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
  ],
  templateUrl: './reject-document-modal.component.html',
  styleUrl: './reject-document-modal.component.scss',
})
export class RejectDocumentModalComponent {
  private readonly dialogRef = inject(MatDialogRef<RejectDocumentModalComponent>);

  reason = '';
  note = '';

  readonly reasons = [
    'Clinical information missing',
    'Incorrect medication list',
    'Discrepancy with source records',
    'Other',
  ];

  cancel(): void {
    this.dialogRef.close();
  }

  confirm(): void {
    if (!this.reason) return;
    this.dialogRef.close({ reason: this.reason, note: this.note });
  }
}
