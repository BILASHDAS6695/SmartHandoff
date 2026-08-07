/**
 * ChangePasswordDialogComponent — modal to update the user's password.
 */
import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

import { ToastService } from '@core/notifications/toast.service';

@Component({
  selector: 'app-change-password-dialog',
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
    <h2 mat-dialog-title>Change Password</h2>
    <mat-dialog-content>
      <div class="form-stack">
        <mat-form-field appearance="outline">
          <mat-label>Current Password</mat-label>
          <input matInput type="password" [(ngModel)]="currentPassword" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>New Password</mat-label>
          <input matInput type="password" [(ngModel)]="newPassword" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Confirm New Password</mat-label>
          <input matInput type="password" [(ngModel)]="confirmPassword" />
        </mat-form-field>
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button
        mat-flat-button
        color="primary"
        [disabled]="!canSubmit()"
        (click)="onSubmit()"
      >
        Update Password
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    .form-stack {
      display: grid;
      gap: 12px;
      padding-top: 8px;
    }
  `],
})
export class ChangePasswordDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<ChangePasswordDialogComponent>);
  private readonly toast = inject(ToastService);

  currentPassword = '';
  newPassword = '';
  confirmPassword = '';

  canSubmit(): boolean {
    return (
      this.currentPassword.length > 0 &&
      this.newPassword.length >= 8 &&
      this.newPassword === this.confirmPassword
    );
  }

  onSubmit(): void {
    // Wireframe only — in production call the auth API
    this.toast.success('Password updated successfully');
    this.dialogRef.close();
  }
}
