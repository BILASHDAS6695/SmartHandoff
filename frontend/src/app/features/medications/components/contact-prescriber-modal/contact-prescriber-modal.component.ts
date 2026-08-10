import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';

export type ContactMethod = 'secure-message' | 'pager' | 'page-oncall';

@Component({
  selector: 'app-contact-prescriber-modal',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule, MatIconModule, MatListModule],
  template: `
    <h2 mat-dialog-title>Contact Prescriber</h2>
    <mat-dialog-content>
      <p class="prescriber-subtitle"><strong>Dr. Chen</strong> — Attending Physician</p>
      <mat-action-list class="contact-options">
        <button mat-list-item (click)="select('secure-message')">
          <mat-icon matListItemIcon>chat</mat-icon>
          <span matListItemTitle>Send secure message</span>
        </button>
        <button mat-list-item (click)="select('pager')">
          <mat-icon matListItemIcon>phone</mat-icon>
          <span matListItemTitle>Call pager #44521</span>
        </button>
        <button mat-list-item (click)="select('page-oncall')">
          <mat-icon matListItemIcon>emergency</mat-icon>
          <span matListItemTitle>Page on-call pharmacist</span>
        </button>
      </mat-action-list>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .prescriber-subtitle {
      margin: 0 0 12px;
      color: #4b5563;
      font-size: 14px;
    }
    .contact-options {
      padding: 0;
    }
    .contact-options button {
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      margin-bottom: 8px;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ContactPrescriberModalComponent {
  private readonly dialogRef = inject(MatDialogRef<ContactPrescriberModalComponent>);

  select(method: ContactMethod): void {
    this.dialogRef.close(method);
  }
}
