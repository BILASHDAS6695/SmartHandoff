/**
 * SignOutAllDialogComponent — confirmation modal to terminate all other sessions.
 */
import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';

import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@core/notifications/toast.service';

@Component({
  selector: 'app-sign-out-all-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title>Sign Out All Devices</h2>
    <mat-dialog-content>
      <p>
        This will end all active sessions except the current one. You’ll need to
        sign in again on any other device.
      </p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-flat-button color="warn" (click)="onConfirm()">
        Sign Out All
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    p {
      font-size: 13px;
      line-height: 1.5;
      margin: 8px 0 0;
    }
  `],
})
export class SignOutAllDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<SignOutAllDialogComponent>);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);

  onConfirm(): void {
    // Wireframe only — in production call the session-management API
    this.toast.success('All other devices signed out');
    this.dialogRef.close();
  }
}
