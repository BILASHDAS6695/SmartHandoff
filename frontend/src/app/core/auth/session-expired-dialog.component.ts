import { Component } from '@angular/core';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';

/**
 * SessionExpiredDialogComponent — auto-dismissing "Session expired" modal.
 *
 * Displayed by IdleTimeoutService when the 30-minute idle timer fires.
 * Auto-dismissed after 5 seconds by the service; also has a manual
 * "Return to Login" button for immediate navigation.
 *
 * Accessibility:
 *   - role="alertdialog" with aria-live="assertive" for screen reader announcement
 *   - aria-labelledby links the title for assistive technologies
 *   - MatDialog handles focus trap automatically (WCAG 2.1 AA, NFR-034)
 *
 * Design refs:
 *   design.md §8.2 Authentication Flow
 *   US-059 DoD — "Session expired" modal: MatDialog with auto-dismiss and redirect to login
 */
@Component({
  selector: 'app-session-expired-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule],
  template: `
    <div role="alertdialog" aria-live="assertive" aria-labelledby="session-expired-title">
      <h2 id="session-expired-title" mat-dialog-title>Session Expired</h2>
      <mat-dialog-content>
        <p>
          Your session has expired due to 30 minutes of inactivity.
          You will be redirected to the login page.
        </p>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button
          mat-flat-button
          color="primary"
          (click)="dialogRef.close()"
          aria-label="Return to login page"
        >
          Return to Login
        </button>
      </mat-dialog-actions>
    </div>
  `,
})
export class SessionExpiredDialogComponent {
  constructor(readonly dialogRef: MatDialogRef<SessionExpiredDialogComponent>) {}
}
